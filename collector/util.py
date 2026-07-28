"""공용 유틸."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import unicodedata
from datetime import datetime, timezone


def enable_utf8_stdout():
    """Windows 콘솔 기본 cp949 에서 한자·한글 출력이 깨지는 것 방지."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def write_json(path, payload, indent=1):
    """원자적 JSON 쓰기.

    같은 디렉터리에 임시 파일로 쓴 뒤 os.replace 로 갈아끼운다. 직접 쓰면
    도중에 죽었을 때 파일이 반쯤 쓰인 상태로 남고, 읽는 쪽이 예외를 삼켜
    조용히 빈 값으로 복구한다. tension.json 은 수년치 누적 자산이라
    그렇게 날아가면 되돌릴 방법이 없다.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=str(path.parent),
        prefix=path.name + ".", suffix=".tmp", delete=False,
    )
    try:
        with handle as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=indent)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(handle.name, path)
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def utcnow():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s　-鿿가-힯]", re.UNICODE)


def normalize_text(text):
    """비교용 정규화: NFKC, 소문자, 구두점 제거, 공백 축약."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip()


def sha1(*parts):
    h = hashlib.sha1()
    for part in parts:
        h.update(str(part).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


_TAG = re.compile(r"<[^>]+>")


def strip_html(text):
    if not text:
        return ""
    text = _TAG.sub(" ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    return _WS.sub(" ", text).strip()


# ---------------------------------------------------------------------------
# 제목 비교용 토큰화 — 와이어 전재(같은 원고 재게재) 탐지에 쓴다
# ---------------------------------------------------------------------------

# 매체가 제목 앞뒤에 붙이는 상용구. 남겨두면 같은 원고인데도 토큰이 갈린다.
#
# 이 규칙은 한 번 잘못 만들어 크게 데였다. 이전 판은 `\s*-\s*[A-Za-z0-9.\s]{2,25}$`
# 였는데, 하이픈 앞뒤 공백을 요구하지 않아 하이픈 단어를 통째로 먹었다:
#   "…hits three-year low"        → "…hits three"
#   "…new gray-zone tactics near" → "…new gray"   (43% 소실)
# 게다가 문자 클래스에 숫자가 있어 "- 17 sorties" 같은 꼬리가 지워지면서
# same_copy 의 숫자 충돌 방어까지 무력화됐다.
#
# 지금은 (1) 대시 앞뒤에 공백을 요구하고 (2) 꼬리에 숫자를 허용하지 않으며
# (3) 아래 strip_furniture 가 고정점 반복 대신 한 번만 적용한다.
_FURNITURE_PREFIX = re.compile(
    r"^\s*(?:【[^】]*】|\[[^\]]*\]|快訊／|快讯／|獨家／|独家／|更新／|影音／)+"
)
_FURNITURE_SUFFIX = re.compile(
    r"\s*[|｜]\s*[^|｜]{1,20}$"          # "| 政治焦點"
    r"|\s+[-–—]\s+[A-Za-z.\s]{2,25}$"   # " - SCMP" (숫자 불허, 양쪽 공백 필수)
)

_EN_STOP = {
    "a", "an", "the", "of", "in", "on", "at", "to", "for", "with", "as", "by",
    "from", "and", "or", "but", "is", "are", "was", "were", "be", "been",
    "its", "it", "this", "that", "these", "those", "over", "after", "amid",
    "into", "near", "new", "says", "said", "say",
}

# 숫자어 → 아라비아 숫자. 로이터 "two days" 와 전재본 "2 days" 를 같은 지문으로
# 만들기 위해 필요하다.
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "一": 1, "兩": 2, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
    "七": 7, "八": 8, "九": 9, "十": 10,
}
# 라틴 숫자어는 반드시 단어 경계를 요구한다. 경계가 없으면 이 코퍼스에서
# 가장 흔한 두 단어가 숫자를 만들어낸다 — "tension" → ten → 10,
# "drone" → one → 1. 실측으로 스냅샷 128건 중 25건(20%)이 환각 숫자를 가졌고,
# 그 결과 로이터·BBC·AP 가 "같은 발표 수치를 인용한 1곳"으로 계산됐다.
_LATIN_NUM_WORDS = {k: v for k, v in _NUMBER_WORDS.items() if k.isascii()}
_WORD_NUM = re.compile(
    r"(?<![A-Za-z])(?:"
    + "|".join(sorted(_LATIN_NUM_WORDS, key=len, reverse=True))
    + r")(?![A-Za-z])",
    re.IGNORECASE,
)
# CJK 숫자(五·十 …)는 형태소로 너무 흔해(五角大廈=펜타곤, 九二共識=92공식)
# 지문으로 쓸 수 없다. 兩/两 만 "連兩天"(이틀 연속) 관용구 때문에 남긴다.
_CJK_NUM_WORDS = {"兩": 2, "两": 2}
_DIGITS = re.compile(r"\d{1,4}")


def strip_furniture(title):
    """매체 상용구·꼬리표 제거.

    두 가지를 지킨다.

    1. 고정점까지 반복하지 않는다. 반복하면 "A｜B｜C" 가 "A" 로 무너진다.
    2. **떼어낸 것이 남는 것보다 길면 떼지 않는다.** 꼬리표는 본문보다 짧다는
       것이 유일하게 믿을 만한 신호다. 대만·홍콩 매체는 ｜를 꼬리표로도
       쓰지만("…菲律賓| 軍事") 칼럼명 접두로도 쓴다("台海有戰事｜兩岸…").
       길이 조건이 없으면 후자에서 제목 본문이 통째로 날아가고, 같은 칼럼의
       서로 다른 기사 두 개가 동일한 토큰 집합이 되어 전재로 오인된다.
    """
    text = (title or "").strip()
    text = _FURNITURE_PREFIX.sub("", text).strip()

    stripped = _FURNITURE_SUFFIX.sub("", text).strip()
    if stripped and len(stripped) > len(text) - len(stripped):
        text = stripped
    return text


def title_tokens(title, lang):
    """제목 → 비교용 토큰 집합.

    영어는 단어(불용어 제거), CJK 는 띄어쓰기가 없거나 무의미하므로 문자
    2-gram 을 쓴다.
    """
    text = normalize_text(strip_furniture(title))
    if not text:
        return set()
    if lang == "en":
        return {t for t in text.split() if len(t) > 1 and t not in _EN_STOP}
    compact = text.replace(" ", "")
    return {compact[i:i + 2] for i in range(len(compact) - 1)}


def title_numbers(title):
    """제목의 숫자 지문. 숫자어를 아라비아 숫자로 정규화한다.

    상용구를 떼기 **전** 원문에서 뽑는다. 꼬리표 제거가 숫자를 지우면
    "숫자가 충돌하니 다른 회차다"라는 방어가 조용히 꺼진다.
    """
    text = title or ""
    found = {int(m.group(0)) for m in _DIGITS.finditer(text)}
    for match in _WORD_NUM.finditer(text):
        found.add(_LATIN_NUM_WORDS[match.group(0).lower()])
    for word, value in _CJK_NUM_WORDS.items():
        if word in text:
            found.add(value)
    # 연도는 변별력이 없다
    return {n for n in found if not (1900 <= n <= 2100)}


def containment(a, b):
    """작은 쪽이 큰 쪽에 얼마나 들어앉는가.

    Jaccard 가 아니라 containment 를 쓰는 이유: 전재는 원 헤드라인에 매체
    꼬리표를 붙이거나 앞머리를 잘라내므로 길이가 달라진다. Jaccard 는 그
    길이 차이를 벌점으로 먹어 전재와 독립 취재를 구분하지 못한다.
    """
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


# 언어 판정: 유니코드 블록 비율. 외부 라이브러리 불필요.
_HANGUL = re.compile(r"[가-힯ᄀ-ᇿ]")
_KANA = re.compile(r"[぀-ヿ]")
_HAN = re.compile(r"[一-鿿]")
_LATIN = re.compile(r"[a-zA-Z]")


def detect_lang(text):
    """en / ko / zh / ja 판정. 짧은 제목에도 안정적으로 동작."""
    if not text:
        return "en"
    hangul = len(_HANGUL.findall(text))
    kana = len(_KANA.findall(text))
    han = len(_HAN.findall(text))
    latin = len(_LATIN.findall(text))
    total = hangul + kana + han + latin
    if not total:
        return "en"
    # 한글이 조금이라도 섞이면 한국어(한자 병기 관행 때문)
    if hangul / total > 0.10:
        return "ko"
    # 가나가 있으면 일본어(한자만으로는 중국어와 구분 불가)
    if kana / total > 0.05:
        return "ja"
    if han / total > 0.20:
        return "zh"
    return "en"
