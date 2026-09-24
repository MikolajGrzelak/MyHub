from __future__ import annotations

import hashlib
import html
import re
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import feedparser

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db import init_db, upsert_item
from feeds import FEEDS


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
    stable = entry.get("id") or entry.get("guid") or entry.get("link") or entry.get("title", "")
    digest = hashlib.sha256(f"{source}|{stable}".encode("utf-8")).hexdigest()
    return digest


def collect_feed(feed) -> int:
    parsed = feedparser.parse(
        feed["url"],
        request_headers={"User-Agent": "MyHub/0.1 (+https://myhub.pythonanywhere.com)"},
    )

    if parsed.bozo and not parsed.entries:
        print(f"[ERROR] {feed['name']}: {parsed.bozo_exception}")
        return 0

    count = 0
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

        upsert_item(
            {
                "external_id": make_external_id(feed["name"], entry),
                "source": feed["name"],
                "category": feed["category"],
                "title": title,
                "summary": clean_text(summary),
                "url": link,
                "published_at": published_iso(entry),
            }
        )
        count += 1

    print(f"[OK] {feed['name']}: {count} items")
    return count


def main():
    init_db()
    total = sum(collect_feed(feed) for feed in FEEDS)
    print(f"Done. Processed {total} items.")


if __name__ == "__main__":
    main()
