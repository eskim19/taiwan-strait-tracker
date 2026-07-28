"""사건 클러스터링.

2단 구조다.

1단 — 언어 내 TF-IDF 코사인
    같은 언어끼리는 어휘가 겹치므로 표준적인 방법이 통한다. 중국어·일본어는
    형태소 분석기 없이 char n-gram 으로 처리하고, 한국어도 교착어라 어절
    토큰보다 char n-gram 이 안정적이다.

2단 — 엔티티 시그니처로 교차언어 병합
    한국어 기사와 중국어 기사는 어휘 교집합이 0 이라 코사인으로는 영원히
    묶이지 않는다. 임베딩 없이 이걸 푸는 방법이 gazetteer 기반 시그니처다.

병합은 보수적으로 간다. 과병합(다른 사건을 하나로 묶음)은 없는 교차검증을
만들어내 신뢰도 등급을 조작하는 셈이라, 미병합(사건이 쪼개져 보임)보다 훨씬
해롭다.
"""

from __future__ import annotations

import math
from collections import Counter

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .gazetteer import anchors, extract_numbers, signature
from .util import normalize_text

WINDOW_HOURS = 48
# 언어별 코사인 임계. 제목만 있는 언어(중국어 애그리게이터)는 조금 더 엄격하게.
SIM_THRESHOLD = {"en": 0.34, "ko": 0.40, "zh": 0.40, "ja": 0.40}
DEFAULT_THRESHOLD = 0.38

# 시그니처 병합 조건.
#
# 유사도는 Jaccard 가 아니라 **겹침계수**(shared / min(|A|,|B|)) 를 쓴다.
# 사건이 커지면 "훈련 발표" 클러스터 옆에 "외교부 규탄" 클러스터가 생기는데,
# 후자는 요소가 더 많다. Jaccard 는 합집합으로 나누므로 그 추가 요소가 분모를
# 부풀려 오히려 병합을 막는다. 겹침계수는 작은 쪽이 큰 쪽에 들어앉는지를 본다.
# 실측: Jaccard 파편화 8장 / Dice 6장 / 겹침계수 1장.
SIG_OVERLAP = 0.35        # 0.20~0.45 가 평탄역, 0.50 에서 절벽 → 평탄역 위쪽
MIN_SHARED_WEIGHT = 1.0
# 전체 기사의 이 비율을 넘게 등장하는 엔티티는 변별력이 없어 시그니처에서 뺀다
# (거의 모든 기사에 taiwan_strait 가 들어 있다).
COMMON_ENTITY_RATIO = 0.40
# 한 사건의 총 기간 상한. _gap_hours 는 스팬 사이 간격만 재므로 클러스터가
# 커질수록 스팬이 길어져 코퍼스 전체를 훑는 연쇄가 생긴다.
# 48시간은 안 된다 — 실탄사격 사건 자체가 48.4시간이다.
MAX_EVENT_SPAN_HOURS = 72

# 앵커가 하나뿐일 때 그 앵커에 허용되는 최대 문서빈도.
#
# 흔한 앵커(military_drill) 단독 병합을 막으려 도입했다가 **빈도로는 좋은
# 앵커와 나쁜 앵커를 가를 수 없다**는 것을 다시 확인했다. 라이브에서는
# military_drill 28.7% > live_fire 16.1% 인데 스냅샷에서는 live_fire 28.9% >
# military_drill 23.4% 로 순서가 뒤집힌다. 어떤 값을 잡아도 코퍼스가 바뀌면
# 반대로 동작한다 — IDF 가중이 실패한 것과 정확히 같은 이유다.
#
# 그래서 상한을 사실상 끄고, 과병합은 어휘(EVENT 엔티티 정밀화)와 골드
# 라벨 확장으로 잡는다. 1.0 을 넘기면 이 규칙은 비활성이다.
SOLO_ANCHOR_MAX_DF = 1.01


def _vectorizer(lang):
    if lang == "en":
        return TfidfVectorizer(
            analyzer="word", ngram_range=(1, 2), sublinear_tf=True,
            min_df=1, stop_words="english",
        )
    if lang == "ko":
        # 교착어라 어절 토큰은 조사 때문에 흩어진다
        return TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True)
    # zh / ja — 띄어쓰기가 없어 char n-gram 이 사실상 유일한 선택
    return TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3), sublinear_tf=True)


def _text_for(article):
    return normalize_text(f"{article['title']} {article.get('summary', '')}")


def cluster_one_language(articles, lang):
    """한 언어 안에서 묶기. 기사 인덱스 그룹 목록 반환."""
    if len(articles) < 2:
        return [[i] for i in range(len(articles))]

    texts = [_text_for(a) for a in articles]
    try:
        matrix = _vectorizer(lang).fit_transform(texts)
    except ValueError:
        # 어휘가 하나도 안 잡히는 극단적 경우
        return [[i] for i in range(len(articles))]

    sim = cosine_similarity(matrix)
    distance = np.clip(1.0 - sim, 0.0, 1.0)
    np.fill_diagonal(distance, 0.0)

    # 시간창 밖의 쌍은 최대 거리로 밀어 병합을 막는다
    stamps = np.array([a["published"].timestamp() for a in articles])
    gap_hours = np.abs(stamps[:, None] - stamps[None, :]) / 3600.0
    distance[gap_hours > WINDOW_HOURS] = 1.0

    # 숫자가 충돌하면 다른 회차다. 국방부 일일 집계 제목이 지뢰인데,
    # TfidfVectorizer 의 기본 token_pattern 이 한 자리 숫자를 버려서
    # "11 ships, 4 aircraft"(7/21) 와 "11 ships, 3 aircraft"(7/27) 의
    # 코사인이 1.000 이 된다. 시간창만으로는 인접일을 막지 못한다.
    numbers = [extract_numbers(a["title"]) for a in articles]
    for i in range(len(articles)):
        for j in range(i + 1, len(articles)):
            if numbers[i] and numbers[j] and not (numbers[i] & numbers[j]):
                distance[i, j] = distance[j, i] = 1.0

    threshold = SIM_THRESHOLD.get(lang, DEFAULT_THRESHOLD)
    model = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=1.0 - threshold,
        metric="precomputed",
        # 평균연결. 단일연결은 짧은 제목에서 체인이 생겨 무관한 기사까지
        # 줄줄이 엮인다.
        linkage="average",
    )
    labels = model.fit_predict(distance)

    groups = {}
    for idx, label in enumerate(labels):
        groups.setdefault(int(label), []).append(idx)
    return list(groups.values())


def _core_signature(articles, common):
    """클러스터의 대표 시그니처.

    구성원 다수가 공유하는 요소만 남긴다. 단순 합집합을 쓰면 클러스터가 커질수록
    시그니처가 비대해져 Jaccard 가 떨어지고 병합이 안 된다.
    """
    counts = Counter()
    for article in articles:
        counts.update(signature(f"{article['title']} {article.get('summary', '')}"))
    need = max(1, math.ceil(0.4 * len(articles)))
    return {key for key, count in counts.items() if count >= need} - common


def _signature_stats(articles):
    """시그니처 요소별 문서빈도 → (변별력 없는 요소 집합, IDF 가중치)."""
    counts = Counter()
    for article in articles:
        counts.update(signature(f"{article['title']} {article.get('summary', '')}"))
    total = len(articles)
    limit = COMMON_ENTITY_RATIO * total
    common = {key for key, count in counts.items() if count > limit}
    weights = {key: math.log(1 + total / count) for key, count in counts.items()}
    frequency = {key: count / total for key, count in counts.items()}
    return common, weights, frequency


def _weight_of(elements, weights):
    return sum(weights.get(e, 1.0) for e in elements)


def _weighted_overlap(a, b, weights):
    """겹침계수 — 작은 쪽 시그니처가 큰 쪽에 들어앉는 정도."""
    if not a or not b:
        return 0.0, 0.0
    shared = _weight_of(a & b, weights)
    smaller = min(_weight_of(a, weights), _weight_of(b, weights))
    return (shared / smaller if smaller else 0.0), shared


def _time_span(articles):
    stamps = [a["published"] for a in articles]
    return min(stamps), max(stamps)


def _gap_hours(span_a, span_b):
    (start_a, end_a), (start_b, end_b) = span_a, span_b
    overlap_start = max(start_a, start_b)
    overlap_end = min(end_a, end_b)
    return max(0.0, (overlap_start - overlap_end).total_seconds() / 3600.0)


def merge_cross_language(groups, common, weights, frequency):
    """언어별 클러스터를 시그니처로 병합.

    union-find 로 한 번에 잇지 않는다. 그렇게 하면 A-B 가 닮고 B-C 가 닮았다는
    이유만으로 전혀 다른 A 와 C 가 한 사건이 되는 연쇄 병합이 생긴다(실측에서
    "PHL-191 로켓" 기사가 "헬기 중간선 통과" 사건에 붙었다).

    대신 매번 가장 닮은 쌍 하나만 합치고, 합친 뒤 시그니처를 구성원 전체의
    합의로 다시 계산한다. 세 번째 클러스터는 개별 구성원이 아니라 이 '합의'와
    닮아야 들어올 수 있어 연쇄가 끊긴다.
    """
    clusters = [list(g) for g in groups]
    signatures = [_core_signature(c, common) for c in clusters]
    spans = [_time_span(c) for c in clusters]

    while True:
        best = None
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                sig_a, sig_b = signatures[i], signatures[j]
                # 앵커 게이트 — 공유 요소 중 최소 하나가 사건 유형·고유명·큰 숫자여야
                # 병합을 연다. 행위자(pla 등)만 공유하는 쌍은 유사도가 아무리 높아도
                # 막는다. 이걸 허용하면 정밀도가 1.000 → 0.893 으로 무너진다.
                shared_anchors = anchors(sig_a & sig_b)
                if not shared_anchors:
                    continue
                # 흔한 앵커 하나만 공유하는 것으로는 부족하다(위 상수 주석 참조)
                if len(shared_anchors) == 1:
                    only = next(iter(shared_anchors))
                    if frequency.get(only, 0.0) > SOLO_ANCHOR_MAX_DF:
                        continue
                score, shared_weight = _weighted_overlap(sig_a, sig_b, weights)
                if shared_weight < MIN_SHARED_WEIGHT or score < SIG_OVERLAP:
                    continue
                if _gap_hours(spans[i], spans[j]) > WINDOW_HOURS:
                    continue
                # 병합 결과의 총 기간이 상한을 넘으면 연쇄로 번지고 있다는 뜻
                merged_span = (
                    max(spans[i][1], spans[j][1]) - min(spans[i][0], spans[j][0])
                ).total_seconds() / 3600.0
                if merged_span > MAX_EVENT_SPAN_HOURS:
                    continue
                if best is None or score > best[0]:
                    best = (score, i, j)
        if best is None:
            break

        _, i, j = best
        clusters[i].extend(clusters[j])
        signatures[i] = _core_signature(clusters[i], common)
        spans[i] = _time_span(clusters[i])
        del clusters[j], signatures[j], spans[j]

    return clusters


def cluster_articles(articles):
    """기사 목록 → 사건별 기사 묶음 목록.

    같은 사건을 3개 언어로 보도한 기사가 한 묶음에 들어오는지가 이 함수의
    핵심 테스트다.
    """
    if not articles:
        return []

    by_lang = {}
    for article in articles:
        by_lang.setdefault(article["lang"], []).append(article)

    groups = []
    for lang, items in by_lang.items():
        for index_group in cluster_one_language(items, lang):
            groups.append([items[i] for i in index_group])

    common, weights, frequency = _signature_stats(articles)
    groups = merge_cross_language(groups, common, weights, frequency)

    for group in groups:
        group.sort(key=lambda a: a["published"])
    groups.sort(key=lambda g: max(a["published"] for a in g), reverse=True)
    return groups
