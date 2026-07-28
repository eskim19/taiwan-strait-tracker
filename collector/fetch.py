"""RSS 수집. 피드별 예외 격리 + 조건부 GET.

feedparser 에 URL 을 직접 주면 기본 User-Agent 로 403 을 맞는 피드가 있다
(SCMP 는 Cloudflare, Kyodo·연합 은 자체 차단). requests 로 브라우저 UA 를 붙여
받은 뒤 바이트를 feedparser 에 넘긴다. 대신 feedparser 내장 ETag 처리를
못 쓰게 되므로 state/etag.json 으로 직접 관리한다.
"""

from __future__ import annotations

import json
import random
import ssl
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import certifi
import feedparser
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

from . import feeds as feedreg
from .util import enable_utf8_stdout, short_error

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "state" / "etag.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
    # Accept-Language 는 일부러 보내지 않는다. Google News 는 hl/gl 을 URL 로 받고,
    # 헤더로 언어를 주면 레이트리밋이 예민해진다는 보고가 있다.
}
TIMEOUT = (5, 20)


class _RelaxedStrictAdapter(HTTPAdapter):
    """RFC 5280 확장 필드 엄격 검사만 끈 TLS 어댑터.

    Python 3.13 부터 기본 SSL 컨텍스트가 VERIFY_X509_STRICT 를 켠다. 대만
    국방부(mnd.gov.tw) 인증서는 Subject Key Identifier 확장이 없어 여기서
    막힌다. 인증서 체인·호스트명 검증은 그대로 두고 이 검사만 완화한다
    (verify=False 로 전부 끄는 것과 다르다).
    """

    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.load_verify_locations(cafile=certifi.where())
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def make_session():
    session = requests.Session()
    session.headers.update(HEADERS)
    session.mount("https://", _RelaxedStrictAdapter())
    return session


def load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def fetch_one(feed, state, session, use_cache=True):
    """피드 하나를 받아 (parsed, report) 반환. 실패해도 예외를 올리지 않는다."""
    feed_id = feed["id"]
    report = {
        "id": feed_id,
        "name": feed["name"],
        "status": "ok",
        "http": None,
        "n_entries": 0,
        "newest": None,
        "error": None,
    }

    cached = state.get(feed_id, {}) if use_cache else {}
    headers = dict(HEADERS)
    if cached.get("etag"):
        headers["If-None-Match"] = cached["etag"]
    if cached.get("last_modified"):
        headers["If-Modified-Since"] = cached["last_modified"]

    try:
        resp = session.get(feed["url"], headers=headers, timeout=TIMEOUT)
    except requests.RequestException as exc:
        report["status"] = "error"
        report["error"] = short_error(exc)
        return None, report

    report["http"] = resp.status_code

    if resp.status_code == 304:
        report["status"] = "not_modified"
        return None, report

    if resp.status_code != 200:
        report["status"] = "error"
        report["error"] = f"HTTP {resp.status_code}"
        return None, report

    parsed = feedparser.parse(resp.content)
    if parsed.bozo and not parsed.entries:
        report["status"] = "error"
        report["error"] = f"파싱 실패: {parsed.get('bozo_exception')}"
        return None, report

    report["n_entries"] = len(parsed.entries)
    if not parsed.entries:
        report["status"] = "empty"

    newest = newest_entry_date(parsed)
    if newest:
        report["newest"] = newest.isoformat()

    # 성공한 응답만 캐시 갱신
    new_cache = {}
    if resp.headers.get("ETag"):
        new_cache["etag"] = resp.headers["ETag"]
    if resp.headers.get("Last-Modified"):
        new_cache["last_modified"] = resp.headers["Last-Modified"]
    new_cache["fetched_at"] = datetime.now(timezone.utc).isoformat()
    state[feed_id] = new_cache

    return parsed, report


def entry_datetime(entry):
    """RSS 항목에서 UTC datetime 추출. 없으면 None."""
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        stamp = entry.get(key)
        if stamp:
            try:
                return datetime(*stamp[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def newest_entry_date(parsed):
    stamps = [entry_datetime(e) for e in parsed.entries]
    stamps = [s for s in stamps if s]
    return max(stamps) if stamps else None


def fetch_all(only=None, use_cache=True, jitter=True):
    """전 피드 수집. (feed, parsed) 목록과 리포트 목록 반환."""
    state = load_state()
    session = make_session()
    results, reports = [], []

    targets = [f for f in feedreg.FEEDS if not only or f["id"] in only]
    for i, feed in enumerate(targets):
        if jitter and i:
            time.sleep(random.uniform(1.0, 2.2))
        parsed, report = fetch_one(feed, state, session, use_cache=use_cache)
        reports.append(report)
        if parsed is not None:
            results.append((feed, parsed))

    save_state(state)
    return results, reports


STALE_DAYS = 7


def check(only=None):
    """--check: 피드 생존 진단. 좀비 피드(신화통신형)를 조기에 잡는다."""
    results, reports = fetch_all(only=only, use_cache=False)
    now = datetime.now(timezone.utc)

    width = max(len(r["name"]) for r in reports)
    print(f"{'피드':<{width}}  {'HTTP':>5}  {'항목':>4}  최신 항목")
    print("-" * (width + 40))

    problems = []
    for report in reports:
        newest_txt = "-"
        if report["newest"]:
            newest = datetime.fromisoformat(report["newest"])
            age = (now - newest).days
            newest_txt = f"{newest:%Y-%m-%d} ({age}일 전)"
            if age > STALE_DAYS:
                newest_txt += "  [정체]"
                problems.append(f"{report['name']}: 최신 항목이 {age}일 전 — 좀비 피드 의심")
        if report["status"] == "error":
            problems.append(f"{report['name']}: {report['error']}")
        print(
            f"{report['name']:<{width}}  {str(report['http'] or '-'):>5}  "
            f"{report['n_entries']:>4}  {newest_txt}"
        )

    print()
    if problems:
        print("문제:")
        for p in problems:
            print(f"  - {p}")
    else:
        print("전 피드 정상")
    return results, reports, problems


if __name__ == "__main__":
    enable_utf8_stdout()
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    check(only=args or None)
