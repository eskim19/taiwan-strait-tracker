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
from .util import enable_utf8_stdout, write_json

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "docs" / "data" / "tension.json"

BASE = "https://www.mnd.gov.tw"
LIST_URL = BASE + "/en/news/plaactlist/{page}"
# 국방부는 2020-11-14 까지 208쪽을 공개한다(실측: 12쪽=2026-04, 100쪽=2024-02,
# 208쪽=2020-11). 2022년 8월 펠로시 방문 위기와 2024년 연합리검 훈련이 이 범위
# 안에 있어, 지금 지수가 평시인지 위기인지 비교할 기준선을 만들 수 있다.
FULL_HISTORY_PAGES = 210
TIMEOUT = (6, 25)

_DETAIL_LINK = re.compile(r'href="([^"]*?/PLAAct/(\d+))"', re.IGNORECASE)
_LIST_DATE = re.compile(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})")
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

_DATE = re.compile(r"PLA Activities\s+(\d{4})\.(\d{1,2})\.(\d{1,2})")

# 국방부는 문구를 여러 번 바꿨다. 두 형식을 모두 받아야 한다.
#   2024년형: "27 PLA aircraft and 7 PLAN vessels operating around Taiwan were
#             detected up until 6 a.m. … 19 of the aircraft crossed the median line"
#   2026년형: "3 sorties of PLA aircraft, 7 PLAN ships and 4 official ships …
#             detected as of 6 a.m. … 1 out of 3 sorties crossed the median line"
# 한쪽만 지원하면 나머지 기간이 통째로 0으로 기록되고, 그 0이 기준선을 오염시켜
# 평시/위기 비교를 무의미하게 만든다.
_AIRCRAFT = re.compile(
    r"(\d+)\s+(?:sorties?\s+of\s+)?PLA(?:AF)?\s+(?:aircraft|planes?|warplanes?)",
    re.IGNORECASE,
)
_NAVY = re.compile(r"(\d+)\s+PLAN\s+(?:ships?|vessels?)", re.IGNORECASE)
_OFFICIAL = re.compile(r"(\d+)\s+official\s+ships?", re.IGNORECASE)
_BALLOON = re.compile(r"(\d+)\s+(?:PLA\s+)?balloons?", re.IGNORECASE)
# 중간선 통과: "N out of M sorties crossed" / "N of the aircraft crossed"
# / "N of them crossed" / "N sorties crossed"
_CROSSED = re.compile(
    r"(\d+)\s+(?:out\s+of\s+\d+\s+)?"
    r"(?:sorties?\s+|of\s+(?:them|the\s+aircraft|the\s+detected\s+sorties)\s+)?"
    r"(?:sorties?\s+|aircraft\s+)?cross(?:ed)?\s+the\s+median\s+line",
    re.IGNORECASE,
)
_NONE_CROSSED = re.compile(
    r"(?:none|no)\s+(?:of\s+them\s+|sorties?\s+)?cross(?:ed)?\s+the\s+median\s+line",
    re.IGNORECASE,
)
# 이 문장은 활동이 0인 날에도 반드시 나온다. 파싱 성공 여부의 판정 기준.
_DETECTED = re.compile(
    r"(?:were|was)\s+detected\s+as\s+of|operating\s+around\s+Taiwan", re.IGNORECASE
)


def page_text(html):
    return _WS.sub(" ", _TAGS.sub(" ", html)).strip()


def list_detail_ids(session, page):
    """목록 페이지에서 (날짜, URL) 목록 추출.

    날짜를 여기서 뽑는 것이 핵심이다. 상세 페이지를 받아야만 날짜를 알 수 있으면
    이미 가진 날짜도 매번 다시 받게 되고, 5년치(약 1,870건) 백필 이후에는 매시
    실행마다 1,870건을 정부 서버에 다시 요청하게 된다.
    """
    resp = session.get(LIST_URL.format(page=page), timeout=TIMEOUT)
    resp.raise_for_status()
    text = resp.text

    seen, items = set(), []
    for match in _DETAIL_LINK.finditer(text):
        href, num = match.group(1), match.group(2)
        if num in seen:
            continue
        seen.add(num)
        # 목록 항목의 날짜는 링크 바로 앞에 온다
        window = page_text(text[max(0, match.start() - 400) : match.end()])
        found = _LIST_DATE.findall(window)
        stamp = None
        if found:
            year, month, day = (int(x) for x in found[-1])
            try:
                stamp = date(year, month, day).isoformat()
            except ValueError:
                stamp = None
        items.append((stamp, href if href.startswith("http") else BASE + href))
    return items


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

    matched = set()

    def first_int(name, pattern, default=0):
        found = pattern.search(text)
        if found:
            matched.add(name)
            return int(found.group(1))
        return default

    aircraft = first_int("aircraft", _AIRCRAFT)
    navy = first_int("navy", _NAVY)
    official = first_int("official", _OFFICIAL)
    balloons = first_int("balloon", _BALLOON)

    if _NONE_CROSSED.search(text):
        crossed = 0
    else:
        crossed = first_int("crossed", _CROSSED)
    # 통과 소티가 전체 소티를 넘을 수는 없다(정규식 오매칭 방어)
    crossed = min(crossed, aircraft)

    # '0으로 발표됨' 과 '정규식이 안 걸림' 을 구분한다.
    #
    # 보고 문장이 있다는 것만으로는 부족하다 — 실제로 겪은 일인데, 국방부가
    # 2024년에 쓰던 "27 PLA aircraft and 7 PLAN vessels" 형식은 그 문장을
    # 갖고 있어 통과했지만 숫자 정규식이 전부 빗나가 2년치가 0으로 쌓였다.
    # 그 0이 기준선 중앙값을 무너뜨려 '평소 대비 113배' 같은 헛수치를 만든다.
    # 그래서 숫자를 실제로 하나라도 뽑았는지까지 확인한다.
    parse_ok = bool(_DETECTED.search(text)) and bool(matched & {"aircraft", "navy"})

    return {
        "date": stamp.isoformat(),
        "aircraft": aircraft,
        "navy_ships": navy,
        "official_ships": official,
        "balloons": balloons,
        "crossed_median": crossed,
        "parse_ok": parse_ok,
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
    added = skipped = failed = 0

    for page in range(1, pages + 1):
        try:
            links = list_detail_ids(session, page)
        except Exception as exc:  # 목록 실패 시 그 페이지만 건너뛴다
            if verbose:
                print(f"  목록 {page}쪽 실패: {type(exc).__name__}: {exc}")
            continue

        for stamp, url in links:
            # 이미 가진 날짜는 상세 페이지를 받지 않는다. 목록에서 날짜를 뽑는
            # 이유가 이것이다 — 이게 없으면 매 실행마다 전체를 재다운로드한다.
            if stamp and stamp in records:
                skipped += 1
                continue
            try:
                time.sleep(delay)
                resp = session.get(url, timeout=TIMEOUT)
                resp.raise_for_status()
                record = parse_detail(resp.text)
            except Exception as exc:
                failed += 1
                if verbose:
                    print(f"  상세 실패 {url}: {type(exc).__name__}: {exc}")
                continue
            if not record:
                failed += 1
                if verbose:
                    print(f"  파싱 실패 {url}")
                continue
            if not record.get("parse_ok"):
                # 날짜는 읽혔는데 집계 문장을 못 찾았다. 0으로 기록하면
                # 조용한 오염이 되므로 아예 버린다.
                failed += 1
                if verbose:
                    print(f"  집계 문장 없음 {record['date']} — 형식 변경 의심 {url}")
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

    return records, {"added": added, "skipped": skipped, "failed": failed}


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
    write_json(OUT_PATH, payload)
    return payload


def main():
    parser = argparse.ArgumentParser(description="대만 국방부 PLA 일일 집계 수집")
    parser.add_argument(
        "--backfill", action="store_true",
        help=f"공개 이력 전체({FULL_HISTORY_PAGES}쪽 ≈ 2020-11~) 백필. 최초 1회만",
    )
    parser.add_argument("--pages", type=int, default=None)
    parser.add_argument("--delay", type=float, default=None, help="요청 간격(초)")
    args = parser.parse_args()

    pages = args.pages if args.pages else (FULL_HISTORY_PAGES if args.backfill else 1)
    delay = args.delay if args.delay is not None else (1.2 if args.backfill else 0.4)
    print(f"국방부 PLA 집계 수집 — {pages}쪽 (요청 간격 {delay}초)")
    records, stats = scrape(pages=pages, verbose=True, delay=delay)
    payload = save(records)
    print(
        f"\n신규 {stats['added']}건 / 재사용 {stats['skipped']}건 / "
        f"실패 {stats['failed']}건 / 누적 {len(payload['records'])}건 → {OUT_PATH}"
    )
    if payload["records"]:
        last = payload["records"][-1]
        print(
            f"최신 {last['date']}: 지수 {last['index']}"
            + (f" (평소 대비 {last['ratio']}배)" if last.get("ratio") else "")
        )


if __name__ == "__main__":
    enable_utf8_stdout()
    main()
