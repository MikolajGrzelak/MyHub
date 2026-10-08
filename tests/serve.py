"""Deterministic browser-test server; never modifies the real collected data."""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app as web


def run():
    games = json.loads((ROOT / 'data/game_watchlist.json').read_text(encoding='utf-8'))['games']
    items = []
    for index in range(200):
        kind = ['news', 'reddit', 'youtube', 'deal'][index % 4]
        game = games[(index // 4) % len(games)]
        record = {'id': f'test-{index}', 'title': f'Legion Go test {index}', 'source_type': kind,
                  'source': {'news': 'Test news', 'reddit': 'r/LegionGo', 'youtube': 'Test channel', 'deal': 'GG.deals'}[kind],
                  'category': 'Okazje' if kind == 'deal' else 'Gaming', 'language': 'pl' if index % 3 else 'en',
                  'url': f'https://gg.deals/game/test-{index}/', 'published_at': '2026-10-07T08:00:00Z',
                  'first_seen_at': '2026-10-07T08:00:00Z', 'summary': 'Treść testowa', 'matched_keywords': []}
        if kind == 'deal':
            current = 20 + index // 4
            record.update(title=game['name'], steam_app_id=game['steam_app_id'], active=True,
                          price_verified=True, current_price=current, historical_low=current if index % 8 == 3 else 5,
                          price=f'{current},00 zł', retail_price=f'{current + 2},00 zł', keyshop_price=f'{current},00 zł',
                          historical_price=f'{current if index % 8 == 3 else 5},00 zł', currency='PLN', price_kind='keyshop',
                          price_checked_at='2026-10-07T08:00:00Z')
        items.append(record)
    items.append({'id': 'steam-jusant', 'title': 'Performance update', 'source': 'Steam · Jusant',
                  'source_type': 'news', 'category': 'Gaming', 'language': 'en', 'steam_app_id': 1977170,
                  'url': 'https://store.steampowered.com/news/42', 'published_at': '2026-10-07T09:00:00Z',
                  'is_game_update': True})
    with tempfile.TemporaryDirectory(prefix='myhub-browser-') as folder:
        web.FEED_PATH = Path(folder) / 'feed.json'
        web.HISTORY_PATH = Path(folder) / 'history.json'
        web.TRACKING_DB = Path(folder) / 'tracking.db'
        web.TRACKED_PATH = Path(folder) / 'tracked.json'
        web.FEED_PATH.write_text(json.dumps({'updated_at': '2026-10-07T09:00:00Z', 'items': items}), encoding='utf-8')
        web.HISTORY_PATH.write_text(json.dumps({'games': {'1977170': [
            {'at': '2026-10-06T08:00:00Z', 'current': 50, 'retail': 55, 'keyshop': 50, 'currency': 'PLN'},
            {'at': '2026-10-07T08:00:00Z', 'current': 36, 'retail': 38, 'keyshop': 36, 'currency': 'PLN'}]}}), encoding='utf-8')
        web.app.run(port=5056)


if __name__ == '__main__':
    run()
