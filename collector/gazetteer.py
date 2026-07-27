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
    "taiwan_strait": ["Taiwan Strait", "Strait of Taiwan",
                      "台海", "臺海", "台灣海峽", "台湾海峡", "臺灣海峽",
                      "대만해협", "타이완해협", "대만 해협"],
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
    "shandong": ["Shandong", "山東艦", "山东舰", "산둥함", "산둥호"],
    "liaoning": ["Liaoning", "遼寧艦", "辽宁舰", "랴오닝함", "랴오닝호"],
    "fujian": ["Fujian", "福建艦", "福建舰", "푸젠함", "푸젠호"],
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
    # --- 사건 유형 ---------------------------------------------------------
    "military_drill": ["military drill", "military exercise", "war game",
                       "wargame", "manoeuvre", "maneuver",
                       "軍演", "军演", "演習", "演习", "軍事演習", "军事演习",
                       "군사훈련", "군사 훈련", "훈련", "연습"],
    "live_fire": ["live-fire", "live fire", "livefire",
                  "實彈", "实弹", "實彈射擊", "实弹射击", "실탄", "실사격"],
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
            pattern = "|".join(
                re.escape(a) for a in sorted(latin_aliases, key=len, reverse=True)
            )
            latin[entity_id] = re.compile(rf"(?<![A-Za-z])(?:{pattern})(?![A-Za-z])",
                                          re.IGNORECASE)
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
