"""신뢰도 등급 산출 + 사건 객체 조립.

이 트래커의 핵심 판단이 여기 있다. 규칙은 전부 명시적이고, 산출된 등급에는
항상 근거 문자열이 따라붙는다. 점수만 보여주면 없는 정밀도를 오해한다.

가장 중요한 설계 결정은 '독립성'을 도메인이 아니라 진영으로 재는 것이다.
환구시보·신화·CGTN 이 같은 사건을 동시에 보도해도 그것은 독립된 세 증언이
아니라 한 정부의 한 발표다. 도메인 수로만 세면 관영매체 일제 보도가 최고
신뢰도를 받는 사고가 난다.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from . import feeds as feedreg
from .gazetteer import ENTITY_LABEL_KO, extract_entities
from .util import containment, iso, sha1, title_numbers, title_tokens

GRADE_LABEL = {
    "A": "검증됨",
    "B": "개연적",
    "C": "단일 출처",
    "D": "미교차",
}

GRADE_DESC = {
    "A": "독립된 출처 3곳 이상이 보도했고 통신사·공영방송 또는 분석기관이 포함됨",
    "B": "독립된 출처 2곳이 보도했거나, 통신사·공영방송이 단독 보도함",
    "C": "독립 출처가 한 곳뿐이라 교차 확인되지 않음",
    "D": "발표 주체 밖의 독립 확인이 아직 없음",
}

# D 는 사유가 셋인데 하나의 라벨('주의')로 뭉뚱그리면 내용의 신빙성을
# 의심하라는 뜻으로 읽힌다. 실제 규칙이 말하는 것은 '확인 상태'다.
D_LABEL = {
    "state_only": "발표 단독",
    "unrated": "출처 미확인",
    "partisan": "성향 단독",
}

D_DESC = {
    "state_only": "한 진영의 공식 발표·국영매체만 있고 그 밖의 확인이 아직 없음",
    "unrated": "등급표에 없는 매체만 보도해 출처 성격을 판정할 수 없음",
    "partisan": "뚜렷한 당파 성향 매체가 단독 보도함",
}

# 등급표 상단에 고정으로 노출한다. D 를 '틀렸다'로 읽는 오해가 가장 크다.
GRADE_CAVEAT = (
    "D는 보도 내용이 틀렸다는 뜻이 아니다. 발표 주체 밖의 독립 확인이 아직 "
    "없다는 뜻이다. 국가 통신사의 정례 보도는 대개 사실이지만, 이 트래커가 "
    "재는 것은 사실 여부가 아니라 교차 확인 여부다."
)


# ---------------------------------------------------------------------------
# 원고군 — 같은 취재를 몇 번 세지 않기 위한 장치
# ---------------------------------------------------------------------------
# 진영 개념만으로는 막지 못하는 구멍이 둘 있었다.
#
#   1) 와이어 전재. 로이터 기사 하나를 세 매체가 그대로 실으면 도메인이 3개라
#      '독립 3곳'이 되어 A등급이 나온다. 실제 증언은 하나다.
#   2) 발표 받아쓰기. 대만 매체 여러 곳이 국방부 보도자료 하나를 옮기면
#      '독립 N곳'이 된다.
#
# 척도 선택은 실측으로 했다. char n-gram·LCS·SequenceMatcher 는 전부 실패한다 —
# 중국어에서는 독립 취재끼리도 台海·實彈 같은 덩어리를 대량 공유해 유사도가
# 올라가고, 일일 집계 템플릿("11 ships, 4 aircraft" vs "11 ships, 3 aircraft")은
# 다른 날 다른 보도인데 LCS 0.95 다. 토큰 containment 만이 두 집단을 가른다.

COPY_CONTAINMENT = 0.75   # 0.72~0.85 구간에서 등급 분포가 동일 — 임계에 둔감
COPY_MIN_TOKENS = 3

# 집계 보도임을 알리는 어휘. 이게 있고 큰 숫자를 공유하면 같은 발표 인용이다.
_TALLY_VOCAB = re.compile(
    r"sortie|aircraft|warplane|ships?|vessels?"
    r"|架次|機艦|机舰|軍機|军机|共機|共机|艦艇|舰艇|共艦|共舰"
    r"|군용기|함정|항공기|척",
    re.IGNORECASE,
)
TALLY_MIN_NUMBER = 4      # '連2天' 같은 흔한 소수를 지문으로 쓰지 않는다
TALLY_MIN_SHARED = 2


def _tally_numbers(title):
    return {n for n in title_numbers(title) if n >= TALLY_MIN_NUMBER}


def same_copy(a, b):
    """같은 원고의 재게재인가."""
    if a["lang"] != b["lang"]:
        return False   # 교차언어 전재는 토큰 교집합이 0이라 이 방법으로는 못 잡는다
    na, nb = title_numbers(a["title"]), title_numbers(b["title"])
    if na and nb and not (na & nb):
        return False   # 숫자가 다르면 다른 회차다
    ta = title_tokens(a["title"], a["lang"])
    tb = title_tokens(b["title"], b["lang"])
    if min(len(ta), len(tb)) < COPY_MIN_TOKENS:
        return False
    return containment(ta, tb) >= COPY_CONTAINMENT


def same_release(a, b):
    """같은 공식 발표(국방부 일일 집계 등)를 옮긴 것인가.

    받아쓰기는 원고가 아니라 숫자를 공유한다. 제목 유사도로는 원리적으로
    잡을 수 없다 — 받아쓰기와 독립 취재의 유사도 분포가 겹친다.
    """
    if not (_TALLY_VOCAB.search(a["title"]) and _TALLY_VOCAB.search(b["title"])):
        return False
    shared = _tally_numbers(a["title"]) & _tally_numbers(b["title"])
    return len(shared) >= TALLY_MIN_SHARED


def copy_groups(articles):
    """기사 목록 → 원고군 목록. 각 군은 기사 인덱스 집합."""
    parent = list(range(len(articles)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    kinds = {}
    for i in range(len(articles)):
        for j in range(i + 1, len(articles)):
            if same_copy(articles[i], articles[j]):
                union(i, j)
                kinds[find(i)] = "wire"
            elif same_release(articles[i], articles[j]):
                union(i, j)
                kinds.setdefault(find(i), "release")

    groups = {}
    for i in range(len(articles)):
        groups.setdefault(find(i), []).append(i)
    return [(members, kinds.get(root)) for root, members in groups.items()]


def _representative(articles, members):
    """원고군의 대표 — 등급이 가장 높고, 같으면 먼저 게재된 쪽."""
    return min(
        members,
        key=lambda i: (
            -feedreg.TIER_WEIGHT.get(articles[i]["tier"], 0.0),
            articles[i]["published"],
        ),
    )


def independence_key(article):
    """교차검증에서 '독립된 하나'로 셀 단위.

    독립 매체는 매체별로 세지만, 같은 정부·진영에 속한 매체는 몇 곳이든
    하나로 묶는다. 계열 매체(파룬궁 계열 등)도 하나로 본다.
    """
    if article["bloc"] == "independent":
        return feedreg.affiliate_of(article["source_domain"])
    return article["bloc"]


def best_tier(articles):
    """가중치가 가장 높은 등급."""
    return max(
        (a["tier"] for a in articles),
        key=lambda t: feedreg.TIER_WEIGHT.get(t, 0.0),
        default="T5",
    )


def _evidence(weights):
    """독립 출처들의 등급을 수확체감으로 합산한 증거력(0~1).

    최고 등급 하나만 보면 'T1+T1' 과 'T1+T5' 가 같은 점수가 된다. 교차검증의
    양뿐 아니라 질을 반영해야 "로이터를 무명 사이트가 받아쓴 것"과 "로이터와
    BBC 가 각각 보도한 것"이 구분된다.
    """
    ordered = sorted(weights, reverse=True)[:4]
    coeffs = (1.0, 0.6, 0.35, 0.2)
    total = sum(w * c for w, c in zip(ordered, coeffs))
    return min(1.0, total / sum(coeffs))


def evaluate(articles):
    """기사 묶음 → 신뢰도 판정 dict."""
    groups = copy_groups(articles)

    # 원고군마다 대표 하나만 증언으로 센다
    reps, merged_notes = [], []
    for members, kind in groups:
        rep = _representative(articles, members)
        reps.append(articles[rep])
        if len(members) > 1:
            others = [articles[i]["source_name"] for i in members if i != rep]
            merged_notes.append((kind, articles[rep]["source_name"], others))

    keys = {independence_key(a) for a in reps if a["bloc"] != "unknown"}
    n_independent = len(keys)
    n_unrated = len({a["source_domain"] for a in reps if a["bloc"] == "unknown"})

    blocs = {a["bloc"] for a in articles}
    tier = best_tier(articles)

    primary_cited = any(a["primary_cited"] for a in articles)
    rated_blocs = blocs - {"unknown"}
    state_only = bool(rated_blocs) and "independent" not in rated_blocs

    langs = {a["lang"] for a in articles}
    stamps = [a["published"] for a in articles]
    duration_h = (max(stamps) - min(stamps)).total_seconds() / 3600.0

    # --- 등급 -------------------------------------------------------------
    # 죽은 조건은 뺐다. 'hedged_ratio > 0.5' 는 95건 중 0건, 즉 한 번도 참인
    # 적이 없는 서술을 등급표에 싣고 있었다.
    if n_independent == 0:
        grade, d_reason = "D", "unrated"
    elif n_independent == 1:
        if state_only:
            grade, d_reason = "D", "state_only"
        elif tier in ("T4", "T5"):
            grade, d_reason = "D", "partisan"
        elif tier == "T1":
            grade, d_reason = "B", None
        else:
            grade, d_reason = "C", None
    elif n_independent >= 3 and tier in ("T1", "TA"):
        grade, d_reason = "A", None
    else:
        grade, d_reason = "B", None

    # --- 점수(정렬용) -----------------------------------------------------
    # 죽은 항 두 개(hedged 0/128, adversarial_pair 0/95)를 제거하고,
    # primary_cited 는 20 → 7 로 낮췄다. 실측상 그 항의 히트 7건이 전부
    # 중국어 '기관명：' 인용 구문이라 사실상 언어 보너스였다.
    rated_weights = [
        feedreg.TIER_WEIGHT.get(a["tier"], 0.3)
        for a in reps if a["bloc"] != "unknown"
    ]
    unrated_weights = [
        0.30 * feedreg.TIER_WEIGHT.get(a["tier"], 0.3)
        for a in reps if a["bloc"] == "unknown"
    ]
    score = (
        50 * _evidence(rated_weights + unrated_weights)
        + 24 * min(n_independent, 4) / 4
        + 11 * (1 if len(langs) >= 2 else 0)
        + 7 * (1 if primary_cited else 0)
        + 8 * min(1.0, math.log1p(max(0.0, duration_h)) / math.log1p(72))
    )

    # --- 근거 -------------------------------------------------------------
    reasons = []
    if n_independent == 0:
        reasons.append("등급표에 없는 매체만 보도")
    elif n_independent == 1:
        only = next(iter(keys))
        label = feedreg.BLOC_LABEL_KO.get(only)
        reasons.append(f"{label} 진영 단독 보도" if label else "독립 출처 1곳")
    else:
        reasons.append(f"독립 출처 {n_independent}곳")

    reasons.append(f"최고 등급 {feedreg.TIER_LABEL_KO.get(tier, tier)}")

    if len(langs) >= 2:
        reasons.append(f"{len(langs)}개 언어권에서 확인")
    if "prc_state" in blocs and "tw_state" in blocs:
        reasons.append("중국·대만 양측 모두 보도")
    if primary_cited:
        reasons.append("정부·군 공식 발표 인용")

    for kind, rep_name, others in merged_notes[:3]:
        joined = "·".join(others[:3])
        if kind == "wire":
            reasons.append(f"{rep_name} 원고를 {joined} 가 전재 — 1곳으로 계산")
        else:
            reasons.append(f"{rep_name} 등이 같은 발표 수치를 인용 — 1곳으로 계산")

    if n_unrated:
        reasons.append(f"미분류 매체 {n_unrated}곳 추가 보도(교차검증 미산입)")

    state_names = sorted(b for b in rated_blocs if b != "independent")
    if state_only and state_names:
        names = "·".join(feedreg.BLOC_LABEL_KO.get(b, b) for b in state_names)
        reasons.append(f"{names} 발표만 존재")

    return {
        "grade": grade,
        "d_reason": d_reason,
        "grade_label": (D_LABEL[d_reason] if d_reason else GRADE_LABEL[grade]),
        "n_originals": len(groups),
        "n_unrated": n_unrated,
        "score": round(max(0.0, min(100.0, score)), 1),
        "n_independent": n_independent,
        "n_articles": len(articles),
        "n_domains": len({a["source_domain"] for a in articles if a["source_domain"]}),
        "blocs": sorted(blocs),
        "top_tier": tier,
        "primary_cited": primary_cited,
        "reasons": reasons,
    }


def pick_headline(articles):
    """대표 제목: 등급이 가장 높은 출처의 것.

    관영매체 표현이 대표 제목이 되면 프레이밍이 그대로 딸려온다.
    """
    def rank(article):
        return (
            feedreg.TIER_WEIGHT.get(article["tier"], 0.0),
            1 if article["bloc"] == "independent" else 0,
            -article["published"].timestamp(),
        )

    return max(articles, key=rank)


PERSPECTIVE_PRC = "prc"
PERSPECTIVE_OTHER = "tw_west"


def split_perspectives(articles):
    """중국 관영 대 그 외로 가른다. 같은 사건 서술이 어떻게 갈리는지 보기 위함."""
    buckets = {PERSPECTIVE_PRC: [], PERSPECTIVE_OTHER: []}
    for article in articles:
        key = PERSPECTIVE_PRC if article["bloc"] == "prc_state" else PERSPECTIVE_OTHER
        buckets[key].append(article["id"])
    return buckets


def article_payload(article):
    # 엔티티는 이미 클러스터링에서 뽑고 있었는데 출력에 담지 않아 UI 가
    # 전혀 쓰지 못했다. 담기만 하면 주제 필터·칩 표시가 바로 된다.
    entities = sorted(
        e for e in extract_entities(article["title"]) if not e.startswith("n:")
    )
    return {
        "id": article["id"],
        "title": article["title"],
        "url": article["url"],
        "published": iso(article["published"]),
        "lang": article["lang"],
        "entities": entities,
        "source_name": article["source_name"],
        "source_domain": article["source_domain"],
        "tier": article["tier"],
        "tier_label": feedreg.TIER_LABEL_KO.get(article["tier"], article["tier"]),
        "bloc": article["bloc"],
        "bloc_label": feedreg.BLOC_LABEL_KO.get(article["bloc"], article["bloc"]),
        "bias": article["bias"],
        "hedged": article["hedged"],
    }


def build_event(articles):
    """기사 묶음 → 사건 객체."""
    articles = sorted(articles, key=lambda a: a["published"])
    head = pick_headline(articles)
    credibility = evaluate(articles)
    first, last = articles[0]["published"], articles[-1]["published"]

    # ID 앵커는 '가장 이른 기사' 가 아니라 구성원 기사 ID 의 정렬 최솟값이다.
    # 전자를 쓰면 최고참 기사가 수집창을 벗어나거나 클러스터가 병합될 때마다
    # ID 가 바뀌고, merge_events 가 옛 ID 를 보존하므로 같은 사건이 두 장으로
    # 남는다. 최솟값은 구성원이 늘어도 잘 안 바뀌고 병합 시 결정론적으로 수렴한다.
    anchor = min(a["id"] for a in articles)
    event_id = "evt_" + first.strftime("%Y%m%d") + "_" + sha1(anchor)[:6]

    langs = sorted({a["lang"] for a in articles})
    return {
        "id": event_id,
        "headline": head["title"],
        "headline_source": head["source_name"],
        "headline_url": head["url"],
        "headline_lang": head["lang"],
        "first_seen": iso(first),
        "last_seen": iso(last),
        "langs": langs,
        "cross_language": len(langs) > 1,
        "credibility": credibility,
        "perspectives": split_perspectives(articles),
        "articles": [article_payload(a) for a in articles],
    }


def build_events(groups):
    events = [build_event(g) for g in groups]
    events.sort(key=lambda e: (e["last_seen"], e["credibility"]["score"]), reverse=True)
    return events


def grade_summary(events):
    return dict(Counter(e["credibility"]["grade"] for e in events))
