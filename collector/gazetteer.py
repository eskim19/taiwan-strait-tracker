"""다국어 별칭 사전.

교차언어 클러스터링의 핵심 자산. 한국어 기사와 중국어 기사는 어휘가 하나도
겹치지 않아 TF-IDF 코사인으로는 절대 묶이지 않는다. 대신 두 기사가 같은
'엔티티'를 말하고 있는지로 판정하는데, 그 엔티티를 언어 중립 ID 로 환원하는 게
이 표의 역할이다.

운영하면서 계속 추가할 것. 새 함정·새 훈련명·새 인물이 나올 때마다 여기에
한 줄 넣으면 그날부터 교차언어 병합이 된다.
"""

from __future__ import annotations

import re

# 엔티티 ID -> 별칭 목록. 라틴 문자 별칭은 단어 경계로, CJK 별칭은 부분 문자열로
# 매칭한다(중국어·일본어는 띄어쓰기가 없어 경계 개념이 없다).
ENTITIES = {
    # --- 군 조직 -----------------------------------------------------------
    "pla": ["PLA", "People's Liberation Army", "Peoples Liberation Army",
            "解放軍", "解放军", "共軍", "共军", "中國軍", "中国军", "中国軍",
            "인민해방군", "중국군", "중국 인민해방군"],
    "plan_navy": ["PLAN", "PLA Navy", "Chinese navy", "海軍", "海军",
                  "중국 해군", "중국해군"],
    "plaaf": ["PLAAF", "PLA Air Force", "空軍", "空军", "중국 공군"],
    "eastern_theater": ["Eastern Theater Command", "東部戰區", "东部战区",
                        "동부전구", "동부 전구"],
    "roc_military": ["ROC Armed Forces", "Taiwan's military", "Taiwanese military",
                     "國軍", "国军", "台軍", "台军", "대만군", "대만 군"],
    "us_military": ["US military", "U.S. military", "American military",
                    "US Navy", "U.S. Navy", "7th Fleet", "Seventh Fleet",
                    "INDOPACOM", "Indo-Pacific Command",
                    "美軍", "美军", "第七艦隊", "第七舰队",
                    "미군", "미 해군", "제7함대", "인도태평양사령부"],
    "jsdf": ["Self-Defense Force", "JSDF", "Japanese military",
             "自衛隊", "自卫队", "자위대", "일본 자위대"],
    "coast_guard": ["coast guard", "coastguard", "海警", "海巡", "해경", "해양경찰"],
    # --- 정부 기관 ---------------------------------------------------------
    "tw_mnd": ["Ministry of National Defense", "Taiwan's defense ministry",
               "國防部", "国防部", "대만 국방부"],
    "prc_mnd": ["Chinese Defense Ministry", "China's defense ministry",
                "中國國防部", "中国国防部", "중국 국방부"],
    "mac": ["Mainland Affairs Council", "陸委會", "陆委会", "대륙위원회"],
    "tao": ["Taiwan Affairs Office", "國台辦", "国台办", "國臺辦",
            "대만사무판공실", "국무원 대만판공실"],
    "ait": ["American Institute in Taiwan", "AIT", "미국재대만협회"],
    "pentagon": ["Pentagon", "五角大廈", "五角大厦", "펜타곤", "미 국방부"],
    "ipac": ["IPAC", "Inter-Parliamentary Alliance on China", "對中政策跨國議會聯盟"],
    # --- 인물 --------------------------------------------------------------
    "lai_chingte": ["Lai Ching-te", "William Lai", "President Lai",
                    "賴清德", "라이칭더", "라이 칭더", "뢰청덕"],
    "xi_jinping": ["Xi Jinping", "President Xi", "習近平", "习近平",
                   "시진핑", "시 주석"],
    "trump": ["Trump", "特朗普", "川普", "트럼프"],
    "hsiao_bikhim": ["Hsiao Bi-khim", "蕭美琴", "萧美琴", "샤오메이친"],
    "wang_yi": ["Wang Yi", "王毅", "왕이"],
    "wellington_koo": ["Wellington Koo", "顧立雄", "顾立雄", "구리슝"],
    "cho_jungtai": ["Cho Jung-tai", "卓榮泰", "卓荣泰", "줘룽타이"],
    "han_kuoyu": ["Han Kuo-yu", "韓國瑜", "韩国瑜", "한궈위"],
    "chu_lilun": ["Eric Chu", "朱立倫", "朱立伦", "주리룬"],
    "ko_wenje": ["Ko Wen-je", "柯文哲", "커원저"],
    # --- 지리 --------------------------------------------------------------
    "taiwan_strait": ["Taiwan Strait", "Taiwan Straits", "Strait of Taiwan",
                      "cross-strait",
                      "台海", "臺海", "台灣海峽", "台湾海峡", "臺灣海峽",
                      "兩岸", "两岸",
                      "대만해협", "타이완해협", "대만 해협", "양안"],
    "median_line": ["median line", "中線", "中线", "海峽中線", "海峡中线",
                    "중간선", "해협 중간선"],
    "adiz": ["ADIZ", "air defense identification zone",
             "air defence identification zone",
             "防空識別區", "防空识别区", "防空識別圏",
             "방공식별구역", "방공 식별 구역"],
    "kinmen": ["Kinmen", "Quemoy", "金門", "金门", "진먼", "금문"],
    "matsu": ["Matsu", "馬祖", "马祖", "마쭈"],
    "penghu": ["Penghu", "Pescadores", "澎湖", "펑후"],
    "pratas": ["Pratas", "東沙", "东沙", "둥사"],
    "itu_aba": ["Itu Aba", "Taiping Island", "太平島", "太平岛", "타이핑다오"],
    "bashi_channel": ["Bashi Channel", "巴士海峽", "巴士海峡", "바시해협"],
    "miyako_strait": ["Miyako Strait", "宮古海峽", "宫古海峡", "미야코해협"],
    "hualien": ["Hualien", "花蓮", "花莲", "화롄"],
    "suao": ["Suao", "Su-ao", "蘇澳", "苏澳", "쑤아오"],
    "keelung": ["Keelung", "基隆", "지룽"],
    "kaohsiung": ["Kaohsiung", "高雄", "가오슝"],
    "taipei": ["Taipei", "台北", "臺北", "타이베이", "타이페이"],
    "beijing": ["Beijing", "北京", "베이징"],
    "south_china_sea": ["South China Sea", "南海", "남중국해"],
    "east_china_sea": ["East China Sea", "東海", "东海", "동중국해"],
    "senkaku": ["Senkaku", "Diaoyu", "尖閣", "釣魚島", "钓鱼岛", "센카쿠", "댜오위다오"],
    "yonaguni": ["Yonaguni", "與那國", "与那国", "요나구니"],
    # --- 함정·기체 ---------------------------------------------------------
    # 맨 라틴 별칭은 뺀다 — Fujian·Shandong·Liaoning 은 성(省) 이름이기도 해서
    # "as Fujian issues maritime alert" 가 항모 福建艦으로 오탐된다.
    "shandong": ["山東艦", "山东舰", "산둥함", "산둥호"],
    "liaoning": ["遼寧艦", "辽宁舰", "랴오닝함", "랴오닝호"],
    "fujian": ["福建艦", "福建舰", "푸젠함", "푸젠호"],
    "aircraft_carrier": ["aircraft carrier", "carrier group", "carrier strike",
                         "航母", "航空母艦", "航空母舰", "항공모함", "항모"],
    "type055": ["Type 055", "055型", "055형"],
    "j16": ["J-16", "殲-16", "歼-16", "J16"],
    "j35": ["J-35", "殲-35", "歼-35"],
    "su30": ["Su-30", "蘇愷30", "苏-30"],
    "h6_bomber": ["H-6", "轟-6", "轰-6", "H6 bomber", "폭격기"],
    "drone": ["drone", "UAV", "unmanned aerial",
              "無人機", "无人机", "무인기", "드론"],
    "balloon": ["balloon", "氣球", "气球", "기구", "풍선"],
    "submarine": ["submarine", "潛艦", "潜艇", "潛艇", "잠수함"],
    "missile": ["missile", "飛彈", "导弹", "飛弾", "미사일"],
    "helicopter": ["helicopter", "chopper", "直升機", "直升机", "헬기", "헬리콥터"],
    "warship": ["warship", "naval vessel", "軍艦", "军舰", "艦艇", "舰艇",
                "共艦", "共舰", "船艦", "군함", "함정"],
    "aircraft_sortie": ["sortie", "架次", "機艦", "机舰", "軍機", "军机",
                        "共機", "共机", "출격", "군용기"],
    # --- 사건 유형 ---------------------------------------------------------
    # 이 구간이 클러스터링의 핵심 자산이다. 행위자·장소·장비는 같은 배우가 모든
    # 사건에 나오므로 사건을 식별하지 못한다(실측 순도: pla 0.24, roc_military
    # 0.14, xi_jinping 0.00). 사건을 식별하는 것은 사건 유형과 고유명뿐이다
    # (live_fire 1.00, military_drill 0.99).
    # '연습 행사'(軍演·演習·Han Kuang 같은 지정된 훈련)만 앵커로 둔다.
    # 아래 rehearsal 과 갈라놓은 이유는 실측이다 — 하나로 두면 사막의 총통부
    # 모형에서 '演練斬首'(참수 리허설)와 한광훈련의 '演習'이 같은 앵커를 공유해
    # 서로 무관한 세 스토리가 한 A등급 카드로 붙는다(혼입 12건 → 5건).
    #
    # 맨 '軍演' 은 뺐다. CJK 별칭은 부분문자열로 맞추는데 '共軍演練'(공군이
    # 리허설한다)·'共軍演習' 안에 共**軍演**練 처럼 글자 경계를 넘어 우연히
    # 걸린다. 그 오탐 하나 때문에 사막 총통부 모형 기사가 한광훈련 카드로
    # 붙었다(혼입 3건 → 1건). '演習' 이 있으므로 손실은 없다.
    "military_drill": ["military drill", "military exercise",
                       "演習", "演习", "軍事演習", "军事演习",
                       "軍訓", "军训", "군사훈련", "군사 훈련"],
    # '리허설한다'는 서술. 특정 훈련 행사를 지목하지 못하므로 앵커가 아니다.
    "rehearsal": ["drill", "exercise", "manoeuvre", "maneuver",
                  "rehearse", "rehearsal",
                  "演練", "演练", "演訓", "훈련", "연습"],
    # 도상훈련·워게임은 실제 무력행사가 아니다. military_drill 에 두면 미 의회
    # 시뮬레이션 기사가 실탄사격 사건에 빨려 들어간다(실측: 정밀도 0.915→0.979).
    "tabletop_wargame": ["war game", "wargame", "tabletop exercise", "simulation",
                         "兵推", "兵棋推演", "워게임", "도상훈련"],
    # 대만 자신의 민방위 훈련도 중국군 훈련과 별개 사건이다.
    "civil_defense": ["civil defense", "civil defence",
                      "民防", "民安演習", "全民防衛", "민방위", "민방공"],
    "live_fire": ["live-fire", "live fire", "livefire", "live ammunition",
                  "live rounds",
                  "實彈", "实弹", "實彈射擊", "实弹射击", "實彈演習", "实弹演习",
                  "實彈演訓", "射擊", "射击", "실탄", "실사격", "실탄사격"],
    "nav_warning": ["navigation warning", "notice to mariners",
                    "航行警告", "航行警报", "禁航", "항행경보"],
    "restricted_zone": ["restricted flight zone", "restricted zone",
                        "飛行限制區", "飞行限制区", "限航區",
                        "비행제한구역", "제한비행구역", "제한 비행구역"],
    "line_crossing": ["crosses the median line", "median-line crossing",
                      "逾越", "越過中線", "越中線", "首越", "越線",
                      "월경", "중간선 통과"],
    "condemn": ["condemn", "denounce", "譴責", "谴责", "嚴正抗議", "严正抗议",
                "규탄", "항의"],
    "freedom_navigation": ["freedom of navigation", "航行自由", "통행 자유",
                           "항행의 자유"],
    "blockade": ["blockade", "quarantine",
                 "封鎖", "封锁", "봉쇄", "해상봉쇄"],
    "invasion": ["invasion", "invade", "seizure", "attack on Taiwan",
                 "攻台", "侵台", "犯台", "武統", "武统",
                 "침공", "무력통일", "무력 통일"],
    "incursion": ["incursion", "intrusion", "airspace violation",
                  "擾台", "扰台", "越界", "침범", "진입"],
    "arms_sale": ["arms sale", "weapons sale", "arms package", "arms deal",
                  "軍售", "军售", "무기 판매", "무기판매", "방산 수출"],
    "gray_zone": ["gray zone", "grey zone", "灰色地帶", "灰色地带", "회색지대"],
    "cable_cut": ["undersea cable", "submarine cable", "cable cut",
                  "海底電纜", "海底电缆", "해저케이블", "해저 케이블"],
    "sanction": ["sanction", "制裁", "제재"],
    "espionage": ["espionage", "spy", "infiltration",
                  "間諜", "间谍", "滲透", "渗透", "간첩", "스파이"],
    # --- 훈련 작전명 -------------------------------------------------------
    "joint_sword": ["Joint Sword", "聯合利劍", "联合利剑", "연합리검"],
    "strait_thunder": ["Strait Thunder", "海峽雷霆", "海峡雷霆", "해협뇌정"],
    "han_kuang": ["Han Kuang", "漢光", "汉光", "한광"],
    # --- 정치 개념 ---------------------------------------------------------
    "one_china": ["one China", "One-China", "一個中國", "一个中国",
                  "하나의 중국", "일중"],
    "1992_consensus": ["1992 consensus", "九二共識", "九二共识", "92공식", "92 공식"],
    "reunification": ["reunification", "unification",
                      "統一", "统一", "통일"],
    "independence": ["Taiwan independence", "台獨", "台独", "대만독립", "대만 독립"],
    "status_quo": ["status quo", "現狀", "现状", "현상유지", "현상 유지"],
    "tra": ["Taiwan Relations Act", "台灣關係法", "台湾关系法", "대만관계법"],
    "chip_war": ["semiconductor", "chip", "TSMC",
                 "半導體", "半导体", "台積電", "台积电", "반도체"],
}


# ---------------------------------------------------------------------------
# 엔티티 종류 — 어떤 요소가 '같은 사건'의 증거가 될 수 있는가
# ---------------------------------------------------------------------------
# 실측으로 확인된 사실: 요소의 변별력은 희귀도의 함수가 아니다.
#
#   요소            문서빈도   IDF    같은사건/다른사건   순도
#   live_fire        28.9%    1.54      594 / 0        1.00
#   pla              14.8%    2.05       17 / 55       0.24
#   roc_military      3.9%    3.29        1 / 6        0.14
#   xi_jinping        2.3%    3.83        0 / 3        0.00
#
# pla 는 live_fire 보다 두 배 희귀한데 순도는 4분의 1이다. IDF 로 가중하면
# 완벽한 증거보다 유해한 증거를 더 신뢰하게 된다. 빈도 컷으로는 절대 잡히지
# 않으므로 종류로 판정한다.
#
# EVENT/NAMED 만 병합을 '허가'할 수 있다(앵커). 나머지는 유사도 점수에는
# 기여하지만 단독으로 두 클러스터를 잇지 못한다. ACTOR 를 앵커로 허용하는
# 순간 정밀도가 1.000 → 0.893 으로 무너진다.

KIND = {}


def _set_kind(kind, ids):
    for entity_id in ids:
        KIND[entity_id] = kind


_set_kind("EVENT", [
    "military_drill", "tabletop_wargame", "civil_defense", "live_fire",
    "nav_warning", "restricted_zone", "condemn",
    "freedom_navigation", "blockade", "arms_sale",
    "cable_cut", "sanction", "espionage",
])
# 행위이긴 하나 거의 매일 일어나 특정 사건을 지목하지 못하는 것들.
# 시그니처에는 남아 유사도에 기여하되 병합을 열지는 못한다.
# 실측: line_crossing 을 앵커로 두면 국방부 일일 집계와 '헬기 첫 월경' 사건이
# 한 카드로 묶인다(혼입 3건 → 0건, BCubed 0.895 → 0.905).
_set_kind("ROUTINE", ["line_crossing", "incursion"])
_set_kind("NAMED", [
    "joint_sword", "strait_thunder", "han_kuang",
    "shandong", "liaoning", "fujian", "type055",
    "j16", "j35", "su30", "h6_bomber",
])
_set_kind("ACTOR", [
    "pla", "plan_navy", "plaaf", "eastern_theater", "roc_military",
    "us_military", "jsdf", "coast_guard",
    "tw_mnd", "prc_mnd", "mac", "tao", "ait", "pentagon", "ipac",
    "lai_chingte", "xi_jinping", "trump", "hsiao_bikhim", "wang_yi",
    "wellington_koo", "cho_jungtai", "han_kuoyu", "chu_lilun", "ko_wenje",
])
_set_kind("PLACE", [
    "taiwan_strait", "median_line", "adiz", "kinmen", "matsu", "penghu",
    "pratas", "itu_aba", "bashi_channel", "miyako_strait", "hualien",
    "suao", "keelung", "kaohsiung", "taipei", "beijing",
    "south_china_sea", "east_china_sea", "senkaku", "yonaguni",
])
_set_kind("ASSET", [
    "aircraft_carrier", "drone", "balloon", "submarine", "missile",
    "helicopter", "warship", "aircraft_sortie",
])
_set_kind("TOPIC", [
    "rehearsal",
    # '攻台' 는 사건이 아니라 주제다(실측 순도 0.33). 논평·전망 기사가
    # 실제 군사 행동 기사와 묶이면 안 된다.
    "invasion", "gray_zone", "one_china", "1992_consensus", "reunification",
    "independence", "status_quo", "tra", "chip_war",
])

ANCHOR_KINDS = {"EVENT", "NAMED"}

# 숫자 앵커 하한. 실측 순도 — 2～4: 0.67, 5～9: 0.00, 10 이상: 1.00.
# "연 2일", "3가지 교훈" 같은 작은 수는 노이즈다. 시그니처에는 그대로 남아
# 점수와 숫자충돌 판정에 쓰이되, 병합을 열지는 못한다.
MIN_ANCHOR_NUMBER = 10


def anchors(sig):
    """시그니처 → 병합을 허가할 수 있는 요소 집합."""
    found = set()
    for item in sig:
        if isinstance(item, str) and item.startswith("n:"):
            try:
                if int(item[2:]) >= MIN_ANCHOR_NUMBER:
                    found.add(item)
            except ValueError:
                pass
        elif KIND.get(item) in ANCHOR_KINDS:
            found.add(item)
    return found


# 복수형 접미를 붙이면 안 되는 약어들. "PLAN" + s → "plans" 가 매칭된다.
_NO_SUFFIX = {
    "pla", "plan_navy", "plaaf", "ait", "adiz", "ipac", "tra", "mac", "tao",
    "jsdf", "tw_mnd", "prc_mnd", "type055", "j16", "j35", "su30", "h6_bomber",
}


def _build_matchers():
    latin, cjk = {}, {}
    for entity_id, aliases in ENTITIES.items():
        latin_aliases = [a for a in aliases if re.search(r"[A-Za-z]", a)]
        other_aliases = [a for a in aliases if not re.search(r"[A-Za-z]", a)]
        if latin_aliases:
            # 긴 별칭 우선. 교대 전체를 (?:...) 로 감싸야 단어 경계가 모든
            # 별칭에 적용된다. 감싸지 않으면 교대 우선순위가 가장 낮아
            # 경계가 첫·마지막 별칭에만 붙고, "PLA" 가 "place"·"plans" 에,
            # "AIT" 가 "Strait" 에 걸린다.
            parts = []
            for alias in sorted(latin_aliases, key=len, reverse=True):
                # 공백·하이픈을 서로 호환시킨다: "live-fire" ≡ "live fire"
                escaped = re.escape(alias).replace(r"\ ", r"[-\s]").replace(r"\-", r"[-\s]")
                parts.append(escaped)
            pattern = "|".join(parts)
            # 복수형·소유격을 허용한다. 약어는 제외 — "PLAN"+s 가 "plans" 에
            # 걸리는 것을 막아야 한다.
            suffix = "" if entity_id in _NO_SUFFIX else r"(?:e?s|'s|’s)?"
            latin[entity_id] = re.compile(
                rf"(?<![A-Za-z])(?:{pattern}){suffix}(?![A-Za-z])", re.IGNORECASE
            )
        if other_aliases:
            cjk[entity_id] = other_aliases
    return latin, cjk


_LATIN_MATCHERS, _CJK_ALIASES = _build_matchers()


def extract_entities(text):
    """텍스트 → 언어 중립 엔티티 ID 집합."""
    if not text:
        return set()
    found = set()
    for entity_id, pattern in _LATIN_MATCHERS.items():
        if pattern.search(text):
            found.add(entity_id)
    for entity_id, aliases in _CJK_ALIASES.items():
        if entity_id in found:
            continue
        for alias in aliases:
            if alias in text:
                found.add(entity_id)
                break
    return found


_NUMBER = re.compile(r"(?<![\d.,])(\d{1,3})(?![\d.,])")
_YEAR = re.compile(r"(?:19|20)\d{2}")


def extract_numbers(text):
    """제목의 숫자 지문.

    이 도메인에서 유독 잘 먹히는 신호다. 모든 매체가 국방부의 같은 일일 집계를
    인용하기 때문에 "40機艦" 과 "40 aircraft and ships" 가 '40' 이라는 거의
    유일한 지문을 공유한다. 언어를 몰라도 같은 사건임을 알 수 있다.
    """
    if not text:
        return set()
    masked = _YEAR.sub(" ", text)  # 연도는 변별력이 없다
    numbers = set()
    for match in _NUMBER.finditer(masked):
        value = int(match.group(1))
        if 2 <= value <= 999:  # 0·1 은 너무 흔해 노이즈
            numbers.add(value)
    return numbers


def signature(text):
    """엔티티 + 숫자를 합친 언어 중립 시그니처."""
    sig = set(extract_entities(text))
    sig |= {f"n:{n}" for n in extract_numbers(text)}
    return sig

# UI 표시용 한국어 라벨. 없는 엔티티는 ID 를 그대로 보여준다.
ENTITY_LABEL_KO = {
    "live_fire": "실탄사격", "military_drill": "군사훈련",
    "tabletop_wargame": "도상훈련", "civil_defense": "민방위",
    "nav_warning": "항행경보", "restricted_zone": "비행제한구역",
    "line_crossing": "중간선 통과", "condemn": "규탄",
    "freedom_navigation": "항행의 자유", "blockade": "봉쇄",
    "incursion": "침범", "arms_sale": "무기판매", "cable_cut": "해저케이블",
    "sanction": "제재", "espionage": "간첩",
    "joint_sword": "연합리검", "strait_thunder": "해협뇌정", "han_kuang": "한광훈련",
    "median_line": "해협 중간선", "adiz": "방공식별구역",
    "taiwan_strait": "대만해협", "kinmen": "진먼", "matsu": "마쭈",
    "penghu": "펑후", "pratas": "둥사", "bashi_channel": "바시해협",
    "south_china_sea": "남중국해", "east_china_sea": "동중국해",
    "senkaku": "센카쿠", "hualien": "화롄", "kaohsiung": "가오슝",
    "keelung": "지룽", "suao": "쑤아오", "taipei": "타이베이", "beijing": "베이징",
    "yonaguni": "요나구니", "itu_aba": "타이핑다오", "miyako_strait": "미야코해협",
    "pla": "인민해방군", "plan_navy": "중국 해군", "plaaf": "중국 공군",
    "eastern_theater": "동부전구", "roc_military": "대만군",
    "us_military": "미군", "jsdf": "자위대", "coast_guard": "해경",
    "tw_mnd": "대만 국방부", "prc_mnd": "중국 국방부", "mac": "대륙위원회",
    "tao": "국태판", "ait": "AIT", "pentagon": "미 국방부", "ipac": "IPAC",
    "lai_chingte": "라이칭더", "xi_jinping": "시진핑", "trump": "트럼프",
    "hsiao_bikhim": "샤오메이친", "wang_yi": "왕이", "wellington_koo": "구리슝",
    "cho_jungtai": "줘룽타이", "han_kuoyu": "한궈위", "chu_lilun": "주리룬",
    "ko_wenje": "커원저",
    "shandong": "산둥함", "liaoning": "랴오닝함", "fujian": "푸젠함",
    "type055": "055형", "j16": "J-16", "j35": "J-35", "su30": "Su-30",
    "h6_bomber": "H-6 폭격기", "aircraft_carrier": "항공모함",
    "drone": "무인기", "balloon": "기구", "submarine": "잠수함",
    "missile": "미사일", "helicopter": "헬기", "warship": "군함",
    "aircraft_sortie": "군용기 출격",
    "invasion": "침공론", "gray_zone": "회색지대", "one_china": "하나의 중국",
    "1992_consensus": "92공식", "reunification": "통일", "independence": "대만독립",
    "status_quo": "현상유지", "tra": "대만관계법", "chip_war": "반도체",
}
