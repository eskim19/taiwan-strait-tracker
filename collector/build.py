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
from .gazetteer import ENTITY_LABEL_KO
from .normalize import normalize_all
from .score import (
    D_DESC,
    D_LABEL,
    GRADE_CAVEAT,
    GRADE_DESC,
    GRADE_LABEL,
    build_events,
    grade_summary,
)
from .util import (
    enable_utf8_stdout,
    iso,
    short_error,
    utcnow,
    write_json,
    write_json_if_changed,
)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"
ARCHIVE = DATA / "archive"

# 메인 피드에 유지할 기간. 그 이전 사건은 월별 아카이브로만 남는다.
ROLLING_DAYS = 14


def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        # 조용히 넘어가면 누적 데이터가 사라진 걸 아무도 모른다
        print(f"      ! {path.name} 읽기 실패 — {type(exc).__name__}: {exc}")
        return default


# 잘못 게시된 사건을 내리는 유일한 수단. 아카이브는 ID 기준 덮어쓰기라
# 여기 넣지 않으면 한 번 올라간 사건을 제거할 방법이 없다.
BLOCKED_EVENT_IDS = set()


def merge_events(previous, current):
    """이전 실행 결과와 병합.

    수집 창(21일)보다 롤링 창이 짧아 보통은 current 가 상위집합이지만,
    피드가 일시적으로 죽은 회차에 사건이 통째로 사라지는 걸 막는다.

    두 가지를 지킨다.

    1. **기사 하나가 두 카드에 있으면 안 된다.** 이전 판은 옛 사건이 새 사건에
       완전히 *포함될 때만* 버렸다. 클러스터링이 과병합됐던 사건을 쪼개면
       옛 상위집합은 아무 것과도 매칭되지 않고 살아남아, 같은 기사가 두 장에
       동시에 노출됐다(실측 5건, 아카이브에는 영구 잔존). 이제 **교집합이
       있으면** 옛 사건을 버린다.
    2. 기사 수가 줄어드는 갱신은 신뢰도 판정만 유지한다. 피드가 한 회차
       죽었다고 등급이 강등되면 안 되지만, 이전 판처럼 last_seen·헤드라인까지
       통째로 동결하면 정당한 정정이 영원히 반영되지 않는다.
    """
    merged = {e["id"]: e for e in previous}

    for event in current:
        old = merged.get(event["id"])
        if old and old["credibility"]["n_articles"] > event["credibility"]["n_articles"]:
            # 수집이 일시적으로 얕아진 것으로 보고 등급만 이전 값을 쓴다.
            # 나머지(시각·헤드라인·기사 목록)는 새 계산을 따른다.
            event = dict(event)
            event["credibility"] = old["credibility"]
        merged[event["id"]] = event

    return list(drop_ghosts(merged, current).values())


def drop_ghosts(merged, current):
    """이번 회차 사건과 기사가 겹치는 옛 사건을 버린다.

    events.json 과 아카이브가 **같은 규칙을 써야 한다.** 처음에는 이 로직이
    merge_events 안에만 있었고 update_archive 는 ID 기준 덮어쓰기만 했다.
    그래서 롤링 창은 깨끗한데 아카이브에는 유령이 영구히 쌓였다(selfcheck 가
    기사 6건 중복 노출로 잡아냈다). 아카이브는 prune 이 없어 한 번 들어가면
    BLOCKED_EVENT_IDS 말고는 뺄 방법이 없다 — 더 엄격해야 할 쪽이다.
    """
    current_ids = {e["id"] for e in current}
    current_articles = set()
    for event in current:
        current_articles.update(a["id"] for a in event["articles"])

    survivors = {}
    for event_id, event in merged.items():
        if event_id in current_ids:
            survivors[event_id] = event
            continue
        own = {a["id"] for a in event["articles"]}
        if not own or (own & current_articles):
            continue  # 기사가 없거나, 이번 회차 사건과 겹친다 → 유령
        survivors[event_id] = event
    return survivors


def assert_no_shared_articles(events):
    """한 기사가 두 사건에 있으면 즉시 드러낸다.

    이 불변식이 없어서 중복 노출이 배포되고 아카이브에 영구히 박혔다.
    조용히 넘기면 다음에도 똑같이 나간다.
    """
    owner = {}
    clashes = []
    for event in events:
        for article in event["articles"]:
            prev = owner.get(article["id"])
            if prev and prev != event["id"]:
                clashes.append((article["id"], prev, event["id"]))
            owner[article["id"]] = event["id"]
    return clashes


def prune(events, days=ROLLING_DAYS):
    cutoff = iso(utcnow() - timedelta(days=days))
    kept = [
        e for e in events
        if e["last_seen"] >= cutoff and e["id"] not in BLOCKED_EVENT_IDS
    ]
    kept.sort(key=lambda e: (e["last_seen"], e["credibility"]["score"]), reverse=True)
    return kept


def update_archive(events):
    """월별 아카이브 갱신. 사건 ID 기준으로 덮어쓰되 유령은 버린다."""
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
        # events.json 과 같은 규칙. 이게 없어서 롤링 창은 깨끗한데 아카이브에만
        # 유령이 쌓였다 — 아카이브는 prune 이 없어 한 번 들어가면 영구다.
        merged = drop_ghosts(merged, items)
        for blocked in BLOCKED_EVENT_IDS:
            merged.pop(blocked, None)
        ordered = sorted(merged.values(), key=lambda e: e["last_seen"], reverse=True)
        clashes = assert_no_shared_articles(ordered)
        if clashes:
            print(f"      ! {path.name}: 기사 중복 노출 {len(clashes)}건")
            for article_id, a, b in clashes[:5]:
                print(f"        {article_id} ∈ {a}, {b}")
            raise SystemExit("아카이브 병합 불변식 위반")
        write_json_if_changed(
            path, {"month": month, "n_events": len(ordered), "events": ordered},
            volatile=(),
        )
        written.append(month)
    return sorted(written)


STALE_FEED_DAYS = 7


def _is_stale(report):
    """최신 항목이 오래된 피드. 200 을 주면서 죽어 있는 경우를 잡는다."""
    if not report.get("newest"):
        return False
    from datetime import datetime

    newest = datetime.fromisoformat(report["newest"])
    return (utcnow() - newest).days > STALE_FEED_DAYS


def feed_health(report, n_adopted, critical):
    """피드 하나의 상태 판정 — 낮은 카디널리티 문자열.

    커밋 여부(write_json_if_changed)를 이 값으로 정한다. 원시 계측
    (n_entries·newest·http)은 매 실행 달라져 커밋을 강제하지만, 이 값은
    '죽었다/살았다'가 바뀔 때만 변한다.

    no_adopt 가 이 함수의 존재 이유다. 200 을 주고 항목도 100개 있는데 채택이
    0건인 상태 — 구글 뉴스가 최신순에서 관련도순으로 빠져 한 달 지난 기사만
    돌려주는 실패(2026-07-27 실측)와 동의 인터스티셜이 여기 걸린다. status 도
    stale 도 이걸 못 잡는다. 저빈도 피드는 정상적으로도 0건인 회차가 있으므로
    중대 피드에만 적용한다.
    """
    if report["status"] == "error":
        return "error"
    if report["status"] == "empty":
        return "empty"
    if _is_stale(report):
        return "stale"
    if critical and report["status"] == "ok" and report["n_entries"] and not n_adopted:
        return "no_adopt"
    return "ok"


# build_meta 는 '상태'와 '계측'이 섞여 있다. 커밋 여부는 상태만으로 정한다.
# 계측(측정 시각·소요·항목 수·최신 항목 시각)은 매 실행 달라지므로 여기 넣으면
# 3시간마다 커밋이 강제된다. 반대로 피드 status·health·error 는 상태다 —
# T1 경로가 죽으면 그 회차에 바로 커밋돼 사이트에 드러나야 한다.
_META_VOLATILE = ("updated", "duration_sec")
_FEED_VOLATILE = ("http", "n_entries", "n_adopted", "newest")


def meta_fingerprint(meta):
    core = {k: v for k, v in meta.items() if k not in _META_VOLATILE and k != "feeds"}
    core["feeds"] = [
        {k: v for k, v in feed.items() if k not in _FEED_VOLATILE}
        for feed in meta.get("feeds", [])
    ]
    return core


def unrated_queue(events, limit=20):
    """미분류 도메인 승격 대기열.

    `unknown` 진영은 '사람이 계속 등급표에 올린다'는 전제 위에서만 안전한데,
    그 대기열이 없으면 전제가 성립하지 않는다. 빈도순으로 남겨 운영자가
    feeds.SOURCES 에 한 줄씩 추가할 수 있게 한다.
    """
    counts = Counter()
    sample = {}
    for event in events:
        for article in event["articles"]:
            if article.get("bloc") != "unknown":
                continue
            domain = article.get("source_domain") or "?"
            counts[domain] += 1
            sample.setdefault(domain, article["title"][:80])
    return [
        {"domain": d, "n_articles": n, "sample_title": sample.get(d, "")}
        for d, n in counts.most_common(limit)
    ]


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
        "d_reasons": [
            {"key": k, "label": D_LABEL[k], "rule": D_DESC[k]} for k in D_DESC
        ],
        "grade_caveat": GRADE_CAVEAT,
        # 등급표는 소유·자금 구조 기준이지 개별 기사의 정확도 평가가 아니다.
        # 이걸 밝히지 않으면 정치적 판단을 객관 지표처럼 제시하는 셈이 된다.
        "tier_basis": (
            "등급은 매체의 소유·자금 구조와 취재망을 기준으로 부여한 것이며, "
            "개별 기사의 정확도를 평가한 것이 아니다. 동의하지 않으면 "
            "collector/feeds.py 의 SOURCES 를 고쳐 쓰면 된다."
        ),
        "entity_labels": [
            {"key": key, "label": label}
            for key, label in sorted(ENTITY_LABEL_KO.items())
        ],
        "syndicators_excluded": list(feedreg.SYNDICATORS),
    }


def run(skip_mnd=False, skip_fetch=False, rebuild=False):
    started = utcnow()
    if rebuild:
        # 클러스터링·등급 규칙이 바뀌면 사건 ID 가 전부 바뀐다. 이전 결과를
        # 안고 가면 옛 파편 카드가 최대 14일(아카이브는 영구) 나란히 남는다.
        for path in [DATA / "events.json"] + sorted(ARCHIVE.glob("*.json")):
            backup = path.with_suffix(".json.bak")
            if path.exists():
                path.replace(backup)
                print(f"      마이그레이션: {path.name} → {backup.name}")
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

    clashes = assert_no_shared_articles(events)
    if clashes:
        print(f"      ! 기사 중복 노출 {len(clashes)}건 — 사건 병합 규칙 위반")
        for article_id, a, b in clashes[:5]:
            print(f"        {article_id} ∈ {a}, {b}")
        raise SystemExit("사건 병합 불변식 위반 — 중복 카드를 배포할 수 없다")

    print("[5/5] 국방부 집계 + JSON 출력")
    tension_note = None
    if skip_mnd:
        tension = load_json(DATA / "tension.json", {"records": []})
    else:
        try:
            records, stats = mnd.scrape(pages=1)
            tension = mnd.save(records)
            print(
                f"      국방부 신규 {stats['added']}건 / 재사용 {stats['skipped']}건"
                f" / 실패 {stats['failed']}건 / 누적 {len(tension['records'])}건"
            )
            if stats["failed"]:
                tension_note = f"상세 {stats['failed']}건 파싱 실패 — 형식 변경 의심"
        except Exception as exc:
            tension = load_json(DATA / "tension.json", {"records": []})
            tension_note = short_error(exc)
            print(f"      국방부 수집 실패 — {tension_note} (기존 데이터 유지)")

    months = update_archive(events)

    adopted = Counter(a.get("feed_id") for a in articles)
    critical_ids = {f["id"] for f in feedreg.FEEDS if f.get("critical")}
    tier_counts = Counter(a["tier"] for e in events for a in e["articles"])

    meta = {
        "updated": iso(utcnow()),
        # 하루 단위 생존 신호. 초 단위 값만으로는 '변경 없으면 커밋 생략'이
        # 영원히 죽고, 아무 값도 없으면 사이트가 '수집기가 아직 살아 있는가'를
        # 말할 방법이 없다 — "마지막 갱신 3일 전"은 조용한 사망과 구분되지
        # 않는다. 하루 1커밋은 감당할 수 있고, 예약 워크플로가 저장소 비활동으로
        # 꺼지는 것도 막는다.
        "checked": iso(utcnow())[:10],
        "duration_sec": round((utcnow() - started).total_seconds(), 1),
        "rolling_days": ROLLING_DAYS,
        "n_events": len(events),
        "n_articles": sum(e["credibility"]["n_articles"] for e in events),
        "grades": grades,
        "cross_language_events": sum(1 for e in events if e["cross_language"]),
        "tension_error": tension_note,
        "archive_months": months,
        "all_feeds_failed": bool(reports) and not ok,
        # 등급을 실제로 끌어올리는 것은 T1 통신사인데, 실측 코퍼스에서 T1 은
        # 157건 중 7건(4.5%)·도메인 4개뿐이다. 이 분포가 조용히 무너지는 것이
        # '러너 IP 에서 구글 뉴스가 막혔다'의 유일한 사이트 측 지문이다.
        # 둘 다 events 에서 파생되므로 churn 이 늘지 않는다.
        "tier_articles": dict(sorted(tier_counts.items())),
        "t1_domains": sorted(
            {a["source_domain"] for e in events for a in e["articles"] if a["tier"] == "T1"}
        ),
        # newest 를 담아야 좀비 피드(200 을 주면서 몇 달 전 기사만 내보내는
        # 신화통신형)를 UI 가 표시할 수 있다. 없으면 사람이 fetch --check 를
        # 손으로 돌려야만 발견되는데, 무인 운영에서는 아무도 안 돌린다.
        "feeds": [
            {
                "id": r["id"],
                "name": r["name"],
                "critical": r["id"] in critical_ids,
                "status": r["status"],
                "health": feed_health(r, adopted.get(r["id"], 0), r["id"] in critical_ids),
                "http": r["http"],
                "n_entries": r["n_entries"],
                "n_adopted": adopted.get(r["id"], 0),
                "newest": r.get("newest"),
                "stale": _is_stale(r),
                "error": r["error"],
            }
            for r in reports
        ],
        "unrated_domains": unrated_queue(events),
    }

    write_json_if_changed(DATA / "events.json", {"updated": meta["updated"], "events": events})
    write_json_if_changed(DATA / "sources.json", sources_payload())
    write_json_if_changed(DATA / "build_meta.json", meta, fingerprint=meta_fingerprint)

    # 전 피드 실패는 조용히 넘기면 안 된다. 이전에는 수집이 0건이어도
    # 이전 사건을 그대로 재커밋하고 종료코드 0 을 냈다 — 전면 장애가 나도
    # Actions 는 초록불이고 최대 14일간 낡은 데이터가 나간다.
    if reports and not ok:
        print("      ! 전 피드 수집 실패 — 낡은 데이터를 재게시하지 않는다")
        raise SystemExit("모든 피드 수집 실패")
    if meta["feeds"] and any(f["stale"] for f in meta["feeds"]):
        stale_names = [f["name"] for f in meta["feeds"] if f["stale"]]
        print(f"      ! 정체 의심 피드: {', '.join(stale_names)}")

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
    parser.add_argument(
        "--rebuild", action="store_true",
        help="이전 사건·아카이브를 .bak 으로 밀어내고 처음부터 다시 생성"
             " (클러스터링 규칙 변경 시 1회)",
    )
    args = parser.parse_args()
    run(skip_mnd=args.skip_mnd, skip_fetch=args.skip_fetch, rebuild=args.rebuild)


if __name__ == "__main__":
    enable_utf8_stdout()
    main()
