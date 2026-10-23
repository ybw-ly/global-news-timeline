#!/usr/bin/env python3
"""Build config/gazetteer.json.

Country names are generated from Babel for 19 locales, then augmented with
common short forms and demonyms. Cities, actors, organisations and event
topics are curated below. Runtime uses only the generated JSON.

Run:
    uv run --with babel python scripts/build_gazetteer.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from babel import Locale

ROOT = Path(__file__).resolve().parent.parent
COUNTRIES = json.loads((ROOT / "config" / "countries.json").read_text(encoding="utf-8"))

LOCALES = ["en", "zh", "ar", "ru", "es", "fr", "de", "ja", "ko", "pt", "tr", "fa", "he", "hi", "id", "vi", "th", "it", "uk"]
LOCALE_OBJECTS = {code: Locale(code) for code in LOCALES}

# Country names that are also common words or personal names. Matching checks
# capitalisation for these; they are never used from an all-lowercase feed.
AMBIGUOUS = {"turkey"}
# Names too ambiguous to be useful even with capitalisation.
EXCLUDED = {"georgia", "jordan", "chad", "guinea", "congo", "korea"}

COUNTRY_EXTRA: dict[str, dict[str, list[str]]] = {
    "US": {"strong": ["u.s.", "usa", "united states of america"], "weak": ["american"], "ambiguous": ["america", "us"]},
    "GB": {"strong": ["u.k.", "britain", "england", "scotland", "wales"], "weak": ["british"], "ambiguous": ["uk"]},
    "CN": {"strong": ["prc", "mainland china"], "weak": ["chinese"], "ambiguous": []},
    "RU": {"strong": [], "weak": ["russian"], "ambiguous": []},
    "UA": {"strong": [], "weak": ["ukrainian"], "ambiguous": []},
    "IL": {"strong": [], "weak": ["israeli"], "ambiguous": []},
    "PS": {"strong": ["palestinian territories", "west bank", "gaza strip"], "weak": ["palestinian"], "ambiguous": []},
    "IR": {"strong": [], "weak": ["iranian"], "ambiguous": []},
    "SA": {"strong": [], "weak": ["saudi", "saudi arabian"], "ambiguous": []},
    "TR": {"strong": ["türkiye"], "weak": ["turkish"], "ambiguous": ["turkey"]},
    "IN": {"strong": [], "weak": ["indian"], "ambiguous": []},
    "PK": {"strong": [], "weak": ["pakistani"], "ambiguous": []},
    "JP": {"strong": [], "weak": ["japanese"], "ambiguous": []},
    "KR": {"strong": ["republic of korea"], "weak": ["south korean"], "ambiguous": []},
    "KP": {"strong": ["dprk"], "weak": ["north korean"], "ambiguous": []},
    "DE": {"strong": [], "weak": ["german"], "ambiguous": []},
    "FR": {"strong": [], "weak": ["french"], "ambiguous": []},
    "BR": {"strong": [], "weak": ["brazilian"], "ambiguous": []},
    "MX": {"strong": [], "weak": ["mexican"], "ambiguous": []},
    "AR": {"strong": [], "weak": ["argentine", "argentinian"], "ambiguous": []},
    "ZA": {"strong": [], "weak": ["south african"], "ambiguous": []},
    "EG": {"strong": [], "weak": ["egyptian"], "ambiguous": []},
    "NG": {"strong": [], "weak": ["nigerian"], "ambiguous": []},
    "QA": {"strong": [], "weak": ["qatari"], "ambiguous": []},
    "AE": {"strong": ["uae"], "weak": ["emirati"], "ambiguous": []},
    "SY": {"strong": [], "weak": ["syrian"], "ambiguous": []},
    "IQ": {"strong": [], "weak": ["iraqi"], "ambiguous": []},
    "AF": {"strong": [], "weak": ["afghan"], "ambiguous": []},
    "ID": {"strong": [], "weak": ["indonesian"], "ambiguous": []},
    "VN": {"strong": [], "weak": ["vietnamese"], "ambiguous": []},
    "TH": {"strong": [], "weak": ["thai"], "ambiguous": []},
    "PH": {"strong": [], "weak": ["filipino", "philippine"], "ambiguous": []},
    "AU": {"strong": [], "weak": ["australian"], "ambiguous": []},
    "CA": {"strong": [], "weak": ["canadian"], "ambiguous": []},
    "TW": {"strong": ["chinese taipei"], "weak": ["taiwanese"], "ambiguous": []},
    "HK": {"strong": ["hongkong"], "weak": ["hong konger"], "ambiguous": []},
    "ES": {"strong": [], "weak": ["spanish"], "ambiguous": []},
    "IT": {"strong": [], "weak": ["italian"], "ambiguous": []},
    "PL": {"strong": [], "weak": ["polish"], "ambiguous": []},
    "NL": {"strong": [], "weak": ["dutch"], "ambiguous": []},
    "BE": {"strong": [], "weak": ["belgian"], "ambiguous": []},
    "CH": {"strong": [], "weak": ["swiss"], "ambiguous": []},
    "SE": {"strong": [], "weak": ["swedish"], "ambiguous": []},
    "NO": {"strong": [], "weak": ["norwegian"], "ambiguous": []},
    "FI": {"strong": [], "weak": ["finnish"], "ambiguous": []},
    "DK": {"strong": [], "weak": ["danish"], "ambiguous": []},
    "GR": {"strong": [], "weak": ["greek"], "ambiguous": []},
    "AT": {"strong": [], "weak": ["austrian"], "ambiguous": []},
    "CZ": {"strong": [], "weak": ["czech"], "ambiguous": []},
    "HU": {"strong": [], "weak": ["hungarian"], "ambiguous": []},
    "RO": {"strong": [], "weak": ["romanian"], "ambiguous": []},
    "IE": {"strong": [], "weak": ["irish"], "ambiguous": []},
    "PT": {"strong": [], "weak": ["portuguese"], "ambiguous": []},
    "NZ": {"strong": [], "weak": ["new zealander"], "ambiguous": []},
    "KE": {"strong": [], "weak": ["kenyan"], "ambiguous": []},
    "ET": {"strong": [], "weak": ["ethiopian"], "ambiguous": []},
    "VE": {"strong": [], "weak": ["venezuelan"], "ambiguous": []},
    "CO": {"strong": [], "weak": ["colombian"], "ambiguous": []},
    "CL": {"strong": [], "weak": ["chilean"], "ambiguous": []},
    "PE": {"strong": [], "weak": ["peruvian"], "ambiguous": []},
    "CU": {"strong": [], "weak": ["cuban"], "ambiguous": []},
    "BY": {"strong": [], "weak": ["belarusian"], "ambiguous": []},
    "KZ": {"strong": [], "weak": ["kazakh"], "ambiguous": []},
}

# (id, country or None, aliases)
CITY_DATA: list[tuple[str, str | None, list[str]]] = [
    ("KYIV", "UA", ["kyiv", "kiev", "基辅", "киев", "київ", "كييف", "キーウ", "키이우"]),
    ("MOSCOW", "RU", ["moscow", "莫斯科", "москва", "moskau", "moscou", "moscú", "モスクワ", "모스크바", "موسكو"]),
    ("GAZA", "PS", ["gaza", "gaza city", "gaza strip", "加沙", "加沙地带", "غزة", "قطاع غزة", "עזה", "ガザ", "가자"]),
    ("TEL_AVIV", "IL", ["tel aviv", "特拉维夫", "تل أبيب", "תל אביב", "テルアビブ", "텔아비브"]),
    ("JERUSALEM", None, ["jerusalem", "耶路撒冷", "القدس", "ירושלים", "エルサレム", "예루살렘"]),
    ("BEIJING", "CN", ["beijing", "北京", "пекин", "pékin", "pekín", "بكين", "北京", "베이징"]),
    ("SHANGHAI", "CN", ["shanghai", "上海", "шанхай", "changhaï", "شنغهاي", "上海", "상하이"]),
    ("TAIPEI", "TW", ["taipei", "台北", "тайбэй", "taipei", "تايبيه", "台北", "타이베이"]),
    ("HONG_KONG", "HK", ["hong kong", "香港", "гонконг", "hongkong", "هونغ كونغ", "香港", "홍콩"]),
    ("TOKYO", "JP", ["tokyo", "东京", "東京", "токио", "tokio", "طوكيو", "東京", "도쿄"]),
    ("SEOUL", "KR", ["seoul", "首尔", "ソウル", "서울", "сеул", "سيول"]),
    ("PYONGYANG", "KP", ["pyongyang", "平壤", "пхеньян", "بيونغ يانغ", "平壌", "평양"]),
    ("WASHINGTON", "US", ["washington", "washington dc", "华盛顿", "вашингтон", "واشنطن", "ワシントン", "워싱턴"]),
    ("NEW_YORK", "US", ["new york", "纽约", "нью-йорк", "nueva york", "نيويورك", "ニューヨーク", "뉴욕"]),
    ("LONDON", "GB", ["london", "伦敦", "лондон", "londres", "لندن", "ロンドン", "런던"]),
    ("PARIS", "FR", ["paris", "巴黎", "париж", "parís", "باريس", "パリ", "파리"]),
    ("BERLIN", "DE", ["berlin", "柏林", "берлин", "berlín", "berlim", "برلين", "ベルリン", "베를린"]),
    ("BRUSSELS", "BE", ["brussels", "brussel", "布鲁塞尔", "брюссель", "bruselas", "bruxelles", "بروكسل", "ブリュッセル", "브뤼셀"]),
    ("TEHRAN", "IR", ["tehran", "德黑兰", "тегеран", "teherán", "téhéran", "طهران", "テヘラン", "테헤란"]),
    ("RIYADH", "SA", ["riyadh", "利雅得", "эр-рияд", "riad", "رياض", "リヤド", "리야드"]),
    ("DUBAI", "AE", ["dubai", "迪拜", "дубай", "dubái", "دبي", "ドバイ", "두바이"]),
    ("DOHA", "QA", ["doha", "多哈", "доха", "الدوحة", "ドーハ", "도하"]),
    ("CAIRO", "EG", ["cairo", "开罗", "каир", "el cairo", "القاهرة", "カイロ", "카이로"]),
    ("ISTANBUL", "TR", ["istanbul", "伊斯坦布尔", "стамбул", "estambul", "إسطنبول", "イスタンブール", "이스탄불"]),
    ("ANKARA", "TR", ["ankara", "安卡拉", "анкара", "أنقرة", "アンカラ", "앙카라"]),
    ("NEW_DELHI", "IN", ["new delhi", "新德里", "нью-дели", "nueva delhi", "nova déli", "نيودلهي", "ニューデリー", "뉴델리"]),
    ("MUMBAI", "IN", ["mumbai", "bombay", "孟买", "мумбаи", "مومباي", "ムンバイ", "뭄바이"]),
    ("ISLAMABAD", "PK", ["islamabad", "伊斯兰堡", "исламабад", "إسلام آباد", "イスラマバード", "이슬라마바드"]),
    ("KARACHI", "PK", ["karachi", "卡拉奇", "карачи", "كراتشي", "カラチ", "카라치"]),
    ("KABUL", "AF", ["kabul", "喀布尔", "кабул", "كابول", "カブール", "카불"]),
    ("BAGHDAD", "IQ", ["baghdad", "巴格达", "багдад", "bagdad", "بغداد", "バグダッド", "바그다드"]),
    ("DAMASCUS", "SY", ["damascus", "大马士革", "дамаск", "damasco", "damas", "دمشق", "ダマスカス", "다마스쿠스"]),
    ("BEIRUT", "LB", ["beirut", "贝鲁特", "бейрут", "بيروت", "ベイルート", "베이루트"]),
    ("SANAA", "YE", ["sanaa", "萨那", "сана", "sanaá", "صنعاء", "サヌア", "사나"]),
    ("AMMAN", "JO", ["amman", "安曼", "амман", "عمّان", "アンマン", "암만"]),
    ("TBILISI", "GE", ["tbilisi", "第比利斯", "тбилиси", "تبليسي", "トビリシ", "트빌리시"]),
    ("LAGOS", "NG", ["lagos", "拉各斯", "лагос", "لاغوس", "ラゴス", "라고스"]),
    ("ABUJA", "NG", ["abuja", "阿布贾", "абуджа", "abuyá", "أبوجا", "アブジャ", "아부자"]),
    ("NAIROBI", "KE", ["nairobi", "内罗毕", "найроби", "نيروبي", "ナイロビ", "나이로비"]),
    ("ADDIS_ABABA", "ET", ["addis ababa", "亚的斯亚贝巴", "аддис-абеба", "adís abeba", "أديس أبابا", "アディスアベバ", "아디스아바바"]),
    ("JOHANNESBURG", "ZA", ["johannesburg", "约翰内斯堡", "йоханнесбург", "johannesburgo", "جوهانسبرغ", "ヨハネスブルグ", "요하네스버그"]),
    ("MEXICO_CITY", "MX", ["mexico city", "墨西哥城", "мехико", "ciudad de méxico", "مدينة مكسيكو", "メキシコシティ", "멕시코시티"]),
    ("BRASILIA", "BR", ["brasilia", "巴西利亚", "бразилиа", "برازيليا", "ブラジリア", "브라질리아"]),
    ("SAO_PAULO", "BR", ["sao paulo", "são paulo", "圣保罗", "сан-паулу", "ساو باولو", "サンパウロ", "상파울루"]),
    ("BUENOS_AIRES", "AR", ["buenos aires", "布宜诺斯艾利斯", "буэнос-айрес", "بوينس آيرس", "ブエノスアイレス", "부에노스아이레스"]),
    ("CARACAS", "VE", ["caracas", "加拉加斯", "каракас", "كاراكاس", "カラカス", "카라카스"]),
    ("BOGOTA", "CO", ["bogota", "bogotá", "波哥大", "богота", "بوغوتا", "ボゴタ", "보고타"]),
    ("JAKARTA", "ID", ["jakarta", "雅加达", "джакарта", "yakarta", "جاكرتا", "ジャカルタ", "자카르타"]),
    ("BANGKOK", "TH", ["bangkok", "曼谷", "бангкок", "بانكوك", "バンコク", "방콕"]),
    ("HANOI", "VN", ["hanoi", "河内", "ханой", "hanói", "هانوي", "ハノイ", "하노이"]),
    ("MANILA", "PH", ["manila", "马尼拉", "манила", "مانيلا", "マニラ", "마닐라"]),
    ("SINGAPORE", "SG", ["singapore", "新加坡", "сингапур", "singapur", "singapura", "سنغافورة", "シンガポール", "싱가포르"]),
    ("SYDNEY", "AU", ["sydney", "悉尼", "сидней", "sidney", "سيدني", "シドニー", "시드니"]),
    ("CANBERRA", "AU", ["canberra", "堪培拉", "канберра", "كانبرا", "キャンベラ", "캔버라"]),
    ("TORONTO", "CA", ["toronto", "多伦多", "торонто", "تورونتو", "トロント", "토론토"]),
    ("OTTAWA", "CA", ["ottawa", "渥太华", "оттава", "أوتاوا", "オタワ", "오타와"]),
    ("MADRID", "ES", ["madrid", "马德里", "мадрид", "مدريد", "マドリード", "마드리드"]),
    ("BARCELONA", "ES", ["barcelona", "巴塞罗那", "барселона", "برشلونة", "バルセロナ", "바르셀로나"]),
    ("ROME", "IT", ["rome", "roma", "罗马", "рим", "روما", "ローマ", "로마"]),
    ("MILAN", "IT", ["milan", "milano", "米兰", "милан", "ميلانو", "ミラノ", "밀라노"]),
    ("WARSAW", "PL", ["warsaw", "warszawa", "华沙", "варшава", "varsovia", "varsovie", "وارسو", "ワルシャワ", "바르샤바"]),
    ("AMSTERDAM", "NL", ["amsterdam", "阿姆斯特丹", "амстердам", "ámsterdam", "amsterdã", "أمستردام", "アムステルダム", "암스테르담"]),
    ("VIENNA", "AT", ["vienna", "wien", "维也纳", "вена", "viena", "فيينا", "ウィーン", "빈"]),
    ("STOCKHOLM", "SE", ["stockholm", "斯德哥尔摩", "стокгольм", "estocolmo", "ستوكهولم", "ストックホルム", "스톡홀름"]),
    ("OSLO", "NO", ["oslo", "奥斯陆", "осло", "أوسلو", "オスロ", "오슬로"]),
    ("HELSINKI", "FI", ["helsinki", "赫尔辛基", "хельсинки", "هلسنكي", "ヘルシンキ", "헬싱키"]),
    ("COPENHAGEN", "DK", ["copenhagen", "københavn", "哥本哈根", "копенгаген", "copenhague", "كوبنهاغن", "コペンハーゲン", "코펜하겐"]),
    ("ATHENS", "GR", ["athens", "雅典", "афины", "atenas", "athènes", "أثينا", "アテネ", "아테네"]),
    ("LISBON", "PT", ["lisbon", "lisboa", "里斯本", "лиссабон", "لشبونة", "リスボン", "리스본"]),
    ("DUBLIN", "IE", ["dublin", "都柏林", "дублин", "dublín", "دبلن", "ダブリン", "더블린"]),
    ("WELLINGTON", "NZ", ["wellington", "惠灵顿", "веллингтон", "ويلينغتون", "ウェリントン", "웰링턴"]),
    ("DHAKA", "BD", ["dhaka", "达卡", "дакка", "daca", "دكا", "ダッカ", "다카"]),
    ("TIBET", "CN", ["tibet", "西藏", "チベット", "티베트", "тибет", "التبت"]),
    ("DONBAS", "UA", ["donbas", "donbass", "顿巴斯", "Донбасс", "دونباس", "ドンバス", "돈바스"]),
    ("WEST_BANK", "PS", ["west bank", "约旦河西岸", "約旦河西岸", "الضفة الغربية", "הגדה המערבית", "ヨルダン川西岸", "서안 지구"]),
    ("CRIMEA", None, ["crimea", "克里米亚", "克里米亞", "Крым", "القرم", "クリミア", "크림반도"]),
    ("RED_SEA", None, ["red sea", "红海", "紅海", "البحر الأحمر", "Красное море", "mer rouge", "rotes meer", "mar rojo", "紅海", "홍해"]),
    ("SOUTH_CHINA_SEA", None, ["south china sea", "南海", "南シナ海", "남중국해", "Южно-Китайское море", "بحر الصين الجنوبي", "mer de Chine méridionale"]),
    ("TAIWAN_STRAIT", None, ["taiwan strait", "台湾海峡", "台灣海峽", "détroit de Taïwan", "Taiwanstraße", "タイワン海峡", "대만 해협", "Тайваньский пролив"]),
    ("KOREAN_PENINSULA", None, ["korean peninsula", "朝鲜半岛", "朝鮮半島", "Корейский полуостров", "شبه الجزيرة الكورية", "韓半島", "한반도"]),
    ("SAHEL", None, ["sahel", "萨赫勒", "薩赫勒", "Сахель", "الساحل", "サヘル", "사헬"]),
    ("BALKANS", None, ["balkans", "巴尔干", "巴爾幹", "Балканы", "البلقان", "バルカン", "발칸"]),
    ("HORN_OF_AFRICA", None, ["horn of africa", "非洲之角", "Африканский Рог", "القرن الأفريقي", "アフリカの角", "아프리카의 뿔"]),
]

PLACE_REGION = {
    "JERUSALEM": "middle_east",
    "CRIMEA": "europe",
    "RED_SEA": "middle_east",
    "SOUTH_CHINA_SEA": "southeast_asia",
    "TAIWAN_STRAIT": "east_asia",
    "KOREAN_PENINSULA": "east_asia",
    "SAHEL": "africa",
    "BALKANS": "europe",
    "HORN_OF_AFRICA": "africa",
}

ACTOR_COUNTRY = {
    "PUTIN": "RU", "ZELENSKY": "UA", "TRUMP": "US", "XI": "CN",
    "NETANYAHU": "IL", "KHAMENEI": "IR", "ERDOGAN": "TR", "MODI": "IN",
    "MACRON": "FR", "KIM_JONG_UN": "KP", "LUKASHENKO": "BY", "ORBAN": "HU",
    "MILEI": "AR", "LULA": "BR", "STARMER": "GB",
}

ACTOR_DATA: list[tuple[str, str, list[str]]] = [
    ("PUTIN", "person", ["putin", "vladimir putin", "путин", "владимир путин", "普京", "بوتين", "poutine", "プーチン", "푸틴", "पुतिन"]),
    ("ZELENSKY", "person", ["zelensky", "zelenskyy", "зеленский", "泽连斯基", "زيلينسكي", "zelensky", "ゼレンスキー", "젤렌스키", "ज़ेलेंस्की"]),
    ("TRUMP", "person", ["trump", "donald trump", "трамп", "特朗普", "ترامب", "trump", "トランプ", "트럼프", "ट्रंप"]),
    ("XI", "person", ["xi jinping", "习近平", "си цзиньпин", "شي جين بينغ", "習近平", "시진핑", "शी जिनपिंग"]),
    ("NETANYAHU", "person", ["netanyahu", "נתניהו", "内塔尼亚胡", "نتنياهو", "ネタニヤフ", "네타냐후", "नेतन्याहू"]),
    ("KHAMENEI", "person", ["khamenei", "хаменеи", "خامنه‌ای", "哈梅内伊", "ハメネイ", "하메네이"]),
    ("ERDOGAN", "person", ["erdogan", "erdoğan", "эрдоган", "埃尔多安", "أردوغان", "エルドアン", "에르도안"]),
    ("MODI", "person", ["modi", "narendra modi", "моди", "莫迪", "مودي", "モディ", "모디", "मोदी"]),
    ("MACRON", "person", ["macron", "эммануэль макрон", "马克龙", "ماكرون", "マクロン", "마크롱"]),
    ("KIM_JONG_UN", "person", ["kim jong un", "ким чен ын", "金正恩", "كيم جونغ أون", "김정은", "キム・ジョンウン"]),
    ("LUKASHENKO", "person", ["lukashenko", "лукашенко", "卢卡申科", "لوكاشينكو", "ルカシェンコ", "루카셴코"]),
    ("ORBAN", "person", ["orban", "orbán", "орбан", "欧尔班", "أوربان", "オルバーン", "오르반"]),
    ("MILEI", "person", ["milei", "милей", "米莱", "ميلي", "ミレイ", "밀레이"]),
    ("LULA", "person", ["lula", "lula da silva", "лула", "卢拉", "لولا", "ルラ", "룰라"]),
    ("LAGARDE", "person", ["lagarde", "лагард", "拉加德", "لاغارد", "ラガルド", "라가르드"]),
    ("GUTERRES", "person", ["guterres", "гуттериш", "古特雷斯", "غوتيريش", "グテーレス", "구테흐스"]),
    ("STARMER", "person", ["starmer", "стармер", "斯塔默", "ستارمر", "スターマー", "스타머"]),
    ("NATO", "org", ["nato", "нато", "北约", "北約", "الناتو", "ナトー", "나토", "otan"]),
    ("UN", "org", ["united nations", "u.n.", "оон", "联合国", "聯合國", "الأمم المتحدة", "国連", "유엔", "onu", "nazioni unite"]),
    ("EU", "org", ["european union", "евросоюз", "欧盟", "歐盟", "الاتحاد الأوروبي", "欧州連合", "유럽연합", "união europeia", "unión europea"]),
    ("HAMAS", "org", ["hamas", "хамас", "哈马斯", "哈馬斯", "حماس", "ハマス", "하마스"]),
    ("HEZBOLLAH", "org", ["hezbollah", "хезболла", "真主党", "حزب الله", "ヒズボラ", "헤즈볼라"]),
    ("HOUTHIS", "org", ["houthis", "хуситы", "胡塞武装", "الحوثيون", "フーシ派", "후티"]),
    ("TALIBAN", "org", ["taliban", "талибы", "塔利班", "طالبان", "タリバン", "탈레반"]),
    ("OPEC", "org", ["opec", "опек", "欧佩克", "أوبك", "オペック", "오펙"]),
    ("FED", "org", ["federal reserve", "фрс", "美联储", "الاحتياطي الفيدرالي", "frb", "연준"]),
    ("ECB", "org", ["european central bank", "ецб", "欧洲央行", "البنك المركزي الأوروبي", "ecb"]),
    ("IMF", "org", ["imf", "мвф", "国际货币基金组织", "صندوق النقد الدولي", "国際通貨基金"]),
    ("WHO", "org", ["world health organization", "воз", "世卫组织", "منظمة الصحة العالمية", "who"]),
    ("IAEA", "org", ["iaea", "магатэ", "国际原子能机构", "الوكالة الدولية للطاقة الذرية"]),
    ("PENTAGON", "org", ["pentagon", "пентагон", "五角大楼", "البنتاغون", "ペンタゴン", "펜타곤"]),
    ("WHITE_HOUSE", "org", ["white house", "белый дом", "白宫", "البيت الأبيض", "ホワイトハウス", "백악관"]),
    ("KREMLIN", "org", ["kremlin", "кремль", "克里姆林宫", "الكرملين", "クレムリン", "크렘린"]),
]

# (id, zh label, specific_for_cross_language, aliases)
TOPIC_DATA: list[tuple[str, str, bool, list[str]]] = [
    ("CEASEFIRE", "停火", True, ["ceasefire", "cease-fire", "truce", "停火", "休战", "停戦", "휴전", "cessez-le-feu", "alto el fuego", "waffenstillstand", "cessar-fogo", "перемирие", "وقف إطلاق النار", "آتش‌بس", "הפסקת אש", "युद्धविराम", "gencatan senjata", "ngừng bắn", "หยุดยิง", "cessate il fuoco", "перемир'я"]),
    ("ELECTION", "选举", True, ["election", "elections", "vote", "voting", "选举", "投票", "選挙", "선거", "élection", "elecciones", "wahl", "eleição", "выборы", "انتخابات", "בחירות", "चुनाव", "pemilu", "bầu cử", "การเลือกตั้ง", "elezioni", "вибори"]),
    ("PROTEST", "抗议", True, ["protest", "protests", "demonstration", "抗议", "示威", "抗議", "デモ", "시위", "manifestation", "protesta", "protest", "protesto", "протест", "احتجاج", "مظاهرة", "מחאה", "विरोध", "protes", "biểu tình", "การประท้วง", "protesta", "протест"]),
    ("SANCTIONS", "制裁", True, ["sanctions", "sanction", "制裁", "제재", "sanctions", "sanciones", "sanktionen", "sanções", "санкции", "عقوبات", "סנקציות", "प्रतिबंध", "sanksi", "trừng phạt", "การคว่ำบาตร", "sanzioni", "санкції"]),
    ("TARIFF_TRADE", "关税/贸易", True, ["tariff", "tariffs", "trade war", "关税", "贸易战", "関税", "관세", "droits de douane", "aranceles", "zoll", "tarifas", "пошлина", "رسوم جمركية", "מכס", "टैरिफ", "tarif", "thuế quan", "ภาษีศุลกากร", "dazi", "мито"]),
    ("RATES_INFLATION", "利率/通胀", True, ["inflation", "interest rate", "central bank", "通胀", "通货膨胀", "利率", "央行", "インフレ", "金利", "인플레이션", "금리", "inflación", "tasa de interés", "inflation", "zins", "inflação", "juros", "инфляция", "ставка", "تضخم", "فائدة", "אינפלציה", "महंगाई", "ब्याज दर", "inflasi", "suku bunga", "lạm phát", "lãi suất", "เงินเฟ้อ", "ดอกเบี้ย", "inflazione", "tassi", "інфляція"]),
    ("OIL_ENERGY", "石油/能源", True, ["oil price", "crude", "opec", "energy", "石油", "原油", "欧佩克", "能源", "原油", "énergie", "pétrole", "petróleo", "crudo", "öl", "erdöl", "нефть", "النفط", "نفت", "נפט", "तेल", "minyak", "dầu", "น้ำมัน", "petrolio", "нафта"]),
    ("NUCLEAR", "核问题", True, ["nuclear", "atomic", "核", "核武器", "核兵器", "핵", "nucléaire", "nuclear", "atomwaffe", "ядерный", "نووي", "גרעיני", "परमाणु", "nuklir", "hạt nhân", "นิวเคลียร์", "nucleare", "ядерний"]),
    ("AIRSTRIKE_MISSILE", "空袭/导弹", True, ["airstrike", "air strike", "missile", "drone", "空袭", "导弹", "无人机", "空爆", "ミサイル", "공습", "미사일", "frappe aérienne", "ataque aéreo", "misil", "luftangriff", "rakete", "míssil", "авиаудар", "ракета", "غارة جوية", "صاروخ", "תקיפה אווירית", "טיל", "हवाई हमला", "मिसाइल", "serangan udara", "rudal", "không kích", "tên lửa", "โจมตีทางอากาศ", "ขีปนาวุธ", "attacco aereo", "missile", "авіаудар"]),
    ("WAR_CONFLICT", "战争/冲突", False, ["war", "warfare", "conflict", "战争", "冲突", "戦争", "紛争", "전쟁", "분쟁", "guerre", "conflit", "guerra", "conflicto", "krieg", "konflikt", "война", "конфликт", "حرب", "صراع", "מלחמה", "युद्ध", "संघर्ष", "perang", "konflik", "chiến tranh", "xung đột", "สงคราม", "guerra", "conflitto", "війна"]),
    ("HOSTAGE", "人质", True, ["hostage", "hostages", "人质", "人質", "인질", "otage", "rehén", "geisel", "refém", "заложник", "رهينة", "חטוף", "बंधक", "sandera", "con tin", "ตัวประกัน", "ostaggio", "заручник"]),
    ("EARTHQUAKE", "地震", True, ["earthquake", "quake", "地震", "地震", "地震", "지진", "séisme", "terremoto", "erdbeben", "terremoto", "землетрясение", "زلزال", "רעידת אדמה", "भूकंप", "gempa", "động đất", "แผ่นดินไหว", "terremoto", "землетрус"]),
    ("FLOOD_TYPHOON", "洪水/台风", True, ["flood", "floods", "typhoon", "hurricane", "洪水", "台风", "洪水", "台風", "홍수", "태풍", "inondation", "typhon", "inundación", "tifón", "überschwemmung", "taifun", "enchente", "tufão", "наводнение", "тайфун", "فيضان", "إعصار", "שיטפון", "बाढ़", "तूफान", "banjir", "topan", "lũ lụt", "bão", "น้ำท่วม", "ไต้ฝุ่น", "alluvione", "tifone", "повінь"]),
    ("SUMMIT_DIPLOMACY", "峰会/外交", True, ["summit", "diplomacy", "talks", "峰会", "外交", "首脳会談", "정상회담", "sommet", "négociations", "cumbre", "negociaciones", "gipfel", "verhandlungen", "cúpula", "negociações", "саммит", "переговоры", "قمة", "مفاوضات", "פסגה", "शिखर सम्मेलन", "ktt", "hội nghị thượng đỉnh", "การประชุมสุดยอด", "vertice", "negoziati", "саміт"]),
    ("AI_CHIPS", "AI/芯片", True, ["artificial intelligence", "ai", "chip", "chips", "semiconductor", "人工智能", "芯片", "半导体", "半導体", "인공지능", "반도체", "intelligence artificielle", "puce", "semiconducteur", "inteligencia artificial", "chip", "künstliche intelligenz", "halbleiter", "inteligência artificial", "semicondutor", "искусственный интеллект", "чип", "полупроводник", "ذكاء اصطناعي", "شريحة", "בינה מלאכותית", "कृत्रिम बुद्धिमत्ता", "चिप", "kecerdasan buatan", "trí tuệ nhân tạo", "ชิป", "intelligenza artificiale", "штучний інтелект", "чіп"]),
]


REGION_DATA: list[tuple[str, str, list[str]]] = [
    ("east_asia", "东亚", ["east asia", "东亚", "東亞", "شرق آسيا", "Восточная Азия", "asia oriental", "asie de l'est", "ostasien", "東アジア", "동아시아", "شرق آسیا", "מזרח אסיה", "पूर्वी एशिया", "asia timur", "đông á", "เอเชียตะวันออก", "asia orientale", "східна азія"]),
    ("southeast_asia", "东南亚", ["southeast asia", "south-east asia", "东南亚", "東南亞", "جنوب شرق آسيا", "Юго-Восточная Азия", "sudeste asiático", "asie du sud-est", "südostasien", "東南アジア", "동남아시아", "جنوب شرق آسیا", "דרום-מזרח אסיה", "दक्षिण-पूर्व एशिया", "asia tenggara", "đông nam á", "เอเชียตะวันออกเฉียงใต้", "sud-est asiatico", "південно-східна азія"]),
    ("south_asia", "南亚", ["south asia", "南亚", "南亞", "جنوب آسيا", "Южная Азия", "asia meridional", "asie du sud", "südasien", "南アジア", "남아시아", "جنوب آسیا", "דרום אסיה", "दक्षिण एशिया", "asia selatan", "nam á", "เอเชียใต้", "asia meridionale", "південна азія"]),
    ("central_asia", "中亚", ["central asia", "中亚", "中亞", "آسيا الوسطى", "Центральная Азия", "asia central", "asie centrale", "zentralasien", "中央アジア", "중앙아시아", "آسیای مرکزی", "מרכז אסיה", "मध्य एशिया", "asia tengah", "trung á", "เอเชียกลาง", "asia centrale", "центральна азія"]),
    ("middle_east", "中东", ["middle east", "中东", "中東", "الشرق الأوسط", "Ближний Восток", "oriente medio", "moyen-orient", "naher osten", "中東", "중동", "خاورمیانه", "המזרח התיכון", "मध्य पूर्व", "timur tengah", "trung đông", "ตะวันออกกลาง", "medio oriente", "близький схід"]),
    ("europe", "欧洲", ["europe", "欧洲", "歐洲", "أوروبا", "Европа", "europa", "europe", "europa", "ヨーロッパ", "유럽", "اروپا", "אירופה", "यूरोप", "eropa", "châu âu", "ยุโรป", "europa", "європа"]),
    ("north_america", "北美", ["north america", "北美", "北美洲", "أمريكا الشمالية", "Северная Америка", "américa del norte", "amérique du nord", "nordamerika", "北米", "북미", "آمریکای شمالی", "אמריקה הצפונית", "उत्तरी अमेरिका", "amerika utara", "bắc mỹ", "อเมริกาเหนือ", "nord america", "північна америка"]),
    ("latin_america", "拉美", ["latin america", "拉美", "拉丁美洲", "أمريكا اللاتينية", "Латинская Америка", "américa latina", "amérique latine", "lateinamerika", "ラテンアメリカ", "중남미", "آمریکای لاتین", "אמריקה הלטינית", "लैटिन अमेरिका", "amerika latin", "mỹ latinh", "ลาตินอเมริกา", "america latina", "латинська америка"]),
    ("africa", "非洲", ["africa", "非洲", "أفريقيا", "Африка", "áfrica", "afrique", "afrika", "アフリカ", "아프리카", "آفریقا", "אפריקה", "अफ्रीका", "afrika", "châu phi", "แอฟริกา", "africa", "африка"]),
    ("oceania", "大洋洲", ["oceania", "大洋洲", "أوقيانوسيا", "Океания", "oceanía", "océanie", "ozeanien", "オセアニア", "오세아니아", "اقیانوسیه", "אוקיאניה", "ओशिनिया", "oseania", "châu đại dương", "โอเชียเนีย", "oceania", "океанія"]),
]

TOPIC_EXTRA = {
    "CEASEFIRE": ["ateşkes", "barış anlaşması"],
    "ELECTION": ["seçim", "seçimler"],
    "SANCTIONS": ["yaptırım", "yaptırımlar"],
    "TARIFF_TRADE": ["tarife", "ticaret savaşı"],
    "RATES_INFLATION": ["enflasyon", "faiz", "تورم", "نرخ بهره"],
    "OIL_ENERGY": ["petrol", "enerji", "نفت"],
    "NUCLEAR": ["nükleer", "هسته‌ای"],
    "AIRSTRIKE_MISSILE": ["füze", "hava saldırısı", "پهپاد"],
    "WAR_CONFLICT": ["savaş"],
    "HOSTAGE": ["rehine"],
    "EARTHQUAKE": ["deprem", "زلزله"],
    "FLOOD_TYPHOON": ["sel", "tayfun", "سیل"],
    "SUMMIT_DIPLOMACY": ["zirve", "نشست سران"],
    "AI_CHIPS": ["yapay zeka", "çip", "هوش مصنوعی", "تراشه"],
}
for _topic in TOPIC_DATA:
    _topic[3].extend(TOPIC_EXTRA.get(_topic[0], []))


def norm(value: str) -> str:
    value = re.sub(r"\s+", " ", value.replace(" ", " ")).strip()
    return value


def main() -> None:
    countries: dict[str, dict] = {}
    for iso, info in COUNTRIES.items():
        aliases: set[str] = set()
        if info.get("name_en"):
            aliases.add(info["name_en"])
        if info.get("name_zh"):
            aliases.add(info["name_zh"])
        for locale in LOCALES:
            name = LOCALE_OBJECTS[locale].territories.get(iso)
            if name:
                aliases.add(name)
        extra = COUNTRY_EXTRA.get(iso, {})
        for value in extra.get("strong", []):
            aliases.add(value)
        weak = set(extra.get("weak", []))
        ambiguous = set(extra.get("ambiguous", []))
        cleaned = set()
        for alias in aliases:
            alias = norm(alias).lower() if any(ord(ch) < 128 for ch in alias) else norm(alias)
            if not alias or alias in EXCLUDED:
                continue
            if any(c.isalpha() for c in alias):
                cleaned.add(alias)
        weak = {norm(w).lower() for w in weak if w}
        ambiguous = {norm(a).lower() for a in ambiguous if a}
        strong = cleaned - weak - ambiguous
        if iso == "TW":
            strong.add("中国台湾")
        if iso == "HK":
            strong.add("中国香港")
        if iso == "MO":
            strong.add("中国澳门")
        countries[iso] = {
            "region": info.get("region", "other"),
            "label_zh": info.get("name_zh", iso),
            "aliases": sorted(strong, key=lambda x: (-len(x), x)),
            "weak_aliases": sorted(weak - ambiguous, key=lambda x: (-len(x), x)),
            "ambiguous_aliases": sorted(ambiguous, key=lambda x: (-len(x), x)),
        }

    places = []
    for place_id, country, names in CITY_DATA:
        region = (
            COUNTRIES.get(country or "", {}).get("region")
            or PLACE_REGION.get(place_id)
            or "other"
        )
        places.append(
            {
                "id": place_id,
                "country": country,
                "region": region,
                "label_zh": next(
                    (n for n in names if re.search(r"[一-鿿]", n)),
                    COUNTRIES.get(country or "", {}).get("name_zh", place_id),
                ),
                "aliases": sorted(
                    {norm(n).lower() if any(ord(c) < 128 for c in n) else norm(n) for n in names},
                    key=lambda x: (-len(x), x),
                ),
            }
        )

    actors = [
        {"id": actor_id, "kind": kind, "country": ACTOR_COUNTRY.get(actor_id), "aliases": sorted(
            {norm(n).lower() if any(ord(c) < 128 for c in n) else norm(n) for n in names},
            key=lambda x: (-len(x), x),
        )}
        for actor_id, kind, names in ACTOR_DATA
    ]
    topics = [
        {
            "id": topic_id,
            "label_zh": label,
            "specific": specific,
            "aliases": sorted(
                {norm(n).lower() if any(ord(c) < 128 for c in n) else norm(n) for n in names},
                key=lambda x: (-len(x), x),
            ),
        }
        for topic_id, label, specific, names in TOPIC_DATA
    ]

    out = {
        "locales": LOCALES,
        "countries": countries,
        "places": places,
        "actors": actors,
        "topics": topics,
        "regions": [
            {"id": region_id, "label_zh": label, "aliases": sorted(
                {norm(n).lower() if any(ord(c) < 128 for c in n) else norm(n) for n in names},
                key=lambda x: (-len(x), x),
            )}
            for region_id, label, names in REGION_DATA
        ],
    }
    path = ROOT / "config" / "gazetteer.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    print(
        f"countries={len(countries)} places={len(places)} actors={len(actors)} "
        f"topics={len(topics)} size={path.stat().st_size/1024:.1f}KB"
    )


if __name__ == "__main__":
    main()
