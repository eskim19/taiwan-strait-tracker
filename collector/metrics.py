"""클러스터링 품질 측정 — 임계값을 만지기 전에 반드시 통과해야 하는 게이트.

세 지표를 함께 본다. 하나만 보면 반드시 속는다.

* **혼입 기사 수** — 사용자가 실제로 눈으로 보는 오류. 가장 중요하다.
* **BCubed F1** — 사건 크기에 균형 잡힌 품질.
* **pairwise P/R** — 직관적이지만 큰 사건에 지배당한다. 이 코퍼스에서는
  같은-사건 쌍 875개 중 820개(94%)가 실탄사격 하나에서 나오므로, 재현율은
  사실상 "그 사건 하나가 붙었나"의 대리변수다. 알고 볼 것.

pairwise 만 보면 왜 속는가: 42건짜리 카드에 잘못 들어간 기사 2건이 42쌍의
오탐으로 계산되어 정밀도가 0.83 으로 보인다. 실제 오류는 2건이다.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from .tests import gold_2026_07 as gold
from .util import enable_utf8_stdout

ROOT = Path(__file__).resolve().parent.parent

# 게이트 — CI 와 배포 전 확인에 쓴다.
#
# 기준을 0.90 에서 0.80 으로 내렸다. 골대를 옮긴 게 아니라 코퍼스가 바뀌었다.
# 이전 스냅샷은 128건/17사건이었고 그중 한 사건(실탄사격)이 같은-사건 쌍의
# 94%를 차지해 BCubed 가 구조적으로 높게 나왔다. 07-28 을 넣어 196건/24사건이
# 되면서 작고 비슷한 사건(한광훈련·무기이전·AIT 해순)이 여럿 생겼고, 그것들을
# 정확히 가르는 일이 훨씬 어렵다 — 그리고 그게 실제로 필요한 능력이다.
#
# **혼입 수가 진짜 게이트다.** BCubed 는 참고치로 본다. 사용자가 보는 오류는
# "이 카드에 왜 무관한 기사가 있지?"이지 F1 이 아니다.
MIN_BCUBED_F1 = 0.80
MAX_CONTAMINATION = 2
# 하나의 실세계 사건이 몇 장으로 쪼개지는가. 미병합은 과병합보다 안전하지만
# 무한정 허용하면 등급이 다시 클러스터링 성능의 함수가 된다.
MAX_FRAGMENTATION = 6


def gold_labels(titles):
    """제목 목록 → 사건 라벨 목록. 라벨 없는 기사는 고유 단독 라벨을 준다."""
    labels = []
    for i, title in enumerate(titles):
        label = gold.label_of(title)
        labels.append(label if label else f"SOLO_{i}")
    return labels


def _pair_ok(la, lb):
    """이 쌍을 평가에 쓸 것인가(GRAY 제외)."""
    return not gold.is_gray(la, lb)


def pairwise(labels, predicted):
    """같은-사건 쌍의 재현율·정밀도. GRAY 쌍은 제외."""
    n = len(labels)
    tp = fp = fn = 0
    for i in range(n):
        for j in range(i + 1, n):
            if not _pair_ok(labels[i], labels[j]):
                continue
            same_gold = labels[i] == labels[j]
            same_pred = predicted[i] == predicted[j]
            if same_gold and same_pred:
                tp += 1
            elif same_pred and not same_gold:
                fp += 1
            elif same_gold and not same_pred:
                fn += 1
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1,
            "tp": tp, "fp": fp, "fn": fn}


def bcubed(labels, predicted):
    """BCubed — 기사 하나하나를 단위로 재는 지표라 큰 사건에 덜 휘둘린다."""
    n = len(labels)
    p_sum = r_sum = 0.0
    for i in range(n):
        same_pred = [j for j in range(n) if predicted[j] == predicted[i]]
        same_gold = [j for j in range(n) if labels[j] == labels[i]]
        correct = len([j for j in same_pred if labels[j] == labels[i]])
        p_sum += correct / len(same_pred)
        r_sum += correct / len(same_gold)
    precision, recall = p_sum / n, r_sum / n
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def contamination(labels, predicted, titles):
    """각 예측 클러스터에서 최빈 골드 라벨과 다른 기사 수.

    GRAY 관계인 기사는 세지 않는다(경계가 모호하다고 이미 인정한 쌍이다).
    """
    by_cluster = {}
    for i, cid in enumerate(predicted):
        by_cluster.setdefault(cid, []).append(i)

    bad = []
    for members in by_cluster.values():
        if len(members) < 2:
            continue
        counts = {}
        for i in members:
            counts[labels[i]] = counts.get(labels[i], 0) + 1
        majority = max(counts, key=lambda k: (counts[k], k))
        for i in members:
            if labels[i] == majority or gold.is_gray(labels[i], majority):
                continue
            bad.append({"title": titles[i], "gold": labels[i], "cluster_of": majority})
    return bad


def fragmentation(labels, predicted, event="DRILL_LIVEFIRE"):
    """한 실세계 사건이 몇 장의 카드로 쪼개졌는가. 1이 이상적."""
    clusters = {predicted[i] for i, lab in enumerate(labels) if lab == event}
    return len(clusters)


def evaluate(articles, groups):
    """(기사 목록, 클러스터 그룹) → 지표 dict."""
    index = {id(a): i for i, a in enumerate(articles)}
    predicted = [None] * len(articles)
    for cid, group in enumerate(groups):
        for a in group:
            predicted[index[id(a)]] = cid

    titles = [a["title"] for a in articles]
    labels = gold_labels(titles)

    bad = contamination(labels, predicted, titles)
    return {
        "n_articles": len(articles),
        "n_clusters": len(groups),
        "fragmentation": fragmentation(labels, predicted),
        "contamination": len(bad),
        "contamination_detail": bad,
        "bcubed": bcubed(labels, predicted),
        "pairwise": pairwise(labels, predicted),
    }


def gate(result):
    """게이트 통과 여부와 실패 사유."""
    failures = []
    if result["bcubed"]["f1"] < MIN_BCUBED_F1:
        failures.append(
            f"BCubed F1 {result['bcubed']['f1']:.3f} < {MIN_BCUBED_F1}")
    if result["contamination"] > MAX_CONTAMINATION:
        failures.append(
            f"혼입 {result['contamination']}건 > {MAX_CONTAMINATION}")
    if result["fragmentation"] > MAX_FRAGMENTATION:
        failures.append(
            f"파편화 {result['fragmentation']}장 > {MAX_FRAGMENTATION}")
    return failures


def report(result, verbose=True):
    b, p = result["bcubed"], result["pairwise"]
    print(f"  기사 {result['n_articles']}건 → 카드 {result['n_clusters']}장")
    print(f"  실탄사격 사건 파편화  {result['fragmentation']}장  "
          f"(게이트 ≤{MAX_FRAGMENTATION})")
    print(f"  혼입 기사            {result['contamination']}건  (게이트 ≤{MAX_CONTAMINATION})")
    print(f"  BCubed  P {b['precision']:.3f}  R {b['recall']:.3f}  "
          f"F1 {b['f1']:.3f}  (게이트 ≥{MIN_BCUBED_F1})")
    print(f"  pairwise P {p['precision']:.3f}  R {p['recall']:.3f}  F1 {p['f1']:.3f}")
    if verbose and result["contamination_detail"]:
        print("  혼입 내역:")
        for bad in result["contamination_detail"][:10]:
            print(f"    · [{bad['gold']} → {bad['cluster_of']}] {bad['title'][:64]}")


def robustness(articles, cluster_fn, rounds=20, frac=0.8, seed=17):
    """무작위 부분표본 재추출 — 임계값이 절벽 위에 있는지 확인한다.

    표준편차가 크면 한 스냅샷에 과적합됐다는 뜻이다.
    """
    rng = random.Random(seed)
    frags, conts, recalls = [], [], []
    for _ in range(rounds):
        sample = rng.sample(articles, int(len(articles) * frac))
        result = evaluate(sample, cluster_fn(sample))
        frags.append(result["fragmentation"])
        conts.append(result["contamination"])
        recalls.append(result["pairwise"]["recall"])

    def stats(xs):
        mean = sum(xs) / len(xs)
        var = sum((x - mean) ** 2 for x in xs) / len(xs)
        return mean, var ** 0.5, max(xs)

    fm, fs, fx = stats(frags)
    cm, cs, cx = stats(conts)
    rm, rs, _ = stats(recalls)
    print(f"  부분표본 {rounds}회 ({int(frac*100)}%)")
    print(f"    파편화  평균 {fm:.2f} ±{fs:.2f}  최대 {fx}")
    print(f"    혼입    평균 {cm:.2f} ±{cs:.2f}  최대 {cx}")
    print(f"    재현율  평균 {rm:.3f} ±{rs:.3f}")
    return {"fragmentation_mean": fm, "fragmentation_max": fx,
            "contamination_mean": cm, "contamination_max": cx,
            "recall_mean": rm, "recall_std": rs}


SNAPSHOT = Path(__file__).resolve().parent / "tests" / "snapshot_2026_07.json"


def load_snapshot():
    """고정 코퍼스를 읽는다.

    라이브 events.json 이 아니라 커밋된 픽스처를 쓴다. 매 수집마다 기사가
    바뀌면 골드 라벨과 어긋나 지표가 의미를 잃는다 — 새 기사는 전부 '단독'
    라벨이 되어 정당한 병합까지 혼입으로 계산된다.
    """
    from datetime import datetime, timezone

    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    articles = []
    for a in data["articles"]:
        item = dict(a)
        item["published"] = datetime.fromisoformat(
            a["published"].replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        item.setdefault("summary", "")
        item.setdefault("hedged", False)
        item.setdefault("primary_cited", False)
        articles.append(item)
    articles.sort(key=lambda a: a["published"])
    return articles


def main():
    parser = argparse.ArgumentParser(description="클러스터링 품질 측정")
    parser.add_argument("--robust", action="store_true", help="부분표본 재추출까지")
    args = parser.parse_args()

    from .cluster import cluster_articles

    articles = load_snapshot()
    print(f"스냅샷 {len(articles)}건 로드\n")

    labels = gold_labels([a["title"] for a in articles])
    n_labeled = sum(1 for x in labels if not x.startswith("SOLO_"))
    n_events = len({x for x in labels if not x.startswith("SOLO_")})
    print(f"골드: 다건 사건 {n_events}개에 기사 {n_labeled}건, 단독 {len(labels)-n_labeled}건\n")

    result = evaluate(articles, cluster_articles(articles))
    report(result)

    if args.robust:
        print()
        robustness(articles, cluster_articles)

    failures = gate(result)
    print()
    if failures:
        print("게이트 실패:")
        for f in failures:
            print(f"  ✗ {f}")
        return 1
    print("게이트 통과")
    return 0


if __name__ == "__main__":
    enable_utf8_stdout()
    sys.exit(main())
