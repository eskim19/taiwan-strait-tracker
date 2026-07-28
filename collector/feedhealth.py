"""build_meta.json 을 읽어 피드 건전성을 보고한다.

품질(metrics)도 사실성(selfcheck)도 아닌 세 번째 축이다 — **수집 경로가
살아 있는가.** 이게 필요한 이유는 배포 전에 확인할 방법이 없는 실패가
하나 있기 때문이다.

T1 통신사가 전부 구글 뉴스 6개 피드를 통과한다(로이터·AP·CNN·교도는 자체
RSS 가 없다). 구글 뉴스는 GitHub 러너의 Azure 데이터센터 IP 에서 429 를
주거나, 더 나쁘게는 동의 인터스티셜 HTML 을 HTTP 200 으로 준다. 한국
가정용 IP 에서는 이게 보이지 않는다. 그리고 build.py 는 '전 피드 실패'가
아니면 종료코드 0 이라, T1 만 죽으면 등급이 조용히 C/D 로 내려앉는다.

출력이 3층인 이유는 층마다 도달 범위와 비용이 다르기 때문이다.
  1. 스텝 요약  — 항상. 런 페이지를 열면 표가 보인다. 알림은 없다.
  2. 애노테이션 — 실패 피드마다 ::warning::. 런 페이지 최상단. 알림은 없다.
  3. 종료코드   — 1이면 잡이 빨개지고 GitHub 이 메일을 보낸다. 유일한 '푸시'
     신호라 아껴 쓴다. 구글 뉴스는 간헐 429 가 정상인데 매번 빨간불을 켜면
     일주일 만에 아무도 안 본다.

워크플로 인라인 heredoc 이 아니라 모듈로 만든 이유: 이 판정은 배포 후에만
검증할 수 있으므로, 최소한 같은 코드를 로컬에서 돌려 눈으로 볼 수 있어야
한다. 인라인이면 그게 막힌다.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .util import enable_utf8_stdout

ROOT = Path(__file__).resolve().parent.parent
META_PATH = ROOT / "docs" / "data" / "build_meta.json"

# health 값 → (사람이 읽는 말, 심각한가)
HEALTH_LABEL = {
    "ok": ("정상", False),
    "error": ("실패", True),
    "empty": ("빈 응답", True),
    "stale": ("정체", True),
    "no_adopt": ("채택 0", True),
}


def describe(feed):
    """피드 한 줄의 진단 문구. 무엇이 잘못됐는지 사람 말로."""
    health = feed.get("health", "ok")
    if health == "error":
        return feed.get("error") or "원인 미상"
    if health == "no_adopt":
        return f"{feed.get('n_entries', 0)}개 항목 · 채택 0 — 관련도 정렬/차단 의심"
    if health == "stale":
        return f"최신 항목 {str(feed.get('newest') or '?')[:10]} — 며칠째 그대로"
    if health == "empty":
        return "항목 0개"
    if feed.get("status") == "not_modified":
        # 304 는 항목 수가 0으로 잡힌다. "0개 항목"으로만 쓰면 장애처럼 읽힌다.
        return "변경 없음 (304)"
    return f"{feed.get('n_entries', 0)}개 항목 · 채택 {feed.get('n_adopted', 0)}"


def report(meta):
    """(마크다운, 경고목록, 종료코드)."""
    feeds = meta.get("feeds", [])
    critical = [f for f in feeds if f.get("critical")]
    down = [f for f in feeds if HEALTH_LABEL.get(f.get("health", "ok"), ("", False))[1]]
    critical_down = [f for f in critical if f in down]

    lines = ["## 피드 건전성", "", "| 피드 | 중대 | 상태 | 항목 | 채택 | 진단 |", "|---|---|---|---|---|---|"]
    for f in feeds:
        label, bad = HEALTH_LABEL.get(f.get("health", "ok"), (f.get("health", "?"), True))
        lines.append(
            f"| {f.get('name', f.get('id', '?'))} "
            f"| {'●' if f.get('critical') else ''} "
            f"| {'⚠️ ' if bad else ''}{label} "
            f"| {f.get('n_entries', 0)} | {f.get('n_adopted', 0)} "
            f"| {describe(f)} |"
        )

    tiers = meta.get("tier_articles", {})
    t1 = meta.get("t1_domains", [])
    lines += [
        "",
        f"기사 등급 분포 `{tiers or '(없음)'}`",
        "",
        f"T1 도메인 {len(t1)}개 — {', '.join(t1) if t1 else '**없음**'}",
        "",
        f"사건 {meta.get('n_events', 0)}건 / 기사 {meta.get('n_articles', 0)}건"
        f" · 중대 피드 {len(critical) - len(critical_down)}/{len(critical)} 정상",
    ]

    warnings = [
        f"{f.get('name', f.get('id'))}: {describe(f)}"
        for f in down
    ]

    # 종료코드 1 은 아껴 쓴다 — 여기 걸리는 건 '수집이 사실상 멈춘' 경우뿐이다.
    fatal = []
    if meta.get("all_feeds_failed"):
        fatal.append("전 피드 수집 실패")
    if critical and len(critical_down) == len(critical):
        fatal.append(f"중대 피드 {len(critical)}개 전멸 — T1 통신사 경로가 통째로 막혔다")
    if not meta.get("n_articles"):
        fatal.append("채택 기사 0건")
    if fatal:
        lines += ["", "> 🚨 " + " / ".join(fatal)]

    return "\n".join(lines), warnings, fatal


def main(argv=None):
    enable_utf8_stdout()
    if not META_PATH.exists():
        print(f"build_meta.json 없음 — {META_PATH}")
        return 1
    meta = json.loads(META_PATH.read_text(encoding="utf-8"))
    body, warnings, fatal = report(meta)

    print(body)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        # tee 를 안 쓴다. 파이프를 태우면 종료코드가 tee 의 것이 되는 함정을
        # 이 저장소에서 이미 한 번 밟았다(collect.yml 회귀 게이트).
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(body + "\n")

    if os.environ.get("GITHUB_ACTIONS"):
        for w in warnings:
            print(f"::warning title=피드 장애::{w}")
        for f in fatal:
            print(f"::error title=수집 중단 수준::{f}")

    if fatal:
        print(f"\n피드 건전성 실패 — {' / '.join(fatal)}")
        return 1
    if warnings:
        print(f"\n피드 장애 {len(warnings)}건 (경고, 잡은 통과)")
    else:
        print("\n피드 건전성 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
