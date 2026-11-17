from __future__ import annotations

import json
import sys
import tempfile
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from brazil import _normalise, _url, fetch_results  # noqa: E402
from classifier import Classifier  # noqa: E402
from contenttype import ContentTypeClassifier  # noqa: E402
from db import (  # noqa: E402
    connect, count_articles, facet_counts, init_db, insert_articles, kpis,
    query_articles, search_summary, unlocated_count,
)
from elections import (  # noqa: E402
    default_election, fetch_election_results, get_election, list_elections,
)
from eventgraph import EventGraph  # noqa: E402
import query_expand as query_expand_module  # noqa: E402
from query_expand import terms_for_variant  # noqa: E402
import translate as translate_module  # noqa: E402
from roles import choose_primary, classify_roles, statement_score  # noqa: E402
from ingest import build_article, parse_feed, parse_polymarket_markets  # noqa: E402
from quality import QualityFilter  # noqa: E402
from taxonomy import base_language, country_from_url, region_of, script_matches  # noqa: E402
from textutil import (  # noqa: E402
    _corroboration,
    canonical_url,
    cluster_articles,
    diversify,
    fingerprint,
    tokenize,
)


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT / "config" / "feeds.json").read_text(encoding="utf-8"))
        cls.feeds = cls.config["feeds"]

    def test_all_feeds_are_enabled_direct_specialists(self):
        self.assertEqual(len(self.feeds), 111)
        self.assertTrue(all(feed["enabled"] for feed in self.feeds))
        self.assertTrue(all(feed["kind"] == "direct" for feed in self.feeds))
        self.assertTrue(all("google." not in feed["url"].lower() for feed in self.feeds))
        ids = {feed["id"] for feed in self.feeds}
        self.assertEqual(len(ids), len(self.feeds))
        self.assertTrue(all(feed.get("beat") for feed in self.feeds))
        self.assertFalse({"meduza", "rbc-ru", "hankyung"} & ids, "general feeds must stay out")
        polymarket = next(feed for feed in self.feeds if feed["id"] == "polymarket")
        self.assertEqual(polymarket["connector"], "polymarket")
        self.assertEqual(polymarket["ownership"], "market")
        self.assertGreaterEqual(len({feed["country"] for feed in self.feeds}), 29)
        self.assertGreaterEqual(len({feed["beat"] for feed in self.feeds}), 50)

    def test_language_and_region_coverage(self):
        languages = Counter(feed["language"] for feed in self.feeds)
        expected = {
            "en", "zh", "zh-Hant", "ja", "ko", "ru", "uk", "de", "fr", "es",
            "pt", "it", "tr", "ar", "he", "hi", "vi",
        }
        self.assertEqual(set(languages), expected)
        self.assertTrue(all(languages[lang] >= 1 for lang in expected))
        countries = {feed["country"] for feed in self.feeds}
        for country in ("US", "GB", "CN", "JP", "KR", "RU", "UA", "DE", "FR", "ES", "BR", "IN", "ZA", "IL", "VN"):
            self.assertIn(country, countries)

    def test_sector_coverage(self):
        beats = {feed["beat"] for feed in self.feeds}
        for beat in ("finance", "defense", "tech", "china-tech", "climate", "health", "science", "energy", "law", "eu-policy", "prediction-markets"):
            self.assertIn(beat, beats, beat)
        categories = Counter(feed["category_hint"] for feed in self.feeds)
        self.assertGreaterEqual(categories["economy"], 40)
        self.assertGreaterEqual(categories["politics"], 10)
        self.assertGreaterEqual(categories["military"], 8)


class ClassifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = Classifier()

    def check(self, title, language, expected):
        result = self.c.classify(title, "", language)
        self.assertEqual(result["category"], expected, msg=f"{title} -> {result}")

    def test_english(self):
        self.check("Fed cuts interest rates as inflation cools", "en", "economy")
        self.check("Israel and Hamas agree to ceasefire in Gaza", "en", "military")
        self.check("Venezuelans call for elections in first national protest", "en", "politics")

    def test_chinese(self):
        self.check("中国宣布对进口电动汽车加征关税", "zh", "economy")
        self.check("以色列与哈马斯达成停火协议", "zh", "military")
        self.check("全国人大常委会审议多项法律草案", "zh", "politics")

    def test_traditional_chinese(self):
        self.check("美國經濟在特朗普治下表現如何", "zh-Hant", "economy")
        self.check("俄羅斯導彈襲擊烏克蘭城市", "zh-Hant", "military")
        self.check("台灣舉行地方選舉投票", "zh-Hant", "politics")

    def test_generic_market_is_not_enough(self):
        result = self.c.classify(
            "Glass bottle thrown toward Netanyahu's motorcade while passing Mahaneh Yehuda market",
            "",
            "en",
        )
        self.assertNotEqual(result["category"], "economy")

    def test_arabic(self):
        self.check("أوبك تخفض إنتاج النفط مع تراجع الأسعار", "ar", "economy")
        self.check("الجيش يشن هجوما واسعا على مواقع المسلحين", "ar", "military")


class ContentTypeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = ContentTypeClassifier()

    def test_opinion(self):
        self.assertEqual(self.c.classify("Editorial: Why the West must act", "", "", [], "en")["content_type"], "opinion")
        self.assertEqual(self.c.classify("社论：为什么必须改革", "", "", [], "zh")["content_type"], "opinion")
        self.assertEqual(self.c.classify("رأي: لماذا يجب وقف الحرب", "", "", [], "ar")["content_type"], "opinion")

    def test_analysis(self):
        self.assertEqual(self.c.classify("Analysis: What the ceasefire means", "", "", [], "en")["content_type"], "analysis")
        self.assertEqual(self.c.classify("分析：停火协议意味着什么", "", "", [], "zh")["content_type"], "analysis")
        self.assertEqual(self.c.classify("تحليل: ماذا يعني اتفاق وقف إطلاق النار", "", "", [], "ar")["content_type"], "analysis")

    def test_hard_news(self):
        self.assertEqual(self.c.classify("Police say three people killed in explosion", "", "", [], "en")["content_type"], "hard")
        self.assertEqual(self.c.classify("警方称爆炸造成三人死亡", "", "", [], "zh")["content_type"], "hard")

    def test_url_section(self):
        result = self.c.classify("A better way to run the economy", "", "https://example.com/opinion/a-better-way", [], "en")
        self.assertEqual(result["content_type"], "opinion")

    def test_source_hint(self):
        result = self.c.classify("A short note on Europe", "", "", [], "en", "opinion")
        self.assertEqual(result["content_type"], "opinion")


    def test_feed_hint_can_force_hard(self):
        result = self.c.classify("Will the Fed cut rates?", "", "", [], "en", "hard")
        self.assertEqual(result["content_type"], "hard")


class QualityFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.q = QualityFilter()

    def assert_junk(self, title, feed_id, language, summary="", url="https://example.com/a"):
        self.assertIsNotNone(
            self.q.match(title, summary, url, language, feed_id),
            msg=f"expected filtered: {title}",
        )

    def assert_ok(self, title, feed_id, language, summary="", url="https://example.com/a"):
        self.assertIsNone(
            self.q.match(title, summary, url, language, feed_id),
            msg=f"expected kept: {title}",
        )

    def test_indonesian_clickbait_and_real_news(self):
        self.assert_junk(
            "Warren Buffett Ungkap 3L Penyebab Orang Kaya Bangkrut Sekejap",
            "cnbc-indonesia", "id",
            summary="Buffett menyebut minuman keras, wanita, dan utang.",
        )
        self.assert_junk(
            "6 Makanan Paling Cepat dan Ampuh Hilangkan Perut Buncit",
            "cnbc-indonesia", "id",
        )
        self.assert_junk(
            "Harga Emas Galeri 24-UBS-Antam dan Antam Retro Hari Ini 16 November 2026",
            "cnbc-indonesia", "id",
        )
        self.assert_junk(
            "Daftar Bunga Deposito Terbaru BRI, Mandiri dan BNI per 16 November 2026",
            "cnbc-indonesia", "id",
        )
        self.assert_ok(
            "Prabowo: 70% Hasil Tambang Harus Dinikmati Negara-Kuasai Sahamnya!",
            "cnbc-indonesia", "id",
        )
        self.assert_ok(
            "Fadli Zon Respons Isu Endorse RANS Rp14,7 M, Sebut Promosi Kebudayaan",
            "cnbc-indonesia", "id",
        )

    def test_persian_health_and_service_content(self):
        self.assert_junk(
            "با خوردن این 5 میوه، دور چاقی را خط بکشید",
            "donya-eqtesad", "fa",
        )
        self.assert_junk(
            "این روغن خوراکی، مرگ ناشی از زوال عقل را کم می کند!",
            "donya-eqtesad", "fa",
        )
        self.assert_junk(
            "هواشناسی استان مازندران امروز دوشنبه ۲۵ آبان ۱۴۰۵ / بارش سیل‌آسا در راه است",
            "eghtesadonline", "fa",
        )
        self.assert_ok(
            "امکان پیشگیری و تعویق ۹۰درصد موارد ابتلا به دیابت نوع ۲ با تشخیص زودهنگام",
            "donya-eqtesad", "fa",
        )
        self.assert_ok(
            "برخورد تعزیراتی، درمان گرانی است؟",
            "donya-eqtesad", "fa",
        )
        self.assert_ok(
            "اطلاعیه سپاه درباره احتمال شنیده شدن صدای انفجار در این منطقه تهران",
            "donya-eqtesad", "fa",
        )

    def test_korean_press_board_and_thai_horoscope(self):
        self.assert_junk(
            "[게시판] 카카오뱅크, 다이슨 할인·경품 추첨 '한달적금' 출시",
            "yonhap-economy", "ko",
        )
        self.assert_ok(
            "코스피, 젠슨황 파장속 보합권 등락…코스닥 1%대↓(종합)",
            "yonhap-economy", "ko",
        )
        self.assert_junk(
            "설화수, '퍼펙팅 틴티드 립오일' 출시…\"입술 탄력·주름 개선\"",
            "yonhap-economy", "ko",
        )
        self.assert_ok(
            "SK바이오팜, 뇌전증 치료제 '세노바메이트' 일본 출시",
            "yonhap-economy", "ko",
        )
        self.assert_junk(
            "ดวงรายสัปดาห์ 15-21 พฤศจิกายน 2569",
            "prachachat", "th",
        )

    def test_rescue_terms_do_not_match_url_slugs(self):
        title = (
            "存在感が薄い\"非モテ\"でも\"モテ系\"に変わる…コミュニケーション研究の"
            "第一人者が教える｢視線｣と｢観察力｣のコツ | ライフ | 東洋経済オンライン"
        )
        self.assert_junk(
            title, "toyo-keizai", "ja",
            summary="科学的に裏付けられた視線術を解説します。",
            url="https://toyokeizai.net/articles/-/963339",
        )

    def test_chinese_pr_event(self):
        self.assert_junk(
            "“中国文化 世界品牌”——2026杰出品牌营销分享会在京举行",
            "eeo", "zh",
        )
        self.assert_ok(
            "中国宣布对进口电动汽车加征关税",
            "eeo", "zh",
        )


class CorroborationTests(unittest.TestCase):
    def article(self, article_id, publisher, country, language, content_type, title):
        return {
            "id": article_id, "title": title, "publisher": publisher, "country": country,
            "language": language, "content_type": content_type,
            "published_at": "2026-10-23T00:00:00Z", "ownership": "private",
            "event_entities": [], "event_topics": [],
        }

    def test_strong_cross_check(self):
        members = [
            self.article("1", "A", "GB", "en", "hard", "Tibet earthquake kills 16"),
            self.article("2", "B", "US", "en", "hard", "Tibet quake deaths rise to 16"),
            self.article("3", "C", "FR", "fr", "hard", "Le seisme au Tibet fait 16 morts"),
        ]
        result = _corroboration(members)
        self.assertEqual(result["level"], "strong")
        self.assertEqual(result["publishers"], 3)
        self.assertEqual(result["countries"], 3)
        self.assertEqual(result["languages"], 2)
        self.assertEqual(result["hard"], 3)

    def test_single_source(self):
        result = _corroboration([self.article("1", "A", "US", "en", "hard", "A headline")])
        self.assertEqual(result["level"], "single")
        self.assertIn("仅 1 家媒体", result["notes"][0])

    def test_opinion_only(self):
        members = [
            self.article("1", "A", "US", "en", "opinion", "Why this policy is wrong"),
            self.article("2", "B", "GB", "en", "analysis", "What the policy means"),
        ]
        result = _corroboration(members)
        self.assertEqual(result["level"], "opinion")
        self.assertEqual(result["hard"], 0)

    def test_state_media_note(self):
        a = self.article("1", "A", "RU", "en", "hard", "Statement one")
        b = self.article("2", "B", "RU", "en", "hard", "Statement two")
        a["ownership"] = "state"
        b["ownership"] = "state_funded"
        result = _corroboration([a, b])
        self.assertTrue(any("国有" in note for note in result["notes"]))

    def test_many_same_country_is_not_strong(self):
        members = [
            self.article(str(i), f"P{i}", "US", "en", "hard", f"Headline {i}")
            for i in range(1, 6)
        ]
        result = _corroboration(members)
        self.assertEqual(result["publishers"], 5)
        self.assertEqual(result["level"], "multi")

    def test_many_publishers_across_countries_is_strong(self):
        members = [
            self.article(str(i), f"P{i}", "US" if i < 4 else "GB", "en", "hard", f"Headline {i}")
            for i in range(1, 6)
        ]
        result = _corroboration(members)
        self.assertEqual(result["publishers"], 5)
        self.assertEqual(result["level"], "strong")


class FreeTranslationTests(unittest.TestCase):
    def test_external_libre_is_blocked_in_free_mode(self):
        old = (
            translate_module.TRANSLATE_FREE_ONLY,
            translate_module.TRANSLATE_PROVIDER,
            translate_module.LIBRE_URL,
            translate_module.TRANSLATE_FALLBACK,
        )
        try:
            translate_module.TRANSLATE_FREE_ONLY = True
            translate_module.TRANSLATE_PROVIDER = "auto"
            translate_module.LIBRE_URL = "https://paid-translate.example.com"
            translate_module.TRANSLATE_FALLBACK = True
            names = [name for name, _ in translate_module._chain()]
            self.assertNotIn("libre", names)
            self.assertIn("ollama", names)
            self.assertIn("mymemory", names)
            translate_module.TRANSLATE_PROVIDER = "libre"
            self.assertEqual(translate_module._chain(), [])
        finally:
            (
                translate_module.TRANSLATE_FREE_ONLY,
                translate_module.TRANSLATE_PROVIDER,
                translate_module.LIBRE_URL,
                translate_module.TRANSLATE_FALLBACK,
            ) = old

    def test_local_libre_is_allowed(self):
        old_url = translate_module.LIBRE_URL
        old_provider = translate_module.TRANSLATE_PROVIDER
        old_free = translate_module.TRANSLATE_FREE_ONLY
        try:
            translate_module.TRANSLATE_FREE_ONLY = True
            translate_module.TRANSLATE_PROVIDER = "auto"
            translate_module.LIBRE_URL = "http://127.0.0.1:5000"
            self.assertEqual([name for name, _ in translate_module._chain()], ["libre", "mymemory", "ollama"])
            self.assertTrue(translate_module._is_local_url("http://192.168.1.10:5000"))
            self.assertFalse(translate_module._is_local_url("https://translate.example.com"))
        finally:
            translate_module.LIBRE_URL = old_url
            translate_module.TRANSLATE_PROVIDER = old_provider
            translate_module.TRANSLATE_FREE_ONLY = old_free


class RoleTests(unittest.TestCase):
    def member(self, title, publisher, published_at, feed_id="direct", summary=""):
        return {
            "title": title, "publisher": publisher, "published_at": published_at,
            "feed_id": feed_id, "content_type": "hard", "summary": summary,
        }

    def test_primary_skips_statement_and_prefers_direct(self):
        original = self.member(
            "US banks block third-party AI agents", "Reuters", "2026-10-22T21:00:00Z"
        )
        statement = self.member(
            "White House issues statement on AI agents", "White House",
            "2026-10-22T22:00:00Z", summary="Press statement",
        )
        repost = self.member(
            "US banks block third-party AI agents", "Copy News",
            "2026-10-22T20:00:00Z", feed_id="gnews-us",
        )
        angle = self.member(
            "Banks tighten access for AI agents", "Other News",
            "2026-10-22T19:00:00Z",
        )
        members = [original, statement, repost, angle]
        lead = choose_primary(members)
        self.assertIs(lead, original)
        roles = classify_roles(members, lead)
        self.assertEqual(roles[id(original)], "original")
        self.assertEqual(roles[id(statement)], "statement")
        self.assertEqual(roles[id(repost)], "repost")
        self.assertEqual(roles[id(angle)], "angle")

    def test_single_aggregator_item_is_still_original(self):
        member = self.member(
            "A unique report", "Example", "2026-10-22T21:00:00Z", feed_id="gnews-us"
        )
        lead = choose_primary([member])
        self.assertIs(lead, member)
        self.assertEqual(classify_roles([member], lead)[id(member)], "original")

    def test_cluster_assigns_branch_roles(self):
        def article(article_id, publisher, published_at):
            return {
                "id": article_id, "title": "US banks block third-party AI agents",
                "summary": "", "publisher": publisher, "language": "en",
                "content_type": "hard", "published_at": published_at,
                "feed_id": "direct", "event_entities": ["PLACE:US"],
                "event_topics": [{"id": "AI_CHIPS", "label": "AI/芯片"}],
                "event_places": [], "url": f"https://example.com/{article_id}",
            }
        items = [
            article("1", "Publisher A", "2026-10-22T20:00:00Z"),
            article("2", "Publisher B", "2026-10-22T21:00:00Z"),
        ]
        cluster_articles(items)
        lead = next(item for item in items if item.get("coverage", 1) > 1)
        self.assertEqual(lead["role"], "original")
        self.assertEqual(lead["coverage_groups"].get("repost"), 1)
        self.assertEqual(lead["related"][0]["role"], "repost")

    def test_family_statement_is_not_government_statement(self):
        family = self.member(
            "Actor dies, family says in a statement", "CNA",
            "2026-10-22T21:00:00Z", summary="The family issued a statement.",
        )
        self.assertEqual(statement_score(family), 1)
        self.assertEqual(classify_roles([family], family)[id(family)], "original")


class QueryExpansionTests(unittest.TestCase):
    def test_terms_for_variant(self):
        chinese = terms_for_variant("西藏地震", "zh")
        self.assertIn("西藏", chinese)
        self.assertIn("地震", chinese)
        russian = terms_for_variant("Землетрясение в Тибете", "ru")
        self.assertTrue(any(term.startswith("Землет") for term in russian))
        self.assertTrue(any(term.startswith("Тибе") for term in russian))
        english = terms_for_variant("Tibet earthquake", "en")
        self.assertIn("Tibet", english)
        self.assertTrue(any(term.startswith("earthq") for term in english))


class BrazilResultsTests(unittest.TestCase):
    def test_tse_url_uses_runoff_election_code(self):
        self.assertEqual(
            _url("br"),
            "https://resultados.tse.jus.br/oficial/ele2026/6258/dados/br/"
            "br-c0001-e006258-u.json",
        )
        self.assertIn("/mg/mg-c0001-e006258-u.json", _url("mg"))

    def test_normalise_orders_candidates_and_reads_progress(self):
        payload = {
            "dg": "25/10/2026",
            "hg": "17:05:00",
            "and": "n",
            "carg": [{
                "agr": [
                    {"par": [{"sg": "PT", "cand": [{
                        "nmu": "LULA", "nm": "LUIZ INACIO LULA DA SILVA",
                        "n": "13", "vap": "40", "pvap": "40,00", "st": "",
                    }]}]},
                    {"par": [{"sg": "PL", "cand": [{
                        "nmu": "FLAVIO BOLSONARO", "nm": "FLAVIO NANTES BOLSONARO",
                        "n": "22", "vap": "60", "pvap": "60,00", "st": "",
                    }]}]},
                ],
            }],
            "s": {"st": "1000", "ts": "2000", "pst": "50,00"},
            "e": {"est": "10000", "te": "100000", "a": "500", "pa": "5,00"},
            "v": {"tvn": "100", "tv": "110", "vb": "5", "vn": "5"},
        }
        data = _normalise(payload, "br")
        self.assertEqual(data["counted_pct"], 50.0)
        self.assertEqual(data["counted_sections"], 1000)
        self.assertEqual(data["total_sections"], 2000)
        self.assertEqual(data["valid_votes"], 100)
        self.assertEqual(data["abstention_pct"], 5.0)
        self.assertEqual([c["name"] for c in data["candidates"]],
                         ["FLAVIO BOLSONARO", "LULA"])
        self.assertEqual(data["candidates"][0]["votes"], 60)
        self.assertEqual(data["candidates"][0]["pct"], 60.0)

    def test_unknown_scope_is_rejected_without_network(self):
        self.assertFalse(fetch_results("zz")["ok"])


class AliasExpansionTests(unittest.TestCase):
    def test_known_actor_expands_offline(self):
        old = query_expand_module.SEARCH_TRANSLATE
        try:
            query_expand_module.SEARCH_TRANSLATE = False
            filters = {"q": "普京", "hours": 24}
            meta = query_expand_module.expand_search(filters)
            texts = {variant["text"] for variant in filters["_variants"]}
            self.assertTrue(any("putin" in text.casefold() for text in texts), texts)
            self.assertTrue(any("путин" in text.casefold() for text in texts), texts)
            self.assertGreater(meta["alias_count"], 0)
            self.assertIn("PUTIN", meta["alias_expanded"])
        finally:
            query_expand_module.SEARCH_TRANSLATE = old

    def test_alias_variants_are_not_duplicated(self):
        old = query_expand_module.SEARCH_TRANSLATE
        try:
            query_expand_module.SEARCH_TRANSLATE = False
            filters = {"q": "Putin", "hours": 24}
            query_expand_module.expand_search(filters)
            texts = [variant["text"].casefold() for variant in filters["_variants"]]
            self.assertEqual(len(texts), len(set(texts)))
        finally:
            query_expand_module.SEARCH_TRANSLATE = old


class EventGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = EventGraph()

    def test_city_and_country(self):
        result = self.g.extract("Russian missile strike hits Kyiv, Ukraine says")
        self.assertEqual(result["event_country"], "UA")
        self.assertEqual(result["event_region"], "europe")
        self.assertIn("AIRSTRIKE_MISSILE", {t["id"] for t in result["event_topics"]})

    def test_gaza_is_palestine(self):
        result = self.g.extract("Israel and Hamas agree to ceasefire in Gaza")
        self.assertEqual(result["event_country"], "PS")
        self.assertEqual(result["event_region"], "middle_east")

    def test_region_only(self):
        result = self.g.extract("Tensions rise across the Middle East")
        self.assertIsNone(result["event_country"])
        self.assertEqual(result["event_region"], "middle_east")

    def test_ambiguous_country_needs_caps(self):
        self.assertIsNone(self.g.extract("turkey prices rise before the holiday")["event_country"])
        self.assertEqual(self.g.extract("Turkey condemns the strike")["event_country"], "TR")

    def test_us_abbreviation(self):
        result = self.g.extract("SK Hynix abandons plan for US unit's IPO")
        self.assertEqual(result["event_country"], "US")


class CrossLanguageClusterTests(unittest.TestCase):
    def make(self, article_id, title, language, entities, topics, hours_ago=0):
        from datetime import datetime, timedelta, timezone
        ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "id": article_id, "title": title, "language": language, "publisher": "P" + article_id,
            "published_at": ts, "event_entities": entities,
            "event_topics": [{"id": t, "label": t} for t in topics],
        }

    def test_cross_language_event_merges(self):
        items = [
            self.make("1", "Israel and Hamas agree to ceasefire in Gaza", "en",
                      ["PLACE:PS", "CITY:GAZA", "ORG:HAMAS"], ["CEASEFIRE"]),
            self.make("2", "إسرائيل وحماس تتفقان على وقف إطلاق النار في غزة", "ar",
                      ["PLACE:PS", "CITY:GAZA", "ORG:HAMAS"], ["CEASEFIRE"]),
        ]
        cluster_articles(items)
        self.assertEqual(items[0]["coverage"], 2)
        self.assertTrue(items[0]["cross_language"])
        self.assertEqual(items[0]["coverage_languages"], 2)
        self.assertEqual(items[0]["member_ids"], ["2"])

    def test_broad_topic_does_not_merge(self):
        items = [
            self.make("1", "Trump backs a candidate in Ohio", "en",
                      ["PLACE:US", "ACTOR:TRUMP"], ["ELECTION"]),
            self.make("2", "ترامب يدعم مرشحا في أوهايو", "ar",
                      ["PLACE:US", "ACTOR:TRUMP"], ["ELECTION"]),
        ]
        cluster_articles(items)
        self.assertEqual(items[0]["coverage"], 1)
        self.assertFalse(items[0]["cross_language"])

    def test_city_and_earthquake_merge(self):
        items = [
            self.make("1", "Tibet earthquake kills 16", "en",
                      ["PLACE:CN", "CITY:TIBET"], ["EARTHQUAKE"]),
            self.make("2", "西藏发生7级地震，至少16人死亡", "zh",
                      ["PLACE:CN", "CITY:TIBET"], ["EARTHQUAKE"]),
        ]
        cluster_articles(items)
        self.assertEqual(items[0]["coverage"], 2)

    def test_time_window(self):
        items = [
            self.make("1", "Tibet earthquake kills 16", "en",
                      ["PLACE:CN", "CITY:TIBET"], ["EARTHQUAKE"], 0),
            self.make("2", "西藏发生7级地震", "zh",
                      ["PLACE:CN", "CITY:TIBET"], ["EARTHQUAKE"], 48),
        ]
        cluster_articles(items)
        self.assertEqual(items[0]["coverage"], 1)


class TextTests(unittest.TestCase):
    def test_canonical_url(self):
        url = "https://example.com/a/?utm_source=x&utm_medium=y&id=3#top"
        self.assertEqual(canonical_url(url), "https://example.com/a/?id=3")

    def test_fingerprint(self):
        self.assertEqual(fingerprint("Hello, World!"), fingerprint("hello world"))

    def test_chinese_tokens(self):
        tokens = tokenize("以色列与哈马斯达成停火协议", "zh")
        self.assertIn("哈马", tokens)
        self.assertIn("马斯", tokens)

    def test_cluster(self):
        items = [
            {"id": "1", "title": "Israel and Hamas agree to ceasefire in Gaza", "language": "en", "publisher": "A"},
            {"id": "2", "title": "Israel and Hamas agree ceasefire in Gaza", "language": "en", "publisher": "B"},
            {"id": "3", "title": "Markets rally as inflation cools", "language": "en", "publisher": "C"},
        ]
        cluster_articles(items)
        self.assertEqual(items[0]["coverage"], 2)
        self.assertEqual(items[2]["coverage"], 1)

    def test_diversify(self):
        items = [{"publisher": "A", "id": i} for i in range(4)] + [
            {"publisher": "B", "id": 10}, {"publisher": "C", "id": 11},
            {"publisher": "B", "id": 12}, {"publisher": "C", "id": 13},
        ]
        result = diversify(items, cooldown=2)
        self.assertEqual(len(result), 8)
        self.assertEqual([x["publisher"] for x in result[:6]], ["A", "B", "C", "A", "B", "C"])
        self.assertEqual(sorted(x["id"] for x in result), sorted(x["id"] for x in items))

    def test_diversify_spreads_sources(self):
        items = [{"publisher": "A", "id": i} for i in range(6)] + [
            {"publisher": name, "id": 100 + i}
            for i, name in enumerate(("B", "C", "D", "E", "F"))
        ]
        result = diversify(items)
        self.assertEqual([x["publisher"] for x in result[:7]], ["A", "B", "C", "D", "E", "A", "F"])
        self.assertEqual(sorted(x["id"] for x in result), sorted(x["id"] for x in items))


class TaxonomyTests(unittest.TestCase):
    def test_country(self):
        self.assertEqual(region_of("JP"), "east_asia")
        self.assertEqual(region_of("US"), "north_america")
        self.assertEqual(country_from_url("https://www3.nhk.or.jp/news/", "US"), "JP")
        self.assertEqual(country_from_url("https://www.bbc.com/news", "ID"), "GB")
        self.assertEqual(base_language("zh-Hant"), "zh")

    def test_script(self):
        self.assertTrue(script_matches("这是中文标题", "zh"))
        self.assertFalse(script_matches("This is English", "zh"))
        self.assertTrue(script_matches("これは日本語です", "ja"))
        self.assertFalse(script_matches("これは日本語です", "en"))


class IngestTests(unittest.TestCase):
    RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel><title>Test</title>
      <item>
        <title>Central bank cuts rates</title>
        <link>https://example.com/a?utm_source=rss</link>
        <description><![CDATA[<p>Inflation slowed.</p>]]></description>
        <pubDate>Thu, 22 Oct 2026 10:00:00 GMT</pubDate>
      </item>
      <item>
        <title>Old story</title>
        <link>https://example.com/old</link>
        <pubDate>Mon, 01 Jan 2024 10:00:00 GMT</pubDate>
      </item>
    </channel></rss>"""

    def test_parse_polymarket_markets(self):
        feed = {"id": "polymarket", "publisher": "Polymarket", "homepage": "https://polymarket.com/", "max_items": 10}
        data = [
            {
                "question": "Will the Fed cut rates in December?",
                "slug": "fed-cut-december",
                "outcomes": '["Yes", "No"]',
                "outcomePrices": '["0.62", "0.38"]',
                "volume24hr": 120000.0,
                "liquidityNum": 50000.0,
                "endDate": "2026-12-18T20:00:00Z",
                "updatedAt": "2026-10-24T10:00:00.000Z",
                "active": True,
                "closed": False,
                "image": "https://example.com/fed.jpg",
            },
            {
                "question": "Will the home team win?",
                "slug": "home-win",
                "outcomes": '["Yes", "No"]',
                "outcomePrices": '["0.51", "0.49"]',
                "volume24hr": 10.0,
                "active": True,
                "closed": False,
            },
        ]
        items = parse_polymarket_markets(data, feed)
        self.assertEqual(len(items), 2)
        self.assertIn("预测市场", items[0]["summary"])
        self.assertIn("Yes 62.0%", items[0]["summary"])
        self.assertEqual(items[0]["url"], "https://polymarket.com/event/fed-cut-december")
        self.assertTrue(items[0]["snapshot_update"])
        self.assertEqual(items[0]["published_at"], "2026-10-24T10:00:00Z")
        self.assertEqual(items[0]["publisher"], "Polymarket")

    def test_parse_polymarket_events_filters_sports(self):
        feed = {"id": "polymarket", "publisher": "Polymarket", "homepage": "https://polymarket.com/", "max_items": 10}
        data = [
            {
                "title": "Fed Decision in October?",
                "slug": "fed-decision",
                "volume24hr": 1000,
                "liquidity": 500,
                "endDate": "2026-10-29T03:59:00Z",
                "updatedAt": "2026-10-24T10:00:00Z",
                "tags": [{"slug": "economy"}],
                "markets": [
                    {"groupItemTitle": "No change", "outcomePrices": '["0.9", "0.1"]', "active": True, "closed": False},
                    {"groupItemTitle": "25 bps cut", "outcomePrices": '["0.1", "0.9"]', "active": True, "closed": False},
                ],
            },
            {
                "title": "Aston Villa vs Manchester City",
                "slug": "football",
                "volume24hr": 2000,
                "tags": [{"slug": "sports"}, {"slug": "soccer"}],
                "markets": [{"groupItemTitle": "Home", "outcomePrices": '["0.5", "0.5"]'}],
            },
        ]
        items = parse_polymarket_markets(data, feed)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Fed Decision in October?")
        self.assertIn("No change 90.0%", items[0]["summary"])
        self.assertNotIn("Aston Villa", items[0]["title"])

    def test_parse_rss_and_cutoff(self):
        feed = {
            "id": "test", "name": "Test", "publisher": "Test News",
            "country": "US", "language": "en", "kind": "direct", "max_items": 10,
        }
        recent = (datetime.now(timezone.utc) - timedelta(days=1)).strftime(
            "%a, %d %b %Y %H:%M:%S GMT"
        )
        rss = self.RSS.replace(b"Thu, 22 Oct 2026 10:00:00 GMT", recent.encode())
        items = parse_feed(rss, feed)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["publisher"], "Test News")
        self.assertEqual(items[0]["summary"], "Inflation slowed.")
        self.assertIn("utm_source=rss", items[0]["url"])

    def test_google_news_suffix(self):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><title>G</title><item>
          <title>Headline here - Example News</title>
          <link>https://news.google.com/rss/articles/abc</link>
          <pubDate>Thu, 22 Oct 2026 10:00:00 GMT</pubDate>
          <source url="https://example.jp">Example News</source>
        </item></channel></rss>"""
        feed = {
            "id": "g", "name": "G", "publisher": "Google News", "country": "JP",
            "language": "ja", "kind": "aggregator", "max_items": 10,
        }
        recent = (datetime.now(timezone.utc) - timedelta(days=1)).strftime(
            "%a, %d %b %Y %H:%M:%S GMT"
        )
        xml = xml.replace(b"Thu, 22 Oct 2026 10:00:00 GMT", recent.encode())
        items = parse_feed(xml, feed)
        self.assertEqual(items[0]["publisher"], "Example News")
        self.assertEqual(items[0]["title"], "Headline here")

    def test_aggregator_language_guard(self):
        feed = {
            "id": "g", "name": "G", "publisher": "Google News", "country": "IR",
            "language": "fa", "kind": "aggregator", "max_items": 10,
        }
        raw = {
            "title": "This is an English fallback headline",
            "url": "https://news.google.com/x", "published_at": "2026-10-23T00:00:00Z",
            "summary": "", "publisher": "Example", "publisher_url": "https://example.com",
            "image_url": None,
        }
        self.assertIsNone(build_article(raw, feed, Classifier()))


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.conn = connect(Path(self.tmp.name))
        init_db(self.conn)
        now = datetime.now(timezone.utc)

        def article(i, title, publisher, category, hours_ago=1, event_country=None, event_region=None, content_type="hard", event_places=None, event_topics=None, event_entities=None):
            published = (now - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
            return {
                "id": f"id{i}", "title": title, "summary": "", "url": f"https://x/{i}",
                "feed_id": "feed", "feed_name": "Feed", "publisher": publisher,
                "country": "US", "region": "north_america", "language": "en",
                "category": category, "category_terms": [], "category_scores": {},
                "ownership": "private", "published_at": published,
                "fetched_at": published, "fingerprint": f"fp{i}",
                "event_country": event_country, "event_region": event_region,
                "event_places": event_places or [], "event_entities": event_entities or [],
                "event_topics": event_topics or [],
                "event_confidence": "medium" if event_country else "none",
                "content_type": content_type, "content_type_terms": [], "rss_categories": [],
            }

        self.make_article = article
        self.articles = [
            article(1, "Rates fall", "A", "economy", event_country="PS", event_region="middle_east"),
            article(2, "Election result", "B", "politics"),
            article(3, "Ceasefire signed", "A", "military", event_country="UA", event_region="europe", content_type="analysis"),
            article(4, "Old rates story", "C", "economy", hours_ago=48),
        ]
        self.assertEqual(insert_articles(self.conn, self.articles), 4)

    def tearDown(self):
        self.conn.close()
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_query_and_facets(self):
        items, total = query_articles(self.conn, {"hours": 24}, limit=10)
        self.assertEqual(total, 3)
        self.assertEqual(len(items), 3)
        facets = facet_counts(self.conn, {"hours": 24})
        economy = next(x for x in facets["category"] if x["key"] == "economy")
        self.assertEqual(economy["count"], 1)
        self.assertEqual(kpis(self.conn, {"hours": 24})["publishers"], 2)

    def test_filter(self):
        items, total = query_articles(self.conn, {"hours": 24, "publisher": "A"}, limit=10)
        self.assertEqual(total, 2)
        self.assertTrue(all(item["publisher"] == "A" for item in items))

    def test_event_geo(self):
        items, total = query_articles(
            self.conn, {"hours": 24, "geo": "event", "country": "UA"}, limit=10
        )
        self.assertEqual(total, 1)
        self.assertEqual(items[0]["title"], "Ceasefire signed")
        self.assertEqual(unlocated_count(self.conn, {"hours": 24, "geo": "event"}), 1)
        self.assertEqual(kpis(self.conn, {"hours": 24, "geo": "event"})["countries"], 2)
        country_facets = facet_counts(self.conn, {"hours": 24, "geo": "event"})["country"]
        self.assertEqual({x["key"] for x in country_facets}, {"PS", "UA"})

    def test_content_type_filter(self):
        items, total = query_articles(
            self.conn, {"hours": 24, "content_type": "analysis"}, limit=10
        )
        self.assertEqual(total, 1)
        self.assertEqual(items[0]["title"], "Ceasefire signed")
        facets = facet_counts(self.conn, {"hours": 24})["content_type"]
        self.assertEqual({x["key"] for x in facets}, {"hard", "analysis"})

    def test_search_tokens_and_event_metadata(self):
        extra = self.make_article(5, "Quake hits remote region", "D", "other")
        extra["event_places"] = [{"id": "TIBET", "label": "西藏"}]
        extra["event_topics"] = [{"id": "EARTHQUAKE", "label": "地震"}]
        extra["event_entities"] = ["ACTOR:PUTIN"]
        insert_articles(self.conn, [extra])
        self.assertEqual(query_articles(self.conn, {"hours": 24, "q": "西藏"}, limit=10)[1], 1)
        self.assertEqual(query_articles(self.conn, {"hours": 24, "q": "地震 西藏"}, limit=10)[1], 1)
        self.assertEqual(query_articles(self.conn, {"hours": 24, "q": "地震 火山"}, limit=10)[1], 0)
        summary = search_summary(self.conn, {"hours": 24, "q": "地震 西藏"})
        self.assertEqual(summary["topics"][0]["label"], "地震")
        self.assertEqual(summary["places"][0]["label"], "西藏")
        self.assertEqual(summary["sampled"], 1)
        self.assertEqual(summary["source_countries"], 1)
        self.assertEqual(query_articles(self.conn, {"hours": 24, "q": "普京"}, limit=10)[1], 1)

    def test_snapshot_update_refreshes_summary(self):
        article = self.make_article(10, "Market odds", "Polymarket", "politics")
        article["snapshot_update"] = True
        article["summary"] = "old odds"
        self.assertEqual(insert_articles(self.conn, [article]), 1)
        article["summary"] = "new odds"
        self.assertEqual(insert_articles(self.conn, [article]), 0)
        row = self.conn.execute("SELECT summary FROM articles WHERE id=?", (article["id"],)).fetchone()
        self.assertEqual(row["summary"], "new odds")

    def test_short_tokens_do_not_match_inside_words(self):
        noise = self.make_article(8, "UN agencies tour West Bank", "G", "politics")
        target = self.make_article(9, "Banks lock out AI agents", "H", "economy")
        insert_articles(self.conn, [noise, target])
        items, total = query_articles(
            self.conn, {"hours": 24, "q": "AI agents banking"}, limit=10
        )
        titles = {item["title"] for item in items}
        self.assertIn(target["title"], titles)
        self.assertNotIn(noise["title"], titles)

    def test_relaxed_search_falls_back_to_or(self):
        strict_filters = {"hours": 24, "q": "Ceasefire signed nonexistent"}
        _, strict_total = query_articles(self.conn, strict_filters, limit=10)
        self.assertEqual(strict_total, 0)
        relaxed_filters = dict(strict_filters)
        relaxed_filters["_relaxed"] = True
        items, relaxed_total = query_articles(self.conn, relaxed_filters, limit=10)
        self.assertGreaterEqual(relaxed_total, 1)
        self.assertTrue(any(item["title"] == "Ceasefire signed" for item in items))

    def test_cross_language_variants(self):
        ru = self.make_article(6, "Землетрясение в Тибете", "E", "other")
        zh = self.make_article(7, "西藏发生地震", "F", "other")
        insert_articles(self.conn, [ru, zh])
        filters = {
            "hours": 24,
            "q": "Tibet earthquake",
            "_variants": [
                {"language": "ru", "text": "Землетрясение в Тибете", "terms": ["Землетя", "Тибе"]},
                {"language": "zh", "text": "西藏地震", "terms": ["西藏", "地震"]},
            ],
        }
        items, total = query_articles(self.conn, filters, limit=20)
        self.assertEqual(total, 2)
        self.assertEqual({item["title"] for item in items}, {ru["title"], zh["title"]})

    def test_dedup(self):
        self.assertEqual(insert_articles(self.conn, self.articles), 0)

    def test_filtered_articles_are_hidden_from_queries(self):
        junk = self.make_article(11, "Junk lifestyle item", "Z", "other")
        self.assertEqual(insert_articles(self.conn, [junk]), 1)
        self.conn.execute("UPDATE articles SET filtered=1 WHERE id=?", (junk["id"],))
        self.conn.commit()
        items, total = query_articles(self.conn, {"hours": 24}, limit=20)
        self.assertEqual(total, 3)
        self.assertNotIn(junk["title"], {item["title"] for item in items})
        self.assertEqual(count_articles(self.conn), 4)
        facets = facet_counts(self.conn, {"hours": 24})
        self.assertEqual(sum(entry["count"] for entry in facets["category"]), 3)


class ElectionsRegistryTests(unittest.TestCase):
    def test_registry_lists_configured_elections(self):
        elections = list_elections()
        ids = {item["id"] for item in elections}
        self.assertIn("brazil-2026", ids)
        self.assertIn("nigeria-2027", ids)
        self.assertTrue(any(item["status"] == "upcoming" for item in elections))

    def test_default_prefers_upcoming_election(self):
        default = default_election()
        self.assertIsNotNone(default)
        self.assertEqual(default["status"], "upcoming")

    def test_unknown_election_is_none(self):
        self.assertIsNone(get_election("does-not-exist"))

    def test_non_live_adapter_returns_structured_error(self):
        data = fetch_election_results("france-2027", "br")
        self.assertFalse(data["ok"])
        self.assertEqual(data["adapter"], "none")
        self.assertIn("official_url", data)


class CustomizationTests(unittest.TestCase):
    def setUp(self):
        import customization

        self.customization = customization
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = customization.PATH
        customization.PATH = Path(self.tmp.name) / "customization.json"
        customization._CACHE["overlay_mtime"] = None
        customization._CACHE["overlay"] = {}

    def tearDown(self):
        self.customization.PATH = self.old_path
        self.customization._CACHE["overlay_mtime"] = None
        self.customization._CACHE["overlay"] = {}
        self.tmp.cleanup()

    def test_save_and_reset_override(self):
        feeds = self.customization.read_json("feeds")
        feeds["feeds"][0]["name"] = "Edited Feed"
        self.customization.save_config("feeds", feeds)
        self.assertTrue(self.customization.is_overridden("feeds"))
        self.assertEqual(
            self.customization.read_json("feeds")["feeds"][0]["name"],
            "Edited Feed",
        )
        self.customization.reset_config("feeds")
        self.assertFalse(self.customization.is_overridden("feeds"))

    def test_duplicate_feed_is_rejected(self):
        feeds = self.customization.read_json("feeds")
        feeds["feeds"].append(dict(feeds["feeds"][0]))
        with self.assertRaises(self.customization.ConfigError):
            self.customization.save_config("feeds", feeds)

    def test_ui_roundtrip(self):
        ui = self.customization.save_ui(
            {"default_hours": 72, "compact": True, "accent": "#f59e0b"}
        )
        self.assertEqual(ui["default_hours"], 72)
        self.assertTrue(ui["compact"])
        self.assertEqual(self.customization.get_ui()["accent"], "#f59e0b")

    def test_invalid_accent_is_rejected(self):
        with self.assertRaises(self.customization.ConfigError):
            self.customization.save_ui({"accent": "red"})


if __name__ == "__main__":
    unittest.main()
