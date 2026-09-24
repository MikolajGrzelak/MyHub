from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import feedparser
from google import genai
from google.genai import types

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from feeds import FEEDS

DATA_DIR = ROOT / "data"
FEED_PATH = DATA_DIR / "feed.json"

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")

MODEL = os.environ.get("MYHUB_SUMMARY_MODEL", "gemini-3.8-flash")
MAX_AI_ITEMS = int(os.environ.get("MYHUB_MAX_AI_ITEMS", "15"))


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
            "User-Agent": "Mozilla/5.0 (compatible; MyHub/0.4; +https://myhub.pythonanywhere.com)"
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


def merge_items(existing: list[dict], fresh: list[dict]) -> list[dict]:
    merged = {item["id"]: item for item in existing}

    for item in fresh:
        previous = merged.get(item["id"], {})
        enriched = {
            key: previous[key]
            for key in ("summary_pl", "tags")
            if key in previous
        }
        merged[item["id"]] = {**item, **enriched}

    return sorted(
        merged.values(),
        key=lambda item: item.get("published_at", ""),
        reverse=True,
    )[:250]


def enrich_with_ai(items: list[dict]) -> int:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[AI] GEMINI_API_KEY missing; skipping Polish summaries.")
        return 0

    client = genai.Client(api_key=api_key)
    processed = 0

    schema = {
        "type": "object",
        "properties": {
            "summary_pl": {"type": "string"},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 4,
            },
        },
        "required": ["summary_pl", "tags"],
    }

    for item in items:
        if processed >= MAX_AI_ITEMS:
            break
        if item.get("summary_pl"):
            continue

        source_text = item.get("summary", "").strip()
        if not source_text:
            source_text = "(Brak opisu w RSS — oprzyj się tylko na tytule.)"

        prompt = f"""
Jesteś redaktorem osobistego agregatora newsów gamingowo-technologicznych.

Na podstawie WYŁĄCZNIE poniższego tytułu i opisu RSS:
1. Napisz zwięzłe streszczenie po polsku w 1-2 zdaniach, maksymalnie 260 znaków.
2. Nie dopowiadaj faktów, których nie ma w materiale.
3. Dobierz od 1 do 4 krótkich tagów po polsku lub nazw własnych.

Źródło: {item["source"]}
Tytuł: {item["title"]}
Opis RSS: {source_text}
""".strip()

        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                ),
            )
            result = json.loads(response.text)
            summary_pl = clean_text(result.get("summary_pl"), 280)
            tags = [
                clean_text(str(tag), 30)
                for tag in result.get("tags", [])[:4]
                if clean_text(str(tag), 30)
            ]

            if summary_pl:
                item["summary_pl"] = summary_pl
                item["tags"] = tags
                processed += 1
                print(f"[AI] {item['source']}: {item['title'][:70]}")
        except Exception as exc:
            print(f"[AI ERROR] {item['title'][:70]}: {exc}")

    print(f"[AI] Enriched {processed} items with {MODEL}")
    return processed


def write_feed(items: list[dict]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(items),
        "items": items,
    }
    with FEED_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[SAVE] {len(items)} unique items -> {FEED_PATH}")


def main():
    fresh = []
    for feed in FEEDS:
        fresh.extend(collect_feed(feed))

    items = merge_items(read_existing(), fresh)
    enrich_with_ai(items)
    write_feed(items)
    print(f"Done. Collected {len(fresh)} fresh items.")


if __name__ == "__main__":
    main()
