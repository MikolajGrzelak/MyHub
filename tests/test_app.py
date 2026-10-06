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
        html = self.client.get('/').get_data(as_text=True)
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

    def test_deals_only_include_verified_current_targets_or_historical_lows(self):
        self.write([
            item(1, source_type="deal", active=True, price_verified=True, price="10,00 zł", historical_price="10,00 zł"),
            item(2, source_type="deal", active=True, price_verified=True, current_price=20, target_price=25),
            item(3, source_type="deal", active=True, price_verified=True, price="30 zł", historical_price="10 zł", matched_keywords=["Legion"]),
            item(4, source_type="deal", active=True, price="10 zł", priority=True),
            item(5, source_type="deal", active=False, price_verified=True, current_price=0, historical_low=0),
            item(6, source_type="deal", active=True, price_verified=True, price="0,00 zł", historical_price="0,00 zł"),
        ])
        result = self.client.get('/api/feed?section=deal').json
        self.assertEqual({i['id'] for i in result['items']}, {'1', '2', '6'})
        self.assertEqual(self.client.get('/api/feed').json['count'], 5)

    def test_invalid_prices_never_qualify_and_minimum_is_rechecked(self):
        for price in ['nan', 'inf', -1, True, '20 zł zamiast 10 zł']:
            self.assertIsNone(web.price_number(price))
        self.assertFalse(web.deal_signals({'active': True, 'price_verified': True,
                         'current_price': 15, 'historical_low': 10, 'is_historical_low': True})['deal_qualified'])


if __name__ == '__main__':
    unittest.main()
