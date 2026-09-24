from __future__ import annotations

import hashlib
import html
import json
import re
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import feedparser

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from feeds import FEEDS

DATA_DIR = ROOT / "data"
FEED_PATH = DATA_DIR / "feed.json"

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def clean_text(value: str | None, max_length: int = 320) -> str:
    if not value:
        return ""
    value = html.unescape(TAG_RE.sub(" ", value))
    value = SPACE_RE.sub(" ", value).strip()
    if len(value) > max_length:
        value = value[: max_length - 1].rstrip() + "…"
    return value


def published_iso(entry) -> str:
    for field in ("published", "updated", "created"):
        raw = entry.get(field)
        if not raw:
            continue
        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError, OverflowError):
            pass

    return datetime.now(timezone.utc).isoformat()


def make_external_id(source: str, entry) -> str:
    stable = (
        entry.get("id")
        or entry.get("guid")
        or entry.get("link")
        or entry.get("title", "")
    )
    return hashlib.sha256(f"{source}|{stable}".encode("utf-8")).hexdigest()


def collect_feed(feed) -> list[dict]:
    parsed = feedparser.parse(
        feed["url"],
        request_headers={
            "User-Agent": "Mozilla/5.0 (compatible; MyHub/0.2; +https://myhub.pythonanywhere.com)"
        },
    )

    if parsed.bozo and not parsed.entries:
        print(f"[ERROR] {feed['name']}: {parsed.bozo_exception}")
        return []

    items = []

    for entry in parsed.entries[:50]:
        link = entry.get("link")
        title = clean_text(entry.get("title"), 220)

        if not link or not title:
            continue

        summary = (
            entry.get("summary")
            or entry.get("description")
            or (entry.get("content") or [{}])[0].get("value", "")
        )

        items.append(
            {
                "id": make_external_id(feed["name"], entry),
                "source": feed["name"],
                "category": feed["category"],
                "title": title,
                "summary": clean_text(summary),
                "url": link,
                "published_at": published_iso(entry),
            }
        )

    print(f"[OK] {feed['name']}: {len(items)} items")
    return items


def read_existing() -> list[dict]:
    if not FEED_PATH.exists():
        return []

    try:
        with FEED_PATH.open("r", encoding="utf-8") as f:
            return json.load(f).get("items", [])
    except (OSError, json.JSONDecodeError):
        return []


def write_feed(items: list[dict]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    unique = {}
    for item in items:
        unique[item["id"]] = item

    ordered = sorted(
        unique.values(),
        key=lambda item: item.get("published_at", ""),
        reverse=True,
    )[:250]

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(ordered),
        "items": ordered,
    }

    with FEED_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"[SAVE] {len(ordered)} unique items -> {FEED_PATH}")


def main():
    fresh = []
    for feed in FEEDS:
        fresh.extend(collect_feed(feed))

    write_feed(read_existing() + fresh)
    print(f"Done. Collected {len(fresh)} fresh items.")


if __name__ == "__main__":
    main()
