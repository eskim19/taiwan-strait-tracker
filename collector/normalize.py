"""RSS 항목 → 통일 기사 스키마.

Google News 항목은 링크가 불투명 리다이렉트(news.google.com/rss/articles/...)라
원 URL 을 복원할 수 없다. 2023～24년에 base64 디코딩 트릭이 깨졌고 현재 방법은
비공식 엔드포인트를 두드려야 해서 파이프라인에 넣기 부적합하다. 대신 각 항목의
<source url="..."> 태그에서 매체 도메인을 뽑는다 — 신뢰도 등급 판정에 필요한 건
이것뿐이므로 원 URL 복원은 애초에 불필요하다.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from . import feeds as feedreg
from .fetch import entry_datetime
from .util import (
    containment,
    detect_lang,
    normalize_text,
    sha1,
    strip_html,
    title_tokens,
    utcnow,
)

# 헤지 표현 — 확인되지 않은 전언 보도 감지
HEDGE_PATTERNS = re.compile(
    r"reportedly|allegedly|unconfirmed|sources\s+say|according\s+to\s+sources"
    r"|is\s+said\s+to|rumou?r|據悉|据悉|消息人士|傳出|传出|疑似|未經證實|未经证实"
    r"|소식통|알려졌다|전해졌다|미확인|관측통",
    re.IGNORECASE,
)

# 1차 출처(정부·군 공식 발표) 인용 감지
PRIMARY_PATTERNS = re.compile(
    r"ministry\s+of\s+national\s+defen[cs]e|defen[cs]e\s+ministry|pentagon"
    r"|國防部|国防部|國臺辦|国台办|外交部|indo-pacific\s+command"
    r"|국방부|외교부|합참|국무원",
    re.IGNORECASE,
)


def source_from_entry(entry, feed):
    """항목의 매체 도메인·표시명 추출."""
    if feed["kind"] == "native":
        return feed["source_domain"], None

    # Google News: <source url="https://www.reuters.com">Reuters</source>
    src = entry.get("source") or {}
    href = src.get("href") or src.get("url") or ""
    title = src.get("title") or src.get("value") or None
    if href:
        domain = urlparse(href).netloc
        if domain:
            return domain, title

    # 폴백: 링크 자체가 원 매체를 가리키는 경우
    link = entry.get("link") or ""
    domain = urlparse(link).netloc
    if domain and "news.google.com" not in domain:
        return domain, title
    return "", title


_GN_SUFFIX = re.compile(r"\s+-\s+[^-]{2,40}$")


def clean_title(raw, source_title):
    """Google News 제목 끝의 ' - 매체명' 꼬리표 제거."""
    title = strip_html(raw)
    if not title:
        return ""
    if source_title:
        suffix = f" - {source_title}"
        if title.endswith(suffix):
            return title[: -len(suffix)].strip()
    # 매체명을 모를 때는 보수적으로 마지막 하이픈 구획만 제거
    stripped = _GN_SUFFIX.sub("", title)
    return (stripped if len(stripped) >= 15 else title).strip()


MAX_AGE_DAYS = 21


def normalize_entry(entry, feed, now=None, drops=None):
    """RSS 항목 하나 → 기사 dict. 채택 불가면 None.

    drops 를 Counter 로 넘기면 탈락 사유를 집계한다(게이트 튜닝용).
    """
    now = now or utcnow()

    def drop(reason):
        if drops is not None:
            drops[reason] += 1
        return None

    domain, source_title = source_from_entry(entry, feed)
    if feedreg.is_syndicator(domain):
        return drop("syndicator")
    if feedreg.is_noise(domain):
        return drop("noise_domain")

    title = clean_title(entry.get("title", ""), source_title)
    if not title or len(title) < 10:
        return drop("no_title")
    # JS 필수 사이트를 Google News 가 긁어 만든 껍데기 항목
    if "without JavaScript enabled" in title or "Enable JavaScript" in title:
        return drop("js_placeholder")

    summary = strip_html(entry.get("summary", ""))[:400]
    # Google News 의 summary 는 관련기사 링크 목록이라 본문 가치가 없다
    if feed["kind"] == "aggregator":
        summary = ""

    published = entry_datetime(entry)
    if published is None:
        published = now
    age_days = (now - published).days
    if age_days > MAX_AGE_DAYS or age_days < -1:
        return drop("too_old")

    lang = detect_lang(title) if feed["kind"] == "aggregator" else feed["lang"]

    if feed.get("needs_filter"):
        ok, reason = feedreg.passes_gate(title, summary)
        if not ok:
            return drop(reason)

    text = f"{title} {summary}"
    info = feedreg.classify(domain)
    if source_title and info["name"] == info["domain"]:
        info["name"] = source_title

    return {
        "id": sha1(normalize_text(title))[:16],
        "title": title,
        "summary": summary,
        "url": entry.get("link", ""),
        "published": published,
        "lang": lang,
        "feed_id": feed["id"],
        "source_domain": info["domain"],
        "source_name": info["name"],
        "tier": info["tier"],
        "bloc": info["bloc"],
        "bias": info["bias"],
        "hedged": bool(HEDGE_PATTERNS.search(text)),
        "primary_cited": bool(PRIMARY_PATTERNS.search(text)),
    }


REVISION_CONTAINMENT = 0.85
REVISION_WINDOW_HOURS = 36


def dedupe_revisions(articles):
    """같은 매체가 제목만 고쳐 다시 낸 기사를 하나로 합친다.

    매체는 속보를 낸 뒤 제목을 다듬어 재발행하는 일이 잦다("…發射火箭 將經過…"
    → "…發射火箭將經過…| 政治"). 그대로 두면 같은 기사가 두 장의 카드로 보이고,
    교차검증에서도 한 매체가 두 번 계산될 수 있다.

    같은 도메인·같은 언어이고 시간이 가까우며 토큰이 거의 포함관계면 같은
    기사로 보고, 정보가 더 많은(긴) 제목 쪽을 남긴다.
    """
    kept = []
    for article in sorted(articles, key=lambda a: a["published"]):
        merged = False
        for i, other in enumerate(kept):
            if other["source_domain"] != article["source_domain"]:
                continue
            if other["lang"] != article["lang"]:
                continue
            gap = abs((article["published"] - other["published"]).total_seconds()) / 3600.0
            if gap > REVISION_WINDOW_HOURS:
                continue
            ta = title_tokens(article["title"], article["lang"])
            tb = title_tokens(other["title"], other["lang"])
            if min(len(ta), len(tb)) < 3:
                continue
            if containment(ta, tb) < REVISION_CONTAINMENT:
                continue
            if len(article["title"]) > len(other["title"]):
                article["published"] = other["published"]  # 최초 게재 시각 유지
                kept[i] = article
            merged = True
            break
        if not merged:
            kept.append(article)
    return kept


def normalize_all(results, now=None, drops=None):
    """(feed, parsed) 목록 → 중복 제거된 기사 목록."""
    now = now or utcnow()
    by_id = {}
    for feed, parsed in results:
        for entry in parsed.entries:
            article = normalize_entry(entry, feed, now=now, drops=drops)
            if not article:
                continue
            prev = by_id.get(article["id"])
            if prev is None:
                by_id[article["id"]] = article
                continue
            # 같은 제목이 여러 피드에서 잡히면 등급 높은 쪽을 남긴다
            if _rank(article) > _rank(prev):
                by_id[article["id"]] = article

    articles = dedupe_revisions(list(by_id.values()))
    if drops is not None:
        drops["revision"] = len(by_id) - len(articles)
    return sorted(articles, key=lambda a: a["published"], reverse=True)


def _rank(article):
    weight = feedreg.TIER_WEIGHT.get(article["tier"], 0.3)
    # 미분류(도메인 미확보) 는 후순위
    return (1 if article["source_domain"] else 0, weight)
