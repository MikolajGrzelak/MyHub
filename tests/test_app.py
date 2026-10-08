import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as web


def item(index=0, **changes):
    return {"id": str(index), "title": f"Legion Go {index}", "source": "Źródło Łódź",
            "source_type": "news", "language": "pl", "category": "Tech",
            "url": f"https://example.com/{index}", "published_at": "2026-10-06T08:00:00Z", **changes}


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "feed.json"
        self.path_patch = patch.object(web, "FEED_PATH", self.path)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.watchlist_path = Path(self.temp.name) / 'games.json'
        self.watchlist_path.write_text(json.dumps({'games': [{'name': 'Jusant', 'steam_app_id': 1977170}]}), encoding='utf-8')
        for attribute, path in [('WATCHLIST_PATH', self.watchlist_path), ('HISTORY_PATH', Path(self.temp.name) / 'history.json'),
                                ('TRACKING_DB', Path(self.temp.name) / 'tracking.db'), ('TRACKED_PATH', Path(self.temp.name) / 'tracked.json')]:
            replacement = patch.object(web, attribute, path)
            replacement.start()
            self.addCleanup(replacement.stop)
        web._feed_cache.update(signature=None, items=[], updated_at=None, error=None)
        self.client = web.app.test_client()
        self.write([item()])

    def write(self, records):
        self.path.write_text(json.dumps({"items": records, "updated_at": "2026-10-06T08:00:00Z"}), encoding="utf-8")

    def test_search_uses_whole_feed_beyond_original_limit(self):
        records = [item(i) for i in range(170)]
        records[-1]["title"] = "Wyjątkowa gra z Łodzi"
        self.write(records)
        result = self.client.get('/api/feed?q=wyjatkowa+lodz').json
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["id"], "169")

    def test_pagination_exposes_every_item_without_overlap(self):
        self.write([item(i) for i in range(170)])
        ids = []
        for page in range(1, 6):
            result = self.client.get(f'/api/feed?page={page}').json
            ids.extend(i["id"] for i in result["items"])
        self.assertEqual(len(ids), 170)
        self.assertEqual(len(set(ids)), 170)
        self.assertFalse(result["has_more"])

    def test_filters_combine_and_language_links_preserve_them(self):
        self.write([item(), item(1, language="en"), item(2, source_type="reddit")])
        result = self.client.get('/api/feed?section=news&lang=pl&category=Tech&source=%C5%B9r%C3%B3d%C5%82o+%C5%81%C3%B3d%C5%BA&q=Legion').json
        self.assertEqual(result["count"], 1)
        with web.app.test_request_context('/?section=news&category=Tech&q=Legion&page=3'):
            self.assertEqual(web.filter_url(lang='en'), '/?section=news&category=Tech&q=Legion&lang=en')

    def test_malformed_page_and_unknown_section_do_not_break_render(self):
        for url in ['/?page=oops', '/?page=-5', '/?section=%22%3Cscript%3E', '/?view=saved']:
            self.assertEqual(self.client.get(url).status_code, 200)

    def test_reddit_does_not_show_legacy_translation(self):
        self.write([item(source_type="reddit", language="en", summary="Author's words", summary_pl="Legacy translation")])
        html = self.client.get('/?section=reddit').get_data(as_text=True)
        self.assertIn("Author&#39;s words", html)
        self.assertNotIn("Legacy translation", html)

    def test_expired_deals_invalid_records_and_unsafe_urls_are_excluded(self):
        self.write([item(), item(1, source_type="deal", active=False), item(2, url="javascript:alert(1)"), None, item(3, source_type=[]), item(4, thumbnail_url="data:bad")])
        result = self.client.get('/api/feed').json
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["items"][-1]["thumbnail_url"], "")

    def test_html_and_json_script_escape_untrusted_titles(self):
        self.write([item(title='</script><img src=x onerror=alert(1)>')])
        html = self.client.get('/').get_data(as_text=True)
        self.assertNotIn('</script><img src=x', html)
        self.assertIn('&lt;/script&gt;', html)

    def test_dates_sort_by_instant_not_offset_string(self):
        self.write([item(0, published_at="2026-10-06T10:00:00+03:00"), item(1, published_at="2026-10-06T08:00:00Z")])
        self.assertEqual(self.client.get('/api/feed').json["items"][0]["id"], '1')

    def test_cached_feed_survives_partial_upload_but_health_reports_it(self):
        self.assertEqual(self.client.get('/health').status_code, 200)
        self.path.write_text('{"items":', encoding="utf-8")
        health = self.client.get('/health')
        self.assertEqual(health.status_code, 503)
        self.assertEqual(health.json["items"], 1)
        self.assertEqual(self.client.get('/api/feed').json["count"], 1)
        self.write([item(9)])
        self.assertEqual(self.client.get('/health').status_code, 200)
        self.assertEqual(self.client.get('/api/feed').json["items"][0]["id"], '9')

    def test_missing_or_wrong_shape_feed_degrades_without_500(self):
        self.path.unlink()
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.get('/health').status_code, 503)
        self.path.write_text('[]', encoding="utf-8")
        self.assertEqual(self.client.get('/health').status_code, 503)

    def test_worker_has_root_scope_and_is_revalidated(self):
        worker = self.client.get('/service-worker.js')
        self.assertEqual(worker.status_code, 200)
        self.assertEqual(worker.headers['Service-Worker-Allowed'], '/')
        self.assertEqual(worker.headers['Cache-Control'], 'no-cache')
        worker.close()
        self.assertEqual(self.client.get('/offline').status_code, 200)

    def test_priority_includes_keywords_without_legacy_flag(self):
        self.write([item(), item(1, matched_keywords=['Z1E']), item(2, priority=True)])
        result = self.client.get('/api/feed?section=priority').json
        self.assertEqual(result["count"], 2)

    def test_saved_page_does_not_include_server_feed_records(self):
        result = self.client.get('/api/feed?view=saved').json
        self.assertEqual(result["items"], [])
        self.assertFalse(result["has_more"])

    def test_offers_include_all_watched_games_and_low_filter_matches_either_current_price(self):
        self.watchlist_path.write_text(json.dumps({'games': [{'name': f'Game {i}', 'steam_app_id': i} for i in range(1, 6)]}), encoding='utf-8')
        self.write([
            item(1, source='GG.deals', steam_app_id=1, source_type='deal', active=True, price_verified=True, current_price=10, retail_price_value=15, keyshop_price_value=10, historical_low=10),
            item(2, source='GG.deals', steam_app_id=2, source_type='deal', active=True, price_verified=True, current_price=20, retail_price_value=20, historical_low=10),
            item(3, source='GG.deals', steam_app_id=3, source_type='deal', active=True, price_verified=True, current_price=0, retail_price_value=0, historical_low=0),
            item(4, source='GG.deals', steam_app_id=4, source_type='deal', active=False, price_verified=True, current_price=5, historical_low=5),
            item(5, source='GG.deals', steam_app_id=5, source_type='deal', active=True, current_price=10, historical_low=10),
        ])
        result = self.client.get('/api/feed?section=deal').json
        self.assertEqual(result['count'], 5)
        self.assertFalse(result['has_more'])
        self.assertEqual({str(i['steam_app_id']) for i in self.client.get('/api/feed?section=deal&low=1').json['items']}, {'1', '3'})
        self.assertIn('—', result['html'])
        self.assertFalse(web.deal_signals({'active': True, 'price_verified': True, 'current_price': 8, 'historical_low': 10})['is_historical_low'])
        self.assertTrue(web.deal_signals({'active': True, 'price_verified': True, 'current_price': 8, 'retail_price_value': 10, 'keyshop_price_value': 8, 'historical_low': 10})['is_historical_low'])

    def test_invalid_prices_never_qualify_and_minimum_is_rechecked(self):
        for price in ['nan', 'inf', -1, True, '20 zł zamiast 10 zł']:
            self.assertIsNone(web.price_number(price))
        self.assertFalse(web.deal_signals({'active': True, 'price_verified': True,
                         'current_price': 15, 'historical_low': 10, 'is_historical_low': True})['deal_qualified'])

    def test_news_is_default_and_start_is_removed(self):
        self.write([item(), item(1, source_type='reddit'), item(2, source_type='youtube')])
        self.assertEqual([i['id'] for i in self.client.get('/api/feed').json['items']], ['0'])
        html = self.client.get('/').get_data(as_text=True)
        self.assertNotIn('<span>Start</span>', html)
        self.assertIn('data-section="news"', html)

    def test_game_page_joins_exact_prices_and_announcements_and_paginates(self):
        self.write([item(0, source='GG.deals', steam_app_id=1977170, source_type='deal', active=True, price_verified=True, current_price=20)] +
                   [item(i, steam_app_id=1977170, title=f'Update {i}', is_game_update=True) for i in range(1, 45)] +
                   [item(99, title='Unrelated')])
        result = self.client.get('/api/feed?view=games&game=1977170').json
        self.assertEqual(result['count'], 44)
        self.assertEqual(len(result['items']), 36)
        self.assertTrue(result['has_more'])
        self.assertEqual(len(self.client.get('/api/feed?view=games&game=1977170&page=2').json['items']), 8)
        html = self.client.get('/?view=games&game=1977170').get_data(as_text=True)
        self.assertIn('Jusant', html)
        self.assertNotIn('Unrelated', html)

    def test_invalid_catalog_and_history_do_not_break_new_views(self):
        self.watchlist_path.write_text('[]', encoding='utf-8')
        for url in ['/?view=games', '/?view=hardware', '/?view=games&game=bad']:
            self.assertEqual(self.client.get(url).status_code, 200)

    def test_same_patch_title_for_different_games_is_not_grouped(self):
        self.write([item(1, title='Patch 1.1', steam_app_id=123), item(2, title='Patch 1.1', steam_app_id=456)])
        self.assertEqual(self.client.get('/api/feed').json['count'], 2)

    def test_steam_tracking_validates_links_origin_duplicates_and_limits(self):
        headers = {'Origin': 'http://localhost'}
        for value in ['https://evil.com/app/620/', 'https://store.steampowered.com/bundle/620/', 'https://store.steampowered.com/app/0/', 'javascript:alert(1)', '999999999999999999999', 'https://store.steampowered.com:8080/app/620/']:
            self.assertEqual(self.client.post('/api/tracking', json={'steam': value}, headers=headers).status_code, 400)
        self.assertEqual(self.client.post('/api/tracking', json={'steam': '620'}, headers={'Origin': 'https://evil.com'}).status_code, 403)
        result = self.client.post('/api/tracking', json={'steam': 'https://store.steampowered.com/app/620/Portal_2/?x=y'}, headers=headers)
        self.assertEqual(result.status_code, 202)
        self.assertEqual(result.json['steam_app_id'], '620')
        self.assertEqual(self.client.post('/api/tracking', json={'steam': '620'}, headers=headers).json['status'], 'pending')
        self.assertEqual(len(self.client.get('/api/tracking').json['games']), 1)
        catalog = web.TRACKED_PATH
        catalog.write_text(json.dumps({'games': [{'steam_app_id': 620, 'name': 'Portal 2', 'status': 'ready'}]}), encoding='utf-8')
        html = self.client.get('/?section=deal&view=tracking').get_data(as_text=True)
        self.assertIn('Portal 2', html)
        self.assertEqual(self.client.post('/api/tracking', json={'steam': '620'}, headers=headers).json['status'], 'ready')
        catalog.write_text(json.dumps({'games': [{'steam_app_id': i, 'name': 'Not a game', 'status': 'rejected'} for i in range(1, 101)]}), encoding='utf-8')
        self.assertEqual(self.client.post('/api/tracking', json={'steam': '3'}, headers=headers).status_code, 400)
        self.assertEqual(self.client.post('/api/tracking', json={'steam': '621'}, headers=headers).status_code, 429)


if __name__ == '__main__':
    unittest.main()
