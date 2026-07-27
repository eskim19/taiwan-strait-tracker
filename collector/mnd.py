"""대만 국방부 일일 PLA 활동 집계 스크래퍼.

언론 보도량과 무관한 유일한 객관 지표. 국방부는 매일 06시(UTC+8) 기준으로
직전 24시간 동안 대만 주변에서 포착한 중국군 항공기 소티·해군 함정·관공선 수를
정형 문장으로 발표한다.

    "3 sorties of PLA aircraft, 7 PLAN ships and 4 official ships operating
     around Taiwan were detected as of 6 a.m. (UTC+8) today.
     1 out of 3 sorties crossed the median line of the Taiwan Strait..."

이 문장이 사실상 고정 템플릿이라 정규식으로 안정적으로 뽑힌다.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from datetime import date, datetime
from pathlib import Path

from .fetch import make_session
from .util import enable_utf8_stdout

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "docs" / "data" / "tension.json"

BASE = "https://www.mnd.gov.tw"
LIST_URL = BASE + "/en/news/plaactlist/{page}"
TOTAL_PAGES = 11
TIMEOUT = (6, 25)

_DETAIL_LINK = re.compile(r'href="([^"]*?/PLAAct/(\d+))"', re.IGNORECASE)
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

_DATE = re.compile(r"PLA Activities\s+(\d{4})\.(\d{1,2})\.(\d{1,2})")
_AIRCRAFT = re.compile(r"(\d+)\s+sorties?\s+of\s+PLA\s+aircraft", re.IGNORECASE)
_NAVY = re.compile(r"(\d+)\s+PLAN\s+ships?", re.IGNORECASE)
_OFFICIAL = re.compile(r"(\d+)\s+official\s+ships?", re.IGNORECASE)
_BALLOON = re.compile(r"(\d+)\s+(?:PLA\s+)?balloons?", re.IGNORECASE)
# 중간선 통과: "N out of M sorties crossed" / "N of them crossed" / "N sorties crossed"
_CROSSED = re.compile(
    r"(\d+)\s+(?:out\s+of\s+\d+\s+)?(?:sorties?\s+|of\s+(?:them|the\s+detected\s+sorties)\s+)?"
    r"(?:sorties?\s+)?cross(?:ed)?\s+the\s+median\s+line",
    re.IGNORECASE,
)
_NONE_CROSSED = re.compile(
    r"(?:none|no)\s+(?:of\s+them\s+|sorties?\s+)?cross(?:ed)?\s+the\s+median\s+line",
    re.IGNORECASE,
)


def page_text(html):
    return _WS.sub(" ", _TAGS.sub(" ", html)).strip()


def list_detail_ids(session, page):
    """목록 페이지에서 상세 URL 목록 추출."""
    resp = session.get(LIST_URL.format(page=page), timeout=TIMEOUT)
    resp.raise_for_status()
    seen, urls = set(), []
    for href, num in _DETAIL_LINK.findall(resp.text):
        if num in seen:
            continue
        seen.add(num)
        urls.append((num, href if href.startswith("http") else BASE + href))
    return urls


def parse_detail(html):
    """상세 페이지 → 일일 집계 레코드. 날짜를 못 찾으면 None."""
    text = page_text(html)

    m = _DATE.search(text)
    if not m:
        return None
    year, month, day = (int(x) for x in m.groups())
    try:
        stamp = date(year, month, day)
    except ValueError:
        return None

    def first_int(pattern, default=0):
        found = pattern.search(text)
        return int(found.group(1)) if found else default

    aircraft = first_int(_AIRCRAFT)
    navy = first_int(_NAVY)
    official = first_int(_OFFICIAL)
    balloons = first_int(_BALLOON)

    if _NONE_CROSSED.search(text):
        crossed = 0
    else:
        crossed = first_int(_CROSSED)
    # 통과 소티가 전체 소티를 넘을 수는 없다(정규식 오매칭 방어)
    crossed = min(crossed, aircraft)

    return {
        "date": stamp.isoformat(),
        "aircraft": aircraft,
        "navy_ships": navy,
        "official_ships": official,
        "balloons": balloons,
        "crossed_median": crossed,
    }


def tension_index(record):
    """긴장도 지수. 함정은 체류 시간이 길어 항공기보다 무겁게 잡는다."""
    return record["aircraft"] + 2 * record["navy_ships"] + record["official_ships"]


def load_existing():
    if OUT_PATH.exists():
        try:
            data = json.loads(OUT_PATH.read_text(encoding="utf-8"))
            return {r["date"]: r for r in data.get("records", [])}
        except (json.JSONDecodeError, OSError, KeyError):
            return {}
    return {}


def scrape(pages=1, session=None, existing=None, delay=0.4, verbose=False):
    """최신 pages 개 목록 페이지를 훑어 새 레코드만 수집.

    이미 가진 날짜의 상세 페이지는 다시 받지 않는다.
    """
    session = session or make_session()
    existing = load_existing() if existing is None else existing
    records = dict(existing)
    added = 0

    for page in range(1, pages + 1):
        try:
            links = list_detail_ids(session, page)
        except Exception as exc:  # 목록 실패 시 그 페이지만 건너뛴다
            if verbose:
                print(f"  목록 {page}쪽 실패: {type(exc).__name__}: {exc}")
            continue

        for _, url in links:
            try:
                time.sleep(delay)
                resp = session.get(url, timeout=TIMEOUT)
                resp.raise_for_status()
                record = parse_detail(resp.text)
            except Exception as exc:
                if verbose:
                    print(f"  상세 실패 {url}: {type(exc).__name__}: {exc}")
                continue
            if not record:
                if verbose:
                    print(f"  파싱 실패 {url}")
                continue
            if record["date"] not in records:
                added += 1
                if verbose:
                    print(
                        f"  + {record['date']}  항공기 {record['aircraft']:3}  "
                        f"함정 {record['navy_ships']:3}  관공선 {record['official_ships']:3}  "
                        f"중간선통과 {record['crossed_median']:3}"
                    )
            records[record["date"]] = record

    return records, added


BASELINE_DAYS = 90


def build_payload(records):
    """날짜순 정렬 + 지수·기준선 대비 배율 계산."""
    ordered = [records[k] for k in sorted(records)]
    for i, rec in enumerate(ordered):
        rec["index"] = tension_index(rec)

    for i, rec in enumerate(ordered):
        window = [r["index"] for r in ordered[max(0, i - BASELINE_DAYS) : i]]
        # 절대값은 계절성·훈련주기 때문에 해석이 어렵다. 직전 90일 중앙값 대비
        # 배율로 표기해야 "평소보다 얼마나 심한 날인가"가 읽힌다.
        if len(window) >= 14:
            median = statistics.median(window)
            rec["baseline"] = round(median, 1)
            rec["ratio"] = round(rec["index"] / median, 2) if median else None
        else:
            rec["baseline"] = None
            rec["ratio"] = None

    return {
        "updated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": "대만 국방부 (mnd.gov.tw) 일일 PLA 활동 발표",
        "source_url": BASE + "/en/news/PlaactList",
        "baseline_days": BASELINE_DAYS,
        "index_formula": "항공기 소티 + 2×해군 함정 + 관공선",
        "records": ordered,
    }


def save(records):
    payload = build_payload(records)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return payload


def main():
    parser = argparse.ArgumentParser(description="대만 국방부 PLA 일일 집계 수집")
    parser.add_argument(
        "--backfill", action="store_true", help=f"전체 {TOTAL_PAGES}쪽 백필(최초 1회)"
    )
    parser.add_argument("--pages", type=int, default=1)
    args = parser.parse_args()

    pages = TOTAL_PAGES if args.backfill else args.pages
    print(f"국방부 PLA 집계 수집 — {pages}쪽")
    records, added = scrape(pages=pages, verbose=True)
    payload = save(records)
    print(f"\n신규 {added}건 / 누적 {len(payload['records'])}건 → {OUT_PATH}")
    if payload["records"]:
        last = payload["records"][-1]
        print(
            f"최신 {last['date']}: 지수 {last['index']}"
            + (f" (평소 대비 {last['ratio']}배)" if last.get("ratio") else "")
        )


if __name__ == "__main__":
    enable_utf8_stdout()
    main()
