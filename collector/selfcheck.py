"""산출 데이터의 사실성 검사.

`metrics.py` 는 클러스터링 **품질**을 잰다. 이 모듈은 다른 질문을 한다:
**나온 데이터가 사실인가?**

이 구분이 중요한 이유가 있다. 직전 회차에 지표는 전부 좋아졌는데(파편화 26→1,
BCubed 0.697→0.905) 그 와중에 국방부 시계열의 41%가 사라졌고 아무도 몰랐다.
"지표가 올랐다"와 "데이터가 옳다"는 다른 명제이고, 나는 앞의 것만 확인했다.

아래 검사는 전부 **그때 있었으면 잡혔을** 것들이다. 새 결함을 발견할 때마다
"어떤 검사가 이걸 잡았을까"를 묻고 여기에 추가한다.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from .util import enable_utf8_stdout

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"

# 국방부는 거의 매일 발표한다. 결측이 이보다 많으면 수집이 새고 있다.
MIN_TENSION_COVERAGE = 0.90
# 격일 건너뛰기 버그의 지문. 2일 간격이 전체의 이 비율을 넘으면 의심한다.
MAX_TWO_DAY_GAP_RATIO = 0.10


def _load(name, default):
    path = DATA / name
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def check_tension_continuity():
    """국방부 시계열이 연속인가.

    이 검사가 없어서 커버리지 58.8%(2일 간격 345건)짜리 시리즈가 배포됐다.
    차트는 결측일을 건너뛴 채 막대를 등간격으로 그려 구멍을 숨긴다.
    """
    records = _load("tension.json", {}).get("records", [])
    if len(records) < 30:
        return [f"국방부 레코드가 {len(records)}건뿐 — 수집 실패 의심"]

    days = [date.fromisoformat(r["date"]) for r in records]
    span = (days[-1] - days[0]).days + 1
    coverage = len(records) / span
    gaps = Counter((days[i + 1] - days[i]).days for i in range(len(days) - 1))
    two_day_ratio = gaps.get(2, 0) / max(1, len(days) - 1)

    problems = []
    if coverage < MIN_TENSION_COVERAGE:
        problems.append(
            f"국방부 커버리지 {coverage:.1%} < {MIN_TENSION_COVERAGE:.0%}"
            f" ({len(records)}건 / {span}일)"
        )
    if two_day_ratio > MAX_TWO_DAY_GAP_RATIO:
        problems.append(
            f"2일 간격이 {gaps.get(2, 0)}건({two_day_ratio:.1%}) — 목록 파싱이"
            " 한 칸 밀려 격일로 건너뛰고 있을 수 있다"
        )
    return problems


def check_no_shared_articles():
    """한 기사가 두 사건 카드에 동시에 있으면 안 된다.

    사건 병합 규칙이 옛 상위집합을 못 버려서 실제로 기사 5건이 두 카드에
    노출된 채 배포됐고, 아카이브에는 영구히 남았다.
    """
    problems = []
    for name in ["events.json"] + [
        f"archive/{p.name}" for p in sorted((DATA / "archive").glob("*.json"))
    ]:
        events = _load(name, {}).get("events", [])
        owner = {}
        clashes = []
        for event in events:
            for article in event.get("articles", []):
                prev = owner.get(article["id"])
                if prev and prev != event["id"]:
                    clashes.append(article["id"])
                owner[article["id"]] = event["id"]
        if clashes:
            problems.append(f"{name}: 기사 {len(clashes)}건이 두 카드에 중복 노출")
    return problems


def check_no_fabricated_numbers():
    """제목에 숫자가 없는데 숫자 지문이 잡히면 안 된다.

    'tension' 에서 ten→10, 'drone' 에서 one→1 을 뽑는 바람에 서로 다른
    통신사가 "같은 발표 수치를 인용한 1곳"으로 계산됐다.
    """
    from .util import title_numbers

    probes = [
        ("Taiwan Strait tension rises", set()),
        ("Taiwan detects heightened Chinese activity", set()),
        ("China drone flies near Taiwan", set()),
        ("China begins two days of live-fire drills", {2}),
        ("Taiwan tracks 11 Chinese ships, 4 military aircraft", {4, 11}),
    ]
    problems = []
    for title, expected in probes:
        got = title_numbers(title)
        if got != expected:
            problems.append(f"숫자 지문 오류: {title!r} → {sorted(got)} (기대 {sorted(expected)})")
    return problems


def check_title_integrity():
    """비교용 정규화가 제목을 잘라먹지 않는가.

    꼬리표 제거 규칙이 하이픈 단어를 먹어 "…hits three-year low" 가
    "…hits three" 가 됐고, 서로 다른 칼럼이 같은 토큰 집합이 되어 전재로
    오인됐다.
    """
    from .util import strip_furniture

    keep = [
        "China's military activity around Taiwan hits three-year low",
        "Defense analyst warns China testing new gray-zone tactics near Taiwan",
        "US-China talks resume",
        "台海有戰事｜兩岸「和統」須有三大前提",
    ]
    problems = [
        f"제목 절단: {t!r} → {strip_furniture(t)!r}"
        for t in keep if strip_furniture(t) != t
    ]
    return problems


def check_gate_recall():
    """주제 게이트가 명백히 관련된 기사를 버리지 않는가.

    `擾台`·`攻台` 가 대만 언급 관문에서 먼저 탈락해 한광훈련 보도가 통째로
    수집되지 않았다.
    """
    from .feeds import passes_gate

    must_pass = [
        "漢光演習8/5登場！10天9夜模擬共軍攻台 2旅動員逾5000名後備兵力",
        "實彈射擊後…共軍再發動「聯合戰備警巡」 19共機出海擾台",
        "中共機艦臺海周邊活動 國軍嚴密監控應處",
        "航行警告！台湾海峡部分海域进行实弹射击 禁止进入",
    ]
    must_drop = [
        "Taiex suffers third steepest point drop amid AI spending concerns",
        "台湾新北市发生4.8级地震，震源深度95千米",
    ]
    problems = []
    for title in must_pass:
        ok, why = passes_gate(title, "")
        if not ok:
            problems.append(f"게이트가 관련 기사를 버림({why}): {title[:50]}")
    for title in must_drop:
        ok, _ = passes_gate(title, "")
        if ok:
            problems.append(f"게이트가 무관 기사를 통과시킴: {title[:50]}")
    return problems


CHECKS = [
    ("국방부 시계열 연속성", check_tension_continuity),
    ("기사 중복 노출", check_no_shared_articles),
    ("숫자 지문 환각", check_no_fabricated_numbers),
    ("제목 절단", check_title_integrity),
    ("주제 게이트 리콜", check_gate_recall),
]


def main():
    failures = 0
    for label, check in CHECKS:
        problems = check()
        if problems:
            failures += len(problems)
            print(f"  ✗ {label}")
            for p in problems:
                print(f"      {p}")
        else:
            print(f"  ✓ {label}")
    print()
    if failures:
        print(f"사실성 검사 실패 {failures}건")
        return 1
    print("사실성 검사 통과")
    return 0


if __name__ == "__main__":
    enable_utf8_stdout()
    sys.exit(main())
