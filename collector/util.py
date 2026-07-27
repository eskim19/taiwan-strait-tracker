"""공용 유틸."""

from __future__ import annotations

import hashlib
import re
import sys
import unicodedata
from datetime import datetime, timezone


def enable_utf8_stdout():
    """Windows 콘솔 기본 cp949 에서 한자·한글 출력이 깨지는 것 방지."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


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
