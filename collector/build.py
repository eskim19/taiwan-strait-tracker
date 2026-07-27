"""전체 파이프라인 엔트리포인트.

    수집 → 정규화 → 클러스터링 → 신뢰도 산출 → JSON 출력

한 피드가 죽어도 나머지로 계속 진행하고, 실패 내역은 build_meta 에 남겨
사이트 하단에 그대로 표시한다. 조용히 넘어가면 데이터가 비어도 정상으로 보인다.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

from . import feeds as feedreg
from . import mnd
from .cluster import cluster_articles
from .fetch import fetch_all
from .normalize import normalize_all
from .score import GRADE_DESC, GRADE_LABEL, build_events, grade_summary
from .util import enable_utf8_stdout, iso, utcnow

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"
ARCHIVE = DATA / "archive"

# 메인 피드에 유지할 기간. 그 이전 사건은 월별 아카이브로만 남는다.
ROLLING_DAYS = 14


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def merge_events(previous, current):
    """이전 실행 결과와 병합.

    수집 창(21일)보다 롤링 창이 짧아 보통은 current 가 상위집합이지만,
    피드가 일시적으로 죽은 회차에 사건이 통째로 사라지는 걸 막는다.
    """
    merged = {e["id"]: e for e in previous}
    for event in current:
        merged[event["id"]] = event  # 새로 계산한 쪽이 항상 우선
    return list(merged.values())


def prune(events, days=ROLLING_DAYS):
    cutoff = iso(utcnow() - timedelta(days=days))
    kept = [e for e in events if e["last_seen"] >= cutoff]
    kept.sort(key=lambda e: (e["last_seen"], e["credibility"]["score"]), reverse=True)
    return kept


def update_archive(events):
    """월별 아카이브 갱신. 사건 ID 기준으로 덮어쓴다."""
    by_month = defaultdict(list)
    for event in events:
        by_month[event["first_seen"][:7]].append(event)

    written = []
    for month, items in by_month.items():
        path = ARCHIVE / f"{month}.json"
        existing = load_json(path, {"events": []}).get("events", [])
        merged = {e["id"]: e for e in existing}
        for event in items:
            merged[event["id"]] = event
        ordered = sorted(merged.values(), key=lambda e: e["last_seen"], reverse=True)
        write_json(path, {"month": month, "n_events": len(ordered), "events": ordered})
        written.append(month)
    return sorted(written)


def sources_payload():
    """UI 범례용 등급표 노출. 판정 근거를 사용자가 직접 확인할 수 있어야 한다."""
    grouped = defaultdict(list)
    for domain, (tier, bloc, name, bias) in sorted(feedreg.SOURCES.items()):
        grouped[tier].append(
            {
                "domain": domain,
                "name": name,
                "bloc": bloc,
                "bloc_label": feedreg.BLOC_LABEL_KO.get(bloc, bloc),
                "bias": bias,
            }
        )
    return {
        "updated": iso(utcnow()),
        "tiers": [
            {
                "tier": tier,
                "label": feedreg.TIER_LABEL_KO.get(tier, tier),
                "weight": feedreg.TIER_WEIGHT[tier],
                "sources": grouped.get(tier, []),
            }
            for tier in ("T1", "TA", "T2", "T3", "T4", "T5")
        ],
        "blocs": [
            {"key": key, "label": label}
            for key, label in feedreg.BLOC_LABEL_KO.items()
        ],
        "grade_rules": [
            {"grade": g, "label": GRADE_LABEL[g], "rule": GRADE_DESC[g]}
            for g in ("A", "B", "C", "D")
        ],
        "syndicators_excluded": list(feedreg.SYNDICATORS),
    }


def run(skip_mnd=False, skip_fetch=False):
    started = utcnow()
    print(f"[1/5] 피드 수집 — {len(feedreg.FEEDS)}개")

    if skip_fetch:
        results, reports = [], []
    else:
        results, reports = fetch_all()

    ok = [r for r in reports if r["status"] in ("ok", "not_modified")]
    failed = [r for r in reports if r["status"] == "error"]
    print(f"      성공 {len(ok)} / 실패 {len(failed)}")
    for report in failed:
        print(f"      실패: {report['name']} — {report['error']}")

    print("[2/5] 정규화")
    drops = Counter()
    articles = normalize_all(results, drops=drops)
    raw_count = sum(len(p.entries) for _, p in results)
    print(f"      원본 {raw_count} → 채택 {len(articles)}  (탈락 {dict(drops)})")

    print("[3/5] 클러스터링")
    groups = cluster_articles(articles)
    cross = sum(1 for g in groups if len({a['lang'] for a in g}) > 1)
    print(f"      사건 {len(groups)}건 (교차언어 병합 {cross}건)")

    print("[4/5] 신뢰도 산출")
    events = build_events(groups)
    previous = load_json(DATA / "events.json", {"events": []}).get("events", [])
    events = prune(merge_events(previous, events))
    grades = grade_summary(events)
    print(f"      등급 분포 {grades}")

    print("[5/5] 국방부 집계 + JSON 출력")
    tension_note = None
    if skip_mnd:
        tension = load_json(DATA / "tension.json", {"records": []})
    else:
        try:
            records, added = mnd.scrape(pages=1)
            tension = mnd.save(records)
            print(f"      국방부 신규 {added}건 / 누적 {len(tension['records'])}건")
        except Exception as exc:
            tension = load_json(DATA / "tension.json", {"records": []})
            tension_note = f"{type(exc).__name__}: {exc}"
            print(f"      국방부 수집 실패 — {tension_note} (기존 데이터 유지)")

    months = update_archive(events)

    meta = {
        "updated": iso(utcnow()),
        "duration_sec": round((utcnow() - started).total_seconds(), 1),
        "rolling_days": ROLLING_DAYS,
        "n_events": len(events),
        "n_articles": sum(e["credibility"]["n_articles"] for e in events),
        "grades": grades,
        "cross_language_events": sum(1 for e in events if e["cross_language"]),
        "tension_error": tension_note,
        "archive_months": months,
        "feeds": [
            {
                "id": r["id"],
                "name": r["name"],
                "status": r["status"],
                "http": r["http"],
                "n_entries": r["n_entries"],
                "error": r["error"],
            }
            for r in reports
        ],
    }

    write_json(DATA / "events.json", {"updated": meta["updated"], "events": events})
    write_json(DATA / "sources.json", sources_payload())
    write_json(DATA / "build_meta.json", meta)

    last = tension["records"][-1] if tension.get("records") else None
    print(
        f"\n완료 {meta['duration_sec']}초 — 사건 {len(events)}건, "
        f"등급 {grades}, 아카이브 {months}"
    )
    if last:
        ratio = f", 평소 대비 {last['ratio']}배" if last.get("ratio") else ""
        print(f"긴장도 최신 {last['date']}: 지수 {last['index']}{ratio}")
    return meta


def main():
    parser = argparse.ArgumentParser(description="양안 뉴스 트래커 빌드")
    parser.add_argument("--skip-mnd", action="store_true", help="국방부 수집 건너뛰기")
    parser.add_argument("--skip-fetch", action="store_true", help="피드 수집 건너뛰기")
    args = parser.parse_args()
    run(skip_mnd=args.skip_mnd, skip_fetch=args.skip_fetch)


if __name__ == "__main__":
    enable_utf8_stdout()
    main()
