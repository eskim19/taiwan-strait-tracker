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
_FURNITURE = re.compile(
    r"^\s*(?:【[^】]*】|\[[^\]]*\]|快訊／|快讯／|獨家／|独家／|更新／|影音／)+"
    r"|\s*[|｜]\s*[^|｜]{1,20}$"
    r"|\s*-\s*[A-Za-z0-9.\s]{2,25}$",
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
_WORD_NUM = re.compile("|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)),
                       re.IGNORECASE)
_DIGITS = re.compile(r"\d{1,4}")


def strip_furniture(title):
    """매체 상용구·꼬리표 제거."""
    prev = None
    text = title or ""
    while prev != text:
        prev = text
        text = _FURNITURE.sub("", text).strip()
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
    """제목의 숫자 지문. 숫자어를 아라비아 숫자로 정규화한다."""
    text = strip_furniture(title or "")
    found = {int(m.group(0)) for m in _DIGITS.finditer(text)}
    for match in _WORD_NUM.finditer(text):
        found.add(_NUMBER_WORDS[match.group(0).lower()])
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
