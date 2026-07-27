"""신뢰도 등급 산출 + 사건 객체 조립.

이 트래커의 핵심 판단이 여기 있다. 규칙은 전부 명시적이고, 산출된 등급에는
항상 근거 문자열이 따라붙는다. 점수만 보여주면 없는 정밀도를 오해한다.

가장 중요한 설계 결정은 '독립성'을 도메인이 아니라 진영으로 재는 것이다.
환구시보·신화·CGTN 이 같은 사건을 동시에 보도해도 그것은 독립된 세 증언이
아니라 한 정부의 한 발표다. 도메인 수로만 세면 관영매체 일제 보도가 최고
신뢰도를 받는 사고가 난다.
"""

from __future__ import annotations

from collections import Counter

from . import feeds as feedreg
from .util import iso, sha1

GRADE_LABEL = {
    "A": "검증됨",
    "B": "개연적",
    "C": "단일 출처",
    "D": "주의",
}

GRADE_DESC = {
    "A": "독립된 진영 3곳 이상이 보도했고 통신사·공영방송 또는 분석기관이 포함됨",
    "B": "독립된 진영 2곳이 보도했거나, 통신사·공영방송이 단독 보도함",
    "C": "출처가 한 곳뿐이라 교차 확인되지 않음",
    "D": "한쪽 정부 발표만 있거나, 성향·미분류 매체 단독이거나, 전언 표현이 지배적임",
}


def independence_key(article):
    """교차검증에서 '독립된 하나'로 셀 단위.

    독립 매체는 매체별로 세지만, 같은 정부·진영에 속한 매체는 몇 곳이든
    하나로 묶는다.
    """
    if article["bloc"] == "independent":
        return article["source_domain"] or "unknown"
    return article["bloc"]


def best_tier(articles):
    """가중치가 가장 높은 등급."""
    return max(
        (a["tier"] for a in articles),
        key=lambda t: feedreg.TIER_WEIGHT.get(t, 0.0),
        default="T5",
    )


def evaluate(articles):
    """기사 묶음 → 신뢰도 판정 dict."""
    keys = {independence_key(a) for a in articles}
    n_independent = len(keys)
    blocs = {a["bloc"] for a in articles}
    tier = best_tier(articles)
    tier_weight = feedreg.TIER_WEIGHT.get(tier, 0.3)

    hedged_ratio = sum(1 for a in articles if a["hedged"]) / len(articles)
    primary_cited = any(a["primary_cited"] for a in articles)
    state_only = "independent" not in blocs
    adversarial_pair = "prc_state" in blocs and "tw_state" in blocs

    # --- 등급 -------------------------------------------------------------
    if n_independent == 1:
        if state_only or tier in ("T4", "T5") or hedged_ratio > 0.5:
            grade = "D"
        elif tier == "T1":
            grade = "B"
        else:
            grade = "C"
    elif n_independent >= 3 and tier in ("T1", "TA"):
        grade = "A"
    else:
        grade = "B"

    # --- 점수(정렬용) -----------------------------------------------------
    score = (
        45 * tier_weight
        + 35 * min(n_independent, 4) / 4
        + 20 * (1 if primary_cited else 0)
        - 10 * hedged_ratio
    )
    if adversarial_pair:
        score += 5  # 대립하는 두 정부가 함께 인정한 사실

    # --- 근거 -------------------------------------------------------------
    reasons = []
    if n_independent == 1:
        only = next(iter(keys))
        label = feedreg.BLOC_LABEL_KO.get(only)
        reasons.append(f"{label} 진영 단독 보도" if label else "단일 출처")
    else:
        reasons.append(f"독립 출처 {n_independent}곳")

    tier_label = feedreg.TIER_LABEL_KO.get(tier, tier)
    reasons.append(f"최고 등급 {tier_label}")

    if adversarial_pair:
        reasons.append("중국·대만 양측 모두 보도")
    if primary_cited:
        reasons.append("정부·군 공식 발표 인용")
    if hedged_ratio > 0:
        reasons.append(f"전언·미확인 표현 {round(hedged_ratio * 100)}%")

    state_blocs = sorted(b for b in blocs if b != "independent")
    if state_only and state_blocs:
        names = "·".join(feedreg.BLOC_LABEL_KO.get(b, b) for b in state_blocs)
        reasons.append(f"{names} 발표만 존재")

    return {
        "grade": grade,
        "grade_label": GRADE_LABEL[grade],
        "score": round(max(0.0, min(100.0, score)), 1),
        "n_independent": n_independent,
        "n_articles": len(articles),
        "n_domains": len({a["source_domain"] for a in articles if a["source_domain"]}),
        "blocs": sorted(blocs),
        "top_tier": tier,
        "primary_cited": primary_cited,
        "hedged_ratio": round(hedged_ratio, 2),
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
    return {
        "id": article["id"],
        "title": article["title"],
        "url": article["url"],
        "published": iso(article["published"]),
        "lang": article["lang"],
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

    # 가장 이른 기사를 앵커로 삼아 실행마다 같은 ID 가 나오게 한다
    event_id = "evt_" + first.strftime("%Y%m%d") + "_" + sha1(articles[0]["id"])[:6]

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
