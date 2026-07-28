"""피드 레지스트리와 출처 신뢰도 테이블.

이 파일이 트래커의 편집 가능한 정책 데이터. 코드 수정 없이 여기만 고쳐서
출처를 추가하거나 등급을 조정한다.
"""

# ---------------------------------------------------------------------------
# 출처 등급
# ---------------------------------------------------------------------------
# T1  통신사·공영방송      — 1차 취재망, 정정 관행 확립
# T2  주요 일간지          — 자체 취재, 편집 성향은 bias 필드로 별도 표기
# TA  분석·싱크탱크        — 정확도 높으나 속보성 없음
# T3  국가 관영·정부 발표  — 사실 관계는 1차 출처지만 프레이밍 편향 필수 표기
# T5  미분류               — 등급표에 없는 도메인의 기본값

TIER_WEIGHT = {
    "T1": 1.00,
    "T2": 0.85,
    "TA": 0.90,
    "T3": 0.60,
    "T4": 0.45,
    "T5": 0.30,
}

TIER_LABEL_KO = {
    "T1": "통신사·공영",
    "T2": "주요 일간",
    "TA": "분석기관",
    "T3": "관영·정부",
    "T4": "성향 매체",
    "T5": "미분류",
}

# 진영(bloc): 교차검증에서 '독립성'을 판정하는 축.
# independent 가 아닌 진영은 소속 매체가 몇 곳이든 독립 출처 1개로만 계산된다.
# (환구시보 + 신화 + CCTV 동시 보도로는 교차검증 점수가 오르지 않는다)
BLOC_LABEL_KO = {
    "independent": "독립",
    "prc_state": "중국 관영",
    "tw_state": "대만 국영·정부",
    "us_gov": "미국 정부·지원",
    "jp_gov": "일본 정부",
    # 등급표에 없는 도메인. 성격을 판정할 수 없으므로 교차검증 계산에서 뺀다.
    # 단, 점수에는 낮은 가중으로 반영한다 — 순위는 밀어줄 수 있어도 등급은
    # 살 수 없게 한다. T5 도메인의 3할은 정당한 소규모 매체라 하드 배제는
    # 부당하고, build_meta 의 승격 대기열로 사람이 계속 등록해야 한다.
    "unknown": "미분류",
}

# 같은 상위 조직을 공유하는 매체는 독립 증언 하나로 본다.
# GROUP_ALIASES 는 서브도메인 정규화용이라 이 관계를 표현하지 못한다.
AFFILIATE_GROUP = {
    "epochtimes.com": "falun_gong",
    "theepochtimes.com": "falun_gong",
    "ntdtv.com": "falun_gong",
    "ntdtv.com.tw": "falun_gong",
    "visiontimes.com": "falun_gong",
    "soundofhope.org": "falun_gong",
    "rt.com": "ru_state_media",
    "sputniknews.com": "ru_state_media",
}


def affiliate_of(domain):
    """도메인 → 독립성 계산 단위(계열이 있으면 계열 키)."""
    canon = canonical_domain(domain)
    return AFFILIATE_GROUP.get(canon, canon or "unknown")

# domain -> (tier, bloc, 표시명, 편향 메모 or None)
SOURCES = {
    # --- T1 통신사·공영방송 -------------------------------------------------
    "reuters.com": ("T1", "independent", "Reuters", None),
    "apnews.com": ("T1", "independent", "AP", None),
    "afp.com": ("T1", "independent", "AFP", None),
    "bbc.com": ("T1", "independent", "BBC", None),
    "bbc.co.uk": ("T1", "independent", "BBC", None),
    "aljazeera.com": ("T1", "independent", "Al Jazeera", None),
    "kyodonews.net": ("T1", "independent", "Kyodo News", None),
    "yna.co.kr": ("T1", "independent", "연합뉴스", None),
    "nhk.or.jp": ("T1", "independent", "NHK", None),
    "dw.com": ("T1", "independent", "Deutsche Welle", None),
    "france24.com": ("T1", "independent", "France 24", None),
    "rfi.fr": ("T1", "independent", "RFI", None),
    "upi.com": ("T1", "independent", "UPI", None),
    "aninews.in": ("T1", "independent", "ANI", None),
    "pts.org.tw": ("T1", "independent", "公視 PTS", "대만 공영방송(편집권 독립)"),
    "bloomberg.com": ("T1", "independent", "Bloomberg", None),
    "cnn.com": ("T1", "independent", "CNN", None),
    "abc.net.au": ("T1", "independent", "ABC (호주)", None),
    "channelnewsasia.com": ("T1", "independent", "CNA (싱가포르)", None),
    # --- T2 주요 일간지 -----------------------------------------------------
    "nytimes.com": ("T2", "independent", "New York Times", None),
    "washingtonpost.com": ("T2", "independent", "Washington Post", None),
    "wsj.com": ("T2", "independent", "Wall Street Journal", None),
    "ft.com": ("T2", "independent", "Financial Times", None),
    "theguardian.com": ("T2", "independent", "The Guardian", None),
    "economist.com": ("T2", "independent", "The Economist", None),
    "newsweek.com": ("T2", "independent", "Newsweek", None),
    "politico.com": ("T2", "independent", "Politico", None),
    "thehill.com": ("T2", "independent", "The Hill", None),
    "cnbc.com": ("T2", "independent", "CNBC", None),
    "nbcnews.com": ("T2", "independent", "NBC News", None),
    "japantimes.co.jp": ("T2", "independent", "Japan Times", None),
    "asahi.com": ("T2", "independent", "아사히신문", None),
    "yomiuri.co.jp": ("T2", "independent", "요미우리신문", None),
    "nikkei.com": ("T2", "independent", "Nikkei", None),
    "straitstimes.com": ("T2", "independent", "Straits Times", None),
    "scmp.com": ("T2", "independent", "SCMP", "홍콩 소재·알리바바 그룹 소유"),
    "taipeitimes.com": ("T2", "independent", "Taipei Times", "대만 범녹색(친민진당) 성향"),
    "taiwannews.com.tw": ("T2", "independent", "Taiwan News", None),
    "ltn.com.tw": ("T2", "independent", "自由時報", "대만 범녹색(친민진당) 성향"),
    "chinatimes.com": ("T2", "independent", "中國時報", "대만 범파란(친국민당) 성향"),
    "udn.com": ("T2", "independent", "聯合報", "대만 범파란(친국민당) 성향"),
    "storm.mg": ("T2", "independent", "風傳媒", None),
    "newtalk.tw": ("T2", "independent", "新頭殼", None),
    "setn.com": ("T2", "independent", "三立新聞", "대만 범녹색 성향"),
    "tvbs.com.tw": ("T2", "independent", "TVBS", None),
    "ettoday.net": ("T2", "independent", "ETtoday新聞雲", None),
    "taisounds.com": ("T2", "independent", "太報 TaiSounds", None),
    "mirrormedia.mg": ("T2", "independent", "鏡週刊", None),
    "ctwant.com": ("T2", "independent", "CTWANT", None),
    "ebc.net.tw": ("T2", "independent", "東森新聞", None),
    "cts.com.tw": ("T2", "independent", "華視", None),
    "ftvnews.com.tw": ("T2", "independent", "民視新聞", "대만 범녹색 성향"),
    "hk01.com": ("T2", "independent", "香港01", "홍콩 소재"),
    "washingtontimes.com": ("T2", "independent", "Washington Times", "미국 보수 성향"),
    "thehindu.com": ("T2", "independent", "The Hindu", None),
    "timesofindia.indiatimes.com": ("T2", "independent", "Times of India", None),
    "tribuneindia.com": ("T2", "independent", "Tribune India", None),
    "theglobeandmail.com": ("T2", "independent", "Globe and Mail", None),
    "telegraph.co.uk": ("T2", "independent", "The Telegraph", None),
    "independent.co.uk": ("T2", "independent", "The Independent", None),
    "lemonde.fr": ("T2", "independent", "Le Monde", None),
    "elmundo.es": ("T2", "independent", "El Mundo", None),
    "spiegel.de": ("T2", "independent", "Der Spiegel", None),
    "usni.org": ("T2", "independent", "USNI News", None),
    "defensenews.com": ("T2", "independent", "Defense News", None),
    "breakingdefense.com": ("T2", "independent", "Breaking Defense", None),
    "janes.com": ("T2", "independent", "Janes", None),
    "nocutnews.co.kr": ("T2", "independent", "노컷뉴스", None),
    "etoday.co.kr": ("T2", "independent", "이투데이", None),
    "kmib.co.kr": ("T2", "independent", "국민일보", None),
    "segye.com": ("T2", "independent", "세계일보", None),
    "munhwa.com": ("T2", "independent", "문화일보", None),
    "chosunbiz.com": ("T2", "independent", "조선비즈", None),
    "chosun.com": ("T2", "independent", "조선일보", None),
    "joongang.co.kr": ("T2", "independent", "중앙일보", None),
    "donga.com": ("T2", "independent", "동아일보", None),
    "hani.co.kr": ("T2", "independent", "한겨레", None),
    "khan.co.kr": ("T2", "independent", "경향신문", None),
    "hankyung.com": ("T2", "independent", "한국경제", None),
    "mk.co.kr": ("T2", "independent", "매일경제", None),
    "sbs.co.kr": ("T2", "independent", "SBS", None),
    "kbs.co.kr": ("T2", "independent", "KBS", None),
    "imbc.com": ("T2", "independent", "MBC", None),
    "ytn.co.kr": ("T2", "independent", "YTN", None),
    "news1.kr": ("T2", "independent", "뉴스1", None),
    "newsis.com": ("T2", "independent", "뉴시스", None),
    "hankookilbo.com": ("T2", "independent", "한국일보", None),
    "seoul.co.kr": ("T2", "independent", "서울신문", None),
    "mbn.co.kr": ("T2", "independent", "MBN", None),
    "asiaone.com": ("T2", "independent", "AsiaOne", None),
    "skynews.com.au": ("T2", "independent", "Sky News Australia", "호주 보수 성향"),
    "theprint.in": ("T2", "independent", "ThePrint", None),
    "japantoday.com": ("T2", "independent", "Japan Today", None),
    "kbmaeil.com": ("T2", "independent", "경북매일", None),
    "mhns.co.kr": ("T2", "independent", "경남매일", None),
    "tyenews.com": ("T2", "independent", "桃園電子報", None),
    # --- TA 분석·싱크탱크 ---------------------------------------------------
    "csis.org": ("TA", "independent", "CSIS", None),
    "gmu.edu": ("TA", "independent", "Taiwan Security Monitor (GMU)", None),
    "globaltaiwan.org": ("TA", "independent", "Global Taiwan Institute", None),
    "understandingwar.org": ("TA", "independent", "ISW", None),
    "thediplomat.com": ("TA", "independent", "The Diplomat", None),
    "warontherocks.com": ("TA", "independent", "War on the Rocks", None),
    "jamestown.org": ("TA", "independent", "Jamestown Foundation", None),
    "rand.org": ("TA", "independent", "RAND", None),
    "brookings.edu": ("TA", "independent", "Brookings", None),
    "lowyinstitute.org": ("TA", "independent", "Lowy Institute", None),
    "iiss.org": ("TA", "independent", "IISS", None),
    "lawfaremedia.org": ("TA", "independent", "Lawfare", None),
    "defenseone.com": ("TA", "independent", "Defense One", None),
    "hudson.org": ("TA", "independent", "Hudson Institute", None),
    "asiasociety.org": ("TA", "independent", "Asia Society", None),
    "atlanticcouncil.org": ("TA", "independent", "Atlantic Council", None),
    "cfr.org": ("TA", "independent", "Council on Foreign Relations", None),
    "carnegieendowment.org": ("TA", "independent", "Carnegie Endowment", None),
    "stimson.org": ("TA", "independent", "Stimson Center", None),
    "foreignpolicy.com": ("TA", "independent", "Foreign Policy", None),
    "foreignaffairs.com": ("TA", "independent", "Foreign Affairs", None),
    "nationalinterest.org": ("TA", "independent", "The National Interest", None),
    "aei.org": ("TA", "independent", "AEI", None),
    "inss.re.kr": ("TA", "independent", "국가안보전략연구원", None),
    "kida.re.kr": ("TA", "independent", "한국국방연구원", None),
    # --- T4 뚜렷한 당파·선전 성향 (원 취재는 하나 신뢰도 논쟁적) ------------
    "epochtimes.com": ("T4", "independent", "大紀元 Epoch Times", "파룬궁 계열·강한 반중공 논조"),
    "theepochtimes.com": ("T4", "independent", "Epoch Times", "파룬궁 계열·강한 반중공 논조"),
    "ntdtv.com": ("T4", "independent", "新唐人 NTD", "파룬궁 계열·강한 반중공 논조"),
    "ntdtv.com.tw": ("T4", "independent", "新唐人 NTD", "파룬궁 계열·강한 반중공 논조"),
    "visiontimes.com": ("T4", "independent", "看中國 Vision Times", "파룬궁 계열·강한 반중공 논조"),
    "rt.com": ("T4", "independent", "RT", "러시아 국영·선전 매체"),
    "sputniknews.com": ("T4", "independent", "Sputnik", "러시아 국영·선전 매체"),
    "zerohedge.com": ("T4", "independent", "ZeroHedge", "선정적 논조·검증 부실"),
    # --- T3 중국 관영 -------------------------------------------------------
    "globaltimes.cn": ("T3", "prc_state", "環球時報 Global Times", "중국 공산당 기관지 계열"),
    "xinhuanet.com": ("T3", "prc_state", "新華社 Xinhua", "중국 국영 통신사"),
    "news.cn": ("T3", "prc_state", "新華社 Xinhua", "중국 국영 통신사"),
    "chinadaily.com.cn": ("T3", "prc_state", "China Daily", "중국 국영 영문지"),
    "cgtn.com": ("T3", "prc_state", "CGTN", "중국 국영 방송"),
    "people.com.cn": ("T3", "prc_state", "人民日報", "중국 공산당 기관지"),
    "chinamil.com.cn": ("T3", "prc_state", "中國軍網", "중국 인민해방군 매체"),
    "ecns.cn": ("T3", "prc_state", "中國新聞網", "중국 국영"),
    "mod.gov.cn": ("T3", "prc_state", "중국 국방부", "중국 정부 공식 발표"),
    "gwytb.gov.cn": ("T3", "prc_state", "국무원 대만사무판공실", "중국 정부 공식 발표"),
    "scio.gov.cn": ("T3", "prc_state", "국무원 신문판공실", "중국 정부 공식 발표"),
    "chinadailyhk.com": ("T3", "prc_state", "China Daily HK", "중국 국영 영문지 홍콩판"),
    "hkcna.hk": ("T3", "prc_state", "香港中國通訊社", "중국 국영 계열"),
    "wenweipo.com": ("T3", "prc_state", "文匯報", "홍콩 친중공 매체"),
    "takungpao.com": ("T3", "prc_state", "大公報", "홍콩 친중공 매체"),
    "china.com.cn": ("T3", "prc_state", "中國網", "중국 국영"),
    "tkww.hk": ("T3", "prc_state", "大公文匯網", "홍콩 친중공 매체"),
    "bastillepost.com": ("T3", "prc_state", "巴士的報", "홍콩 친중공 매체"),
    "huanqiu.com": ("T3", "prc_state", "環球網", "환구시보 중문판·중국 공산당 기관지 계열"),
    "cctv.com": ("T3", "prc_state", "CCTV 中央電視台", "중국 국영 방송"),
    "cctv.cn": ("T3", "prc_state", "CCTV 中央電視台", "중국 국영 방송"),
    "chinanews.com.cn": ("T3", "prc_state", "中國新聞網", "중국 국영 통신사"),
    "81.cn": ("T3", "prc_state", "中國軍網", "중국 인민해방군 매체"),
    "yicai.com": ("T3", "prc_state", "第一財經", "중국 국영 계열"),
    # --- T3 대만 국영·정부 --------------------------------------------------
    "cna.com.tw": ("T3", "tw_state", "中央社 CNA", "대만 국영 통신사"),
    "focustaiwan.tw": ("T3", "tw_state", "Focus Taiwan (CNA)", "대만 국영 통신사"),
    "rti.org.tw": ("T3", "tw_state", "中央廣播電臺", "대만 국영 방송"),
    "mnd.gov.tw": ("T3", "tw_state", "대만 국방부", "대만 정부 공식 발표"),
    "president.gov.tw": ("T3", "tw_state", "대만 총통부", "대만 정부 공식 발표"),
    "mofa.gov.tw": ("T3", "tw_state", "대만 외교부", "대만 정부 공식 발표"),
    "mac.gov.tw": ("T3", "tw_state", "대만 대륙위원회", "대만 정부 공식 발표"),
    # --- T3 미국 정부·지원 매체 ---------------------------------------------
    "defense.gov": ("T3", "us_gov", "미 국방부", "미국 정부 공식 발표"),
    "state.gov": ("T3", "us_gov", "미 국무부", "미국 정부 공식 발표"),
    "whitehouse.gov": ("T3", "us_gov", "백악관", "미국 정부 공식 발표"),
    "pacom.mil": ("T3", "us_gov", "미 인도태평양사령부", "미국 정부 공식 발표"),
    "indopacom.mil": ("T3", "us_gov", "미 인도태평양사령부", "미국 정부 공식 발표"),
    "voanews.com": ("T2", "us_gov", "VOA", "미국 정부 지원(USAGM) 매체"),
    "rfa.org": ("T2", "us_gov", "RFA 자유아시아방송", "미국 정부 지원(USAGM) 매체"),
    # --- T3 일본 정부 -------------------------------------------------------
    "mod.go.jp": ("T3", "jp_gov", "일본 방위성", "일본 정부 공식 발표"),
}

# 포털·재배포 사이트. 원 매체 기사를 그대로 실어 나르므로 독립 출처가 아니다.
# 교차검증 점수를 부풀리는 주범이라 수집 단계에서 버린다.
SYNDICATORS = (
    "yahoo.com",
    "msn.com",
    "news.nate.com",
    "daum.net",
    "naver.com",
    "pchome.com.tw",
    "flipboard.com",
    "ground.news",
    "newsbreak.com",
    "smartnews.com",
    "headtopics.com",
    "newscord.org",
    "biztoc.com",
    "zhuanlan.zhihu.com",
)


# 주제와 무관한 업종 매체. 대만이 언급됐다는 이유로 흘러 들어온다.
NOISE_DOMAINS = (
    "cryptobriefing.com",
    "investinglive.com",
    "coindesk.com",
    "cointelegraph.com",
    "marinelink.com",
    "ajot.com",
    "fool.com",
    "benzinga.com",
    "tipranks.com",
    "seekingalpha.com",
)


def is_syndicator(domain):
    if not domain:
        return False
    domain = domain.lower()
    return any(domain == s or domain.endswith("." + s) for s in SYNDICATORS)


def is_noise(domain):
    if not domain:
        return False
    domain = domain.lower()
    return any(domain == s or domain.endswith("." + s) for s in NOISE_DOMAINS)


# 같은 언론 그룹은 독립 출처 1개로 취급 (도메인 → 그룹 키)
GROUP_ALIASES = {
    "asia.nikkei.com": "nikkei.com",
    "focustaiwan.tw": "cna.com.tw",
    "english.kyodonews.net": "kyodonews.net",
    "en.yna.co.kr": "yna.co.kr",
    "news.cn": "xinhuanet.com",
    "world.kbs.co.kr": "kbs.co.kr",
    "biz.chosun.com": "chosun.com",
    "air.mnd.gov.tw": "mnd.gov.tw",
}

# 미등록 도메인은 'independent' 가 아니라 'unknown' 이다. 검증 안 된 사이트가
# 자동으로 '독립 증언' 자격을 얻으면 무명 재게재 사이트 두 곳만으로 B등급이 난다.
DEFAULT_SOURCE = ("T5", "unknown", None, None)


# ---------------------------------------------------------------------------
# 주제 게이트
# ---------------------------------------------------------------------------
# 3단 규칙. 단순 키워드 OR 로는 걸러지지 않는 두 가지 오검출을 잡기 위한 구조다.
#
#   1) 中央社·Taipei Times 같은 전 섹션 피드는 요약문 앞머리가 "Taipei, July 27
#      (CNA)" 형태의 데이트라인이라, "taipei" 만 보면 증시·야구 기사까지 통과한다.
#      → 군사 신호는 '제목'에서만 찾는다.
#   2) "金正恩攜妻女赴共軍陵園"(한국전쟁 기념) 처럼 共軍 이 대만과 무관하게 쓰이는
#      경우가 있다. → 대만 언급을 필수 조건으로 둔다.
#
# 최종 판정:  대만 언급 AND ( 양안 핵심어(어디든) OR 군사어(제목) )

import re as _re

TAIWAN_MENTION = _re.compile(
    r"taiwan|taipei|taiwanese|formosa|kinmen|matsu|penghu|pratas"
    r"|台灣|台湾|臺灣|臺湾|台北|台海|兩岸|两岸|金門|金门|馬祖|马祖|澎湖"
    r"|대만|타이완|진먼|펑후",
    _re.IGNORECASE,
)

# 그 자체로 주제를 확정하는 핵심어 — 제목·요약 어디서 걸려도 채택
CORE_TOPIC = _re.compile(
    r"taiwan strait|cross-strait|cross strait|taiwan tension|taiwan conflict"
    r"|taiwan contingency|invasion of taiwan|taiwan blockade"
    r"|台海|兩岸|两岸|擾台|扰台|攻台|侵台|犯台|封鎖台|封锁台"
    r"|대만해협|타이완해협|양안",
    _re.IGNORECASE,
)

# 군사·안보 신호 — 제목에서만 찾는다(요약문 보일러플레이트 오검출 방지)
MILITARY = _re.compile(
    r"\bPLA\b|people'?s liberation army|\bmilitary\b|defen[cs]e|\bnavy\b|naval"
    r"|warship|aircraft carrier|fighter jet|warplane|missile|drill|exercise"
    r"|incursion|\bADIZ\b|air defen[cs]e identification|median line|blockade"
    r"|invasion|invade|troops|\barmy\b|\bwar\b|sortie|coast guard|gray zone"
    r"|grey zone|conscription|arms sale|deterrence|submarine|drone|\bUAV\b"
    r"|live-fire|livefire|espionage|sanction|gunboat|amphibious|reunification"
    r"|共軍|共军|解放軍|解放军|軍演|军演|中線|中线|防空識別區|防空识别区"
    r"|飛彈|导弹|軍艦|军舰|戰機|战机|航母|封鎖|封锁|國防部|国防部|海警"
    r"|灰色地帶|灰色地带|軍售|军售|演習|演习|潛艦|潜艇|無人機|无人机|統一|统一"
    r"|중국군|인민해방군|군사|국방|미사일|전투기|항모|군함|봉쇄|침공|무기"
    r"|방공식별구역|해경|군용기|훈련|도발|무력|통일",
    _re.IGNORECASE,
)

# 통과해도 아래에 걸리면 버린다. 반도체 TSMC 실적 기사가 최대 노이즈원.
NEGATIVE = _re.compile(
    r"tsmc (earnings|revenue|profit|shares|stock|q[1-4])"
    r"|semiconductor (earnings|revenue|sales|shipment)"
    r"|台積電(法說|營收|財報|股價)|반도체 (실적|매출)"
    r"|crypto|bitcoin|token price",
    _re.IGNORECASE,
)


def passes_gate(title, summary):
    """주제 게이트. (통과여부, 탈락사유) 반환."""
    text = f"{title} {summary}"
    if NEGATIVE.search(text):
        return False, "negative"
    if not TAIWAN_MENTION.search(text):
        return False, "no_taiwan"
    if CORE_TOPIC.search(text) or MILITARY.search(title):
        return True, None
    return False, "no_topic"


# ---------------------------------------------------------------------------
# 피드 목록
# ---------------------------------------------------------------------------
# kind:
#   "aggregator" — Google News. 실제 출처는 각 항목의 <source url> 태그에서 뽑는다.
#   "native"     — 매체 자체 피드. 출처가 피드 단위로 고정.
# needs_filter — 전 섹션 피드라 주제 키워드 게이트를 통과해야 채택.

GOOGLE_NEWS = "https://news.google.com/rss/search"

FEEDS = [
    # 주의: Google News 쿼리에 괄호 중첩이나 AND 를 쓰면 최신순 랭킹이 깨지고
    # 관련도 정렬로 빠져 한 달 지난 기사만 돌아온다(2026-07-27 실측). 인용구의
    # 단순 OR 나열만 쓸 것.
    {
        "id": "gn_en",
        "name": "Google News (영어)",
        "url": (
            f"{GOOGLE_NEWS}?q=%22Taiwan+Strait%22+OR+%22Taiwan+tensions%22"
            "&hl=en-US&gl=US&ceid=US%3Aen"
        ),
        "lang": "en",
        "kind": "aggregator",
        "needs_filter": True,
        "note": "Reuters·AP·FT 등 자체 RSS가 없는 통신사를 이 경로로 확보",
    },
    {
        "id": "gn_en_mil",
        "name": "Google News (영어·군사)",
        "url": (
            f"{GOOGLE_NEWS}?q=Taiwan+military+China+when%3A7d"
            "&hl=en-US&gl=US&ceid=US%3Aen"
        ),
        "lang": "en",
        "kind": "aggregator",
        "needs_filter": True,
        "note": "해협 표현 없이 보도되는 훈련·분석 기사 보완",
    },
    {
        "id": "gn_ko",
        "name": "Google News (한국어)",
        "url": (
            f"{GOOGLE_NEWS}?q=%EB%8C%80%EB%A7%8C%ED%95%B4%ED%98%91+OR+%EC%96%91%EC%95%88"
            "+OR+(%EB%8C%80%EB%A7%8C+%EC%A4%91%EA%B5%AD%EA%B5%B0)"
            "&hl=ko&gl=KR&ceid=KR%3Ako"
        ),
        "lang": "ko",
        "kind": "aggregator",
        "needs_filter": True,
        "note": "대만해협 OR 양안 OR (대만 중국군)",
    },
    {
        "id": "gn_zh",
        "name": "Google News (중국어 번체)",
        "url": (
            f"{GOOGLE_NEWS}?q=%E5%8F%B0%E6%B5%B7+OR+%E5%85%B1%E8%BB%8D"
            "+OR+%E8%A7%A3%E6%94%BE%E8%BB%8D%E6%93%BE%E5%8F%B0"
            "&hl=zh-TW&gl=TW&ceid=TW%3Azh-Hant"
        ),
        "lang": "zh",
        "kind": "aggregator",
        "needs_filter": True,
        "note": "台海 OR 共軍 OR 解放軍擾台",
    },
    {
        "id": "gn_prc_state",
        "name": "Google News (중국 관영 감시)",
        "url": (
            f"{GOOGLE_NEWS}?q=site%3Aglobaltimes.cn+OR+site%3Achinadaily.com.cn"
            "+OR+site%3Acgtn.com+Taiwan"
            "&hl=en-US&gl=US&ceid=US%3Aen"
        ),
        "lang": "en",
        "kind": "aggregator",
        "needs_filter": True,
        "note": "관점 대조용. 중국 관영 매체의 대만 보도만 별도 수집",
    },
    {
        # 관영 영문판만 모으면 대만 매체(중국어)와 같은 사건으로 묶이지 않아
        # 관점 대조가 성립하지 않는다. 중국어 관영 스트림이 있어야 한다.
        "id": "gn_prc_zh",
        "name": "Google News (중국 관영·중국어)",
        "url": (
            f"{GOOGLE_NEWS}?q=site%3Ahuanqiu.com+OR+site%3Acctv.com"
            "+OR+site%3Achinanews.com.cn+%E5%8F%B0%E6%B9%BE"
            "&hl=zh-CN&gl=CN&ceid=CN%3Azh-Hans"
        ),
        "lang": "zh",
        "kind": "aggregator",
        "needs_filter": True,
        "note": "CCTV·환구망·중국신문망 등 중국어 관영 보도",
    },
    {
        "id": "focustaiwan",
        "name": "Focus Taiwan (中央社 영문)",
        "url": "https://feeds.feedburner.com/rsscna/engnews",
        "lang": "en",
        "kind": "native",
        "source_domain": "focustaiwan.tw",
        "needs_filter": True,
        "note": "전 섹션 배포 — 키워드 게이트 필수",
    },
    {
        "id": "taipeitimes",
        "name": "Taipei Times",
        "url": "https://www.taipeitimes.com/xml/index.rss",
        "lang": "en",
        "kind": "native",
        "source_domain": "taipeitimes.com",
        "needs_filter": True,
        "note": "대만 시간 매일 아침 일괄 갱신",
    },
    {
        "id": "scmp_china",
        "name": "SCMP 중국 섹션",
        "url": "https://www.scmp.com/rss/4/feed/",
        "lang": "en",
        "kind": "native",
        "source_domain": "scmp.com",
        "needs_filter": True,
        "note": "Cloudflare — 브라우저 UA 필수",
    },
    {
        # Kyodo 영문 RSS 는 2026-07 기준 전 경로 404. Japan Times 로 대체.
        "id": "japantimes",
        "name": "Japan Times",
        "url": "https://www.japantimes.co.jp/feed/",
        "lang": "en",
        "kind": "native",
        "source_domain": "japantimes.co.jp",
        "needs_filter": True,
        "note": "일본 시각의 양안 보도 (Kyodo RSS 폐지 대체)",
    },
    {
        "id": "tsm",
        "name": "Taiwan Security Monitor (GMU)",
        "url": "https://tsm.schar.gmu.edu/feed/",
        "lang": "en",
        "kind": "native",
        "source_domain": "gmu.edu",
        "needs_filter": True,
        "note": "PLA 활동 분석. 저빈도·고신뢰",
    },
    # --- 2차 보강 ---------------------------------------------------------
    {
        "id": "guardian_taiwan",
        "name": "The Guardian — Taiwan 태그",
        "url": "https://www.theguardian.com/world/taiwan/rss",
        "lang": "en",
        "kind": "native",
        "source_domain": "theguardian.com",
        "needs_filter": True,
        "note": "태그 피드라 이미 주제 한정",
    },
    {
        "id": "yonhap_en",
        "name": "연합뉴스 영문",
        "url": "https://en.yna.co.kr/RSS/news.xml",
        "lang": "en",
        "kind": "native",
        "source_domain": "yna.co.kr",
        "needs_filter": True,
        "note": None,
    },
    {
        "id": "bbc_asia",
        "name": "BBC News — 아시아",
        "url": "https://feeds.bbci.co.uk/news/world/asia/rss.xml",
        "lang": "en",
        "kind": "native",
        "source_domain": "bbc.co.uk",
        "needs_filter": True,
        "note": None,
    },
    {
        "id": "aljazeera",
        "name": "Al Jazeera",
        "url": "https://www.aljazeera.com/xml/rss/all.xml",
        "lang": "en",
        "kind": "native",
        "source_domain": "aljazeera.com",
        "needs_filter": True,
        "note": "전 주제 피드, 회전 빠름",
    },
    {
        "id": "gti",
        "name": "Global Taiwan Institute",
        "url": "https://globaltaiwan.org/feed/",
        "lang": "en",
        "kind": "native",
        "source_domain": "globaltaiwan.org",
        "needs_filter": True,
        "note": "주간 분석",
    },
]


def feed_by_id(feed_id):
    for feed in FEEDS:
        if feed["id"] == feed_id:
            return feed
    return None


def canonical_domain(domain):
    """서브도메인·언론그룹을 대표 도메인으로 통일."""
    if not domain:
        return ""
    domain = domain.lower().lstrip(".")
    if domain.startswith("www."):
        domain = domain[4:]
    if domain in GROUP_ALIASES:
        return GROUP_ALIASES[domain]
    if domain in SOURCES:
        return domain
    # 서브도메인을 한 단계씩 벗겨 등급표와 대조
    parts = domain.split(".")
    for i in range(1, len(parts) - 1):
        candidate = ".".join(parts[i:])
        if candidate in GROUP_ALIASES:
            return GROUP_ALIASES[candidate]
        if candidate in SOURCES:
            return candidate
    return domain


def classify(domain):
    """도메인 → (tier, bloc, 표시명, 편향메모). 미등록이면 T5/independent."""
    canon = canonical_domain(domain)
    tier, bloc, name, bias = SOURCES.get(canon, DEFAULT_SOURCE)
    return {
        "domain": canon,
        "tier": tier,
        "bloc": bloc,
        "name": name or canon,
        "bias": bias,
    }
