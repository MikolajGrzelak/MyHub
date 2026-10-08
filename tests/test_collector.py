import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from collectors import rss


class CollectorTests(unittest.TestCase):
    def test_ppe_uses_article_title_without_listing_platform_badges(self):
        source = {"name": "PPE", "url": "https://www.ppe.pl/news.html", "base_url": "https://www.ppe.pl",
                  "link_pattern": r"^/news/\d+/.+\.html$", "language": "pl", "category": "Gaming"}
        response = Mock(text='<a href="/news/123/example.html">Nowa gra Marvela wyciekła PS5 XSX|S PC</a>')
        detail = '<meta property="og:title" content="Nowa gra Marvela wyciekła"><meta property="article:published_time" content="2026-10-06T10:55:00">'
        with patch.object(rss.requests, 'get', return_value=response), patch.object(rss, '_parallel_fetch', return_value={"https://www.ppe.pl/news/123/example.html": detail}):
            result = rss.collect_html(source)
            self.assertEqual(result[0]['title'], 'Nowa gra Marvela wyciekła')
            self.assertEqual(result[0]['published_at'], '2026-10-06T08:55:00+00:00')

    def test_source_dates_use_polish_timezone_and_dst(self):
        zone = ZoneInfo('Europe/Warsaw')
        self.assertEqual(rss._parse_datetime_value('2026-10-06T10:55:00', zone), '2026-10-06T08:55:00+00:00')
        self.assertEqual(rss._parse_datetime_value('2026-12-06T10:55:00', zone), '2026-12-06T09:55:00+00:00')
        self.assertEqual(rss._parse_datetime_value('2026-10-06T10:55:00+02:00', zone), '2026-10-06T08:55:00+00:00')

    def test_nested_article_dates_receive_source_timezone(self):
        soup = BeautifulSoup('<script type="application/ld+json">{"@graph":[{"datePublished":"2026-10-06T10:55:00"}]}</script>', 'html.parser')
        self.assertEqual(rss.extract_published_from_soup(soup, ZoneInfo('Europe/Warsaw')), '2026-10-06T08:55:00+00:00')

    def test_missing_date_does_not_become_publication_time(self):
        self.assertIsNone(rss.published_iso({}))
        merged = rss.merge_items([], [{"id": "new", "source_type": "news"}])
        self.assertIsNone(merged[0]['published_at'])
        self.assertTrue(merged[0]['first_seen_at'])

    def test_deals_expire_and_unchanged_prices_keep_original_date(self):
        old = [{"id": "1", "source_type": "deal", "source": "GG.deals", "price": "12 zł", "published_at": "2026-10-01T10:00:00Z"}, {"id": "expired", "source_type": "deal"}]
        new = [{"id": "1", "source_type": "deal", "source": "GG.deals", "price": "12 zł", "published_at": "2026-10-06T10:00:00Z"}]
        result = rss.merge_items(old, new)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['published_at'], old[0]['published_at'])

    def test_merge_does_not_truncate_before_relevance_filter(self):
        self.assertEqual(len(rss.merge_items([{"id": str(i)} for i in range(500)], [])), 500)

    def test_active_deals_and_unchanged_watched_prices_survive_newer_posts(self):
        posts = [{"id": str(i), "source_type": "reddit", "published_at": "2026-10-06T09:00:00Z"} for i in range(500)]
        deals = [{"id": f"deal-{i}", "source_type": "deal", "active": True, "published_at": "2026-09-24T09:00:00Z"} for i in range(109)]
        result = rss.retain_feed_items(posts + deals)
        self.assertEqual(len(result), 450)
        self.assertEqual(sum(item['source_type'] == 'deal' for item in result), 109)
        self.assertEqual(result[-1]['published_at'], '2026-09-24T09:00:00Z')

    def test_retention_removes_expired_deals_and_reserves_slots_after_relevance(self):
        items = [{"id": str(i), "source_type": "news", "category": "Gaming", "title": "Cosplay streamer", "summary": ""} for i in range(500)]
        items += [{"id": "active", "source_type": "deal", "active": True}, {"id": "expired", "source_type": "deal", "active": False}]
        self.assertEqual([item['id'] for item in rss.retain_feed_items(items)], ['active'])

    def test_negative_and_nonfinite_prices_are_not_presented_as_offers(self):
        for value in [-1, 'nan', 'inf', None, 'bad']:
            self.assertIsNone(rss._price_number(value))
        self.assertEqual(rss._price_number('0'), 0)

    def test_watchlist_accepts_documented_platform_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'games.json'
            path.write_text(json.dumps({"games": [{"steam_app_id": 123, "platform": "xbox_play_anywhere"}]}))
            with patch.object(rss, 'GAME_WATCHLIST_PATH', path):
                self.assertTrue(rss.read_game_watchlist()[0]['xbox_play_anywhere'])

    def test_empty_feed_retries_even_without_parser_bozo_flag(self):
        response = Mock(content=b'<rss><channel/></rss>', status_code=200)
        with patch.object(rss.requests, 'get', return_value=response) as get, patch.object(rss.time, 'sleep'):
            self.assertIsNone(rss.fetch_rss('https://example.com/rss', 'Test', attempts=2))
            self.assertEqual(get.call_count, 2)
            self.assertEqual(get.call_args.kwargs['timeout'], 20)

    def test_atomic_feed_write_and_no_leftover_temp_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'feed.json'
            with patch.object(rss, 'DATA_DIR', Path(tmp)), patch.object(rss, 'FEED_PATH', path):
                rss.write_feed([{"id": "1"}])
                self.assertEqual(json.loads(path.read_text())['count'], 1)
                self.assertEqual(len(list(Path(tmp).iterdir())), 1)

    def test_price_history_records_changes_preserves_gaps_and_separates_store_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'history.json'
            offer = {"source": "GG.deals", "steam_app_id": 123, "active": True,
                     "price_verified": True, "current_price": 10, "retail_price_value": 15,
                     "keyshop_price_value": 10, "currency": "PLN", "price_kind": "keyshop",
                     "price_checked_at": "2026-10-06T08:00:00Z"}
            with patch.object(rss, 'PRICE_HISTORY_PATH', path):
                rss.record_price_history([offer])
                rss.record_price_history([{**offer, "price_checked_at": "2026-10-06T09:00:00Z"}])
                points = json.loads(path.read_text())['games']['123']
                self.assertEqual(len(points), 1)
                self.assertEqual(points[0]['at'], offer['price_checked_at'])
                self.assertEqual(points[0]['checked_at'], '2026-10-06T09:00:00Z')
                rss.record_price_history([{**offer, "retail_price_value": 12}])
                self.assertEqual(len(json.loads(path.read_text())['games']['123']), 2)
                rss.record_price_history([{**offer, "active": False}])
                self.assertEqual(len(json.loads(path.read_text())['games']['123']), 2)

    def test_steam_announcements_keep_source_date_and_link_to_exact_game(self):
        from datetime import datetime, timezone
        now = int(datetime.now(timezone.utc).timestamp())
        response = Mock()
        response.json.return_value = {"appnews": {"newsitems": [
            {"gid": "42", "date": now, "title": "Performance update", "url": "https://store.steampowered.com/news/42", "contents": "<b>Fixes</b>"},
            {"gid": "old", "date": 1, "title": "Old", "url": "https://example.com"},
            {"gid": "bad", "date": now, "title": "Bad", "url": "javascript:alert(1)"},
        ]}}
        with patch.object(rss.requests, 'get', return_value=response):
            items = rss.collect_steam_news([{"steam_app_id": 123, "name": "Test game"}])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['steam_app_id'], 123)
        self.assertEqual(items[0]['summary'], 'Fixes')
        self.assertTrue(items[0]['is_game_update'])

    def test_recent_watched_announcements_survive_new_posts_but_expire_after_60_days(self):
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        posts = [{"id": str(i), "source_type": "reddit", "published_at": now.isoformat()} for i in range(500)]
        recent = {"id": "patch", "source_type": "news", "is_game_update": True,
                  "title": "Version 1.2", "published_at": (now - timedelta(days=30)).isoformat()}
        expired = {**recent, "id": "old", "published_at": (now - timedelta(days=61)).isoformat()}
        invalid = {**recent, "id": "invalid", "published_at": "bad"}
        result = rss.retain_feed_items(posts + [recent, expired, invalid])
        self.assertEqual(len(result), 450)
        self.assertIn('patch', [i['id'] for i in result])
        self.assertNotIn('old', [i['id'] for i in result])
        self.assertNotIn('invalid', [i['id'] for i in result])


if __name__ == '__main__':
    unittest.main()
