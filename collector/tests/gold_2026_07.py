"""2026-07 스냅샷 골드 라벨 — 클러스터링 회귀 테스트의 기준선.

기사 128건(2026-07-13 ～ 07-27)을 사람이 직접 읽고 사건별로 묶은 것이다.
임계값을 만지는 작업은 이 라벨 없이 하면 안 된다. 한쪽(파편화)을 고치면
반대쪽(과병합)이 조용히 터지는데, 지표가 없으면 알아챌 방법이 없다.

라벨링 원칙
-----------
1. **전수 라벨링은 불필요하다.** 클러스터링이 애초에 병합을 시도할 수 있는 쌍만
   판정하면 된다(48시간 이내 + 앵커 공유 = 전체 8,128쌍 중 826쌍). 단독 기사는
   작업이 0이고, 실제 판단이 필요한 건 다건 사건의 경계뿐이다.
2. **경계가 모호하면 억지로 정하지 말고 GRAY 로 빼고 평가에서 제외한다.**
   애매한 몇 쌍 때문에 지표가 흔들리면 파라미터 선택이 뒤집힌다.

키는 기사 제목의 정규화 해시(`normalize.py` 가 만드는 article id)가 아니라
**제목 앞부분 문자열**을 쓴다. 재수집으로 id 계산이 바뀌어도 라벨이 살아남고,
사람이 읽고 고칠 수 있어야 하기 때문이다.
"""

# 사건명 → 그 사건에 속한 기사 제목의 앞부분(고유 식별 가능한 길이)
EVENTS = {
    # 7/23～25 중국의 대만해협 실탄사격 훈련. 발표·규탄·해설이 모두 한 사건이다.
    # 현재 코드가 이걸 21～26장으로 쪼갠다.
    "DRILL_LIVEFIRE": [
        "China Amplifies Tensions with Taiwan Strait Drill",
        "China announces live-fire drills in Taiwan Strait",
        "快訊／陸突宣布連兩天在台海「實彈射擊」",
        "陸發布航行警告 今明2天在台海實彈射擊",
        "範圍曝光！中國宣布連兩天在台海「實彈射擊」軍演",
        "中國突宣布在台海實彈射擊 今明兩日禁止進入演習海域",
        "Beijing conducts live-fire drills in Taiwan Strait",
        "Taiwan Straits live-fire drills are routine warning",
        "China Stages Drills in Taiwan Strait Defying US Warning",
        "China begins 2 days of live-fire drills in Taiwan Strait",
        "China conducts live-fire exercises in Taiwan Strait",
        "China begins military exercises with live ammunition",
        "【更新】緊張升溫！中國宣布今明2天在台海實彈射擊",
        "China maintains pressure on Taiwan with new military exercises",
        "Taiwan Straits drills information already released",
        "China begins two days of live-fire drills in Taiwan Strait",
        "China begins military drills in Taiwan Strait amid escalating",
        "中共今明台海「實彈射擊」！梁文傑",
        "China begins two-day live-fire drills near Taiwan Strait",
        "陸在台海實彈射擊陸委會",
        "中共台海實彈射擊 國防部：嚴密警戒應處",
        "中國突宣布連2天台海實彈射擊 外交部嚴正譴責",
        "China launches two-day live-fire drills in Taiwan Strait",
        "China Launches Live-Fire Drills Near Taiwan After Rubio-Wang Talks",
        "中國突宣布台海實彈射擊外交部：即刻停止軍事挑釁",
        "時論廣場》大陸台海「軍訓」的三重意涵",
        "中國突宣布2天台海實彈射擊 外交部譴責",
        "中國連2天台海實彈射擊 外交部譴責破壞區域安全穩定",
        "陸台海實彈軍演2天 我嚴正譴責",
        "China launches military drills in Taiwan Strait following",
        "中, 대만해협 이틀째 실탄사격",
        "중국, 대만해역서 이틀째 실탄사격",
        "China Conducts Live-Fire Drills in Taiwan Strait for Second",
        "突宣布台海實彈射擊！8共機四面圍台路線曝",
        "中國宣布連兩天台海實彈射擊 外交部嚴正譴責",
        "中共連兩天台海射擊 軍事專家析背後圖謀",
        "중국 대만해협 이틀간 실탄 훈련",
        "共軍無預警多海域實彈演訓吳釗燮批",
        "大陸連2天台海實彈射擊之際 東部戰區釋出兩棲戰車",
        "共軍於台海進行實彈演訓 總統賴清德",
        "共軍實彈演習直逼台海！吳釗燮曬一圖",
        "中共連日台海實彈射擊 被指意圖軍事常態化",
    ],
    # 7/21～23 공군 헬기가 대만 제한비행구역·중간선을 처음 넘은 사건.
    # 한국어는 '제한비행구역', 영어는 'median line', 중국어는 '中線'을 쓴다.
    "HELI_MEDIAN_LINE": [
        "In apparent 1st, PLA chopper crosses Taiwan Strait median line",
        "\"중국군 헬기, 대만 제한비행구역 처음 진입",
        "중국군 헬기, 대만 '제한 비행구역' 첫 진입",
        "Chinese Military Deploys Helicopters, Drones in Taiwan Airspace",
        "중국군 헬기, 대만 비행제한구역 비행",
        "學者指共軍直升機首越台海中線 國防部",
        "“헬기까지 보내 간 보는 시진핑”",
        "What a helicopter’s flight in the Taiwan Strait says about",
    ],
    # PLA 출격 횟수가 3년 최저로 떨어졌다는 분석
    "SORTIE_3YR_LOW": [
        "Why PLA fighter jet sorties near Taiwan dropped to a 3-year low",
        "Why PLA jet sorties near Taiwan dropped to a 3-year low",
        "China's military activity around Taiwan hits three-year low",
        "川習會有效降溫？港媒：解放軍機在台海活動次數降至3年新低",
    ],
    # 7/25 국방부 일일 집계 — 40機艦 / 17架次 중간선 통과
    # (Taiwan News 의 '29 planes and 11 ships' 도 합계 40 으로 같은 발표다)
    "MND_DAILY_0725": [
        "中共台海實彈射擊演習 40架次共機艦出海擾台",
        "中共解放軍40機艦擾台17架次共機逾越台海中線",
        "中共台海實彈射擊！40架共機船艦擾台 17架次闖進空域",
        "Taiwan tracks 29 Chinese military planes and 11 ships",
        "中共40機艦船台海周邊活動 國軍嚴密監控應處",
    ],
    # 7/24 국방부 일일 집계 — 19架共機 / 12架次
    "MND_DAILY_0724": [
        "快訊／19架共機大舉出海！ 12架次逾越台海中線",
        "共軍大動作！19架軍機逼近台海 12架越中線",
    ],
    # 7/26 국방부 일일 집계 — 4架共機 / 7艘共艦 / 3艘公務船 (= 함정 10척)
    "MND_DAILY_0726": [
        "4架共機、7艘共艦及3艘公務船現蹤台海",
        "Taiwan tracks 10 Chinese ships, 4 military aircraft",
    ],
    # PHL-191 다연장로켓 '강철비' 분석
    "STEEL_RAIN": [
        "[VIDEO] China Unleashes \"Steel Rain\"",
        "What do the PLA’s ‘Steel Rain’ shells say about its war plans",
    ],
    # 루비오 국무장관의 대만해협 항행자유 발언
    "RUBIO_NAVIGATION": [
        "盧比歐：任何國家都無權限制台海通行自由",
        "盧比歐重申台海航行自由 任何國家都無權限制國際水道",
    ],
    # 태풍 중 일본 해경선의 대만해협 피항에 중국이 항의
    "JP_COASTGUARD_TYPHOON": [
        "China protests Japan coast guard sheltering in Taiwan Strait amid Typhoo",
        "China protests Japan coast guard sheltering in Taiwan Strait due to typh",
    ],
    # 이란 사례가 대만 시나리오에 주는 교훈
    "IRAN_LESSON": [
        "The Short-War Illusion: What Iran Teaches Beijing About Taiwan",
        "美國打不贏伊朗 專家藉此分析台海：給北京上了3課",
    ],
    # 대만 드론의 사우디 수출
    "DRONE_SAUDI": [
        "Taiwan's Drone Exports Surge into Saudi Market",
        "사우디 뚫은 대만 드론",
    ],
    # 중국 대표단의 일본 발언 반박 (China Daily 본판·홍콩판)
    "CN_REFUTES_JAPAN": [
        "Chinese delegation refutes Japan's false rhetoric on Taiwan Strait",
        "Chinese delegation refutes Japan's false rhetoric regarding Taiwan Strait",
    ],
    # 러시아가 중국의 대만 전쟁 준비를 돕고 있다는 보도
    "RU_ASSISTS_CN": [
        "Russia May Be Helping China Prepare for War Over Taiwan",
        "China receives combat experience and technology from Russia",
    ],
    # 중국 사막의 대만 총통부 실물 모형 위성 포착
    "DESERT_REPLICA": [
        "中國沙漠驚現「台灣總統府」",
        "擴建山寨台北3倍！英媒揭共軍挖280公尺地下通道",
        "China’s Military Prepares for Taiwan Seizure with Detailed Replicas",
    ],
    # '대만 통일' 선전 영화의 중국 내 상영 금지
    "UNIFICATION_FILM": [
        "“대만 통일” 외치다 역풍",
        "Why is a film calling for Taiwan reunification drawing fire",
    ],
    # 미·일·한 외교장관 공동성명의 대만해협 평화 언급
    "TRILATERAL_FM": [
        "韓美日外長重申朝鮮半島無核化 強調台海和平穩定",
        "美日韓外長：維護台海和平 至關重要",
    ],
    # 환구시보 논평 '台海維權 新常態' 과 그 홍콩 전재
    "HAIFENG_NEW_NORMAL": [
        "Rights protection in the Taiwan Straits a ‘new normal’",
        "環球時報海風｜台海維權已經進入新常態",
    ],

    # ---------------------------------------------------------------------
    # 07-27 ～ 07-28 확장분.
    #
    # 이 구간을 넣는 이유가 있다. 07-27 까지의 코퍼스는 훈련 기사가 거의 전부
    # 같은 실탄사격 사건이어서 "military_drill 을 앵커로 써도 안전하다"는
    # 잘못된 결론이 나왔다. 아래 다섯 사건은 **서로 다른 훈련**이 같은 날
    # 공존하는 상황이라, 앵커 정책을 시험할 수 있는 유일한 구간이다.
    # ---------------------------------------------------------------------

    # 대만 연례 최대 군사훈련 한광(漢光) 개시 + 라이칭더 총통 격려
    "HAN_KUANG_2026": [
        "漢光演習將展開總統勗勉國軍精進訓練維持台海和平",
        "快新聞／漢光演習將登場！賴清德",
        "漢光演習將展開 總統勗勉國軍精進訓練維持台海和平",
        "漢光演習將登場賴清德登鑑勗勉國軍維持台海和平穩定",
        "賴清德勗勉國軍精進訓練 共同維持台海和平",
        "Taiwan’s Annual Han Kuang Drill Will Test Military and Society",
        "台灣年度漢光演習在即 實兵演練反制共軍攻台",
    ],
    # 한광훈련의 한 과목 — 무기 생산시설 이전 시험
    "ARMS_RELOCATION_DRILL": [
        "Taiwan drills to test relocating arms production under Chinese attack",
        "Taiwan Drills Test Relocating Arms Factories to Survive a Chinese Atta",
        "Taiwan to test relocation of weapons production in annual war games",
        "Taiwan Tests Relocating Weapons Production as Military Drills Prepare",
        "Taiwan's Strategic Shift: Civilian Factories to Military Powerhouses",
        "Taiwan to conduct drone and counter-drone drills in annual military ex",
    ],
    # AIT 가 미·대만 해순 함정 공동항행 사진을 이례적으로 공개
    "AIT_COASTGUARD_PHOTO": [
        "破天荒！AIT發布美台海巡艦海上共同演練照片",
        "AIT刻意公布美台海巡同框照",
        "刻意秀台美海巡船同框照 AIT",
        "中共海警台灣海域活動升高 AIT罕見秀美台海巡同框照",
        "AIT發布台美海巡船隻同框照古屋圭司",
        "AIT披露台美海巡艦編隊航行 管碧玲",
        "回應AIT公布美台海巡合作 管碧玲",
        "AIT公開台美海巡合作 管碧玲",
        "古屋圭司：守護台海和平理所當然",
        "台美海巡深化合作 共同守護台海與印太安全",
        "中海警頻擾AIT公布台海巡美國海岸防衛隊同框照",
        "影音／併航海巡艦艇！ 美方首公開與台海事合作",
    ],
    # 중국 사막의 타이베이 총통부 실물 모형 (스냅샷 DESERT_REPLICA 의 연장)
    "DESERT_REPLICA_2": [
        "總統府、蘇澳基地都被複製！衛星影像揭中國",
        "外媒揭共軍境內打造台北複製城",
        "共軍造台灣總統府模型演練 國防部：威脅嚴峻",
        "新聞360》中共山寨功力再升級！",
        "PLA building more Taiwan mock-ups",
        "中國沙漠暗藏台北「總統府」",
    ],
    # 이란전 탄약 소모 → 2027 대만해협 '취약 창' 논의
    "IRAN_AMMO_WINDOW": [
        "彈藥耗損讓川普暫停攻擊伊朗？2027台海風險",
        "庫存告急？美軍打伊朗狂燒飛彈 專家：台海開戰恐撐不住",
        "伊朗戰爭耗損美軍彈藥 美智庫警告2027年台海恐現「脆弱窗口期」",
        "美國彈藥短缺才停轟伊朗？BBC：是防止台海曝「脆弱窗口」",
        "川普口中完美的伊朗戰爭，為何讓美軍彈藥在2027台海",
        "手握鐵鎚卻受困！紐時爆川普陷伊朗戰爭3難題華府緊盯台海",
    ],
    # 7/30 중국 로켓 발사가 대만 ADIZ 를 통과할 것이라는 국방부 예고
    "ROCKET_THROUGH_ADIZ": [
        "Chinese rocket launch expected to pass through Taiwan ADIZ",
        "國防部：中共預計7/30發射火箭將經過台灣防空識別區",
    ],
    # 대만·영국 드론 산업 MOU (초기 라벨에서 놓쳤던 쌍)
    "UK_DRONE_MOU": [
        "Taiwan, U.K. sign MOU to boost bilateral drone industry exchanges",
        "Taiwan and UK drone industry groups sign MOU",
    ],
    # 미 의회의 대만 국방 예산 승인
    "US_CONGRESS_AID": [
        "US Congress approves money for Taiwan defense",
        "U.S. Congress Approves $500 Million Military Aid for Taiwan",
    ],
}

# 경계가 모호해 평가에서 제외하는 사건쌍.
# 이 쌍들은 어떻게 묶이든 정답으로도 오답으로도 세지 않는다.
GRAY_PAIRS = [
    # 7/25 집계 기사 일부가 실탄사격 훈련을 함께 다룬다 — 경계가 실제로 모호하다
    ("DRILL_LIVEFIRE", "MND_DAILY_0725"),
    ("DRILL_LIVEFIRE", "MND_DAILY_0724"),
    ("DRILL_LIVEFIRE", "MND_DAILY_0726"),
    # 훈련 기간 중의 헬기 월경 — 별개 사건이지만 같은 압박 국면
    ("DRILL_LIVEFIRE", "HELI_MEDIAN_LINE"),
    ("STEEL_RAIN", "HELI_MEDIAN_LINE"),
    # 서로 다른 날의 일일 집계끼리
    ("MND_DAILY_0724", "MND_DAILY_0725"),
    ("MND_DAILY_0724", "MND_DAILY_0726"),
    ("MND_DAILY_0725", "MND_DAILY_0726"),
    # 무기생산 이전 시험은 한광훈련의 한 과목이다. 별개 스토리로 보도되지만
    # 같은 훈련이라 어느 쪽으로 묶여도 틀렸다고 할 수 없다.
    ("HAN_KUANG_2026", "ARMS_RELOCATION_DRILL"),
    # 07-27 과 07-28 의 사막 모형 보도는 같은 사건의 이틀치다.
    ("DESERT_REPLICA", "DESERT_REPLICA_2"),
]


def build_index():
    """제목 접두 → 사건명. 접두가 긴 것부터 매칭한다."""
    pairs = []
    for event, prefixes in EVENTS.items():
        for prefix in prefixes:
            pairs.append((prefix, event))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs


_INDEX = build_index()


def label_of(title):
    """기사 제목 → 사건명. 라벨이 없으면 None(단독 기사)."""
    for prefix, event in _INDEX:
        if title.startswith(prefix) or prefix in title:
            return event
    return None


def is_gray(a, b):
    if a is None or b is None or a == b:
        return False
    return (a, b) in GRAY_PAIRS or (b, a) in GRAY_PAIRS
