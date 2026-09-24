from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup
from google import genai
from google.genai import types

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from feeds import SOURCES, REDDIT_SUBREDDITS, REDDIT_KEYWORDS, YOUTUBE_CHANNELS

DATA_DIR = ROOT / "data"
FEED_PATH = DATA_DIR / "feed.json"
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
MODEL = os.environ.get("MYHUB_SUMMARY_MODEL", "gemini-3.5-flash-lite")
MAX_AI_ITEMS = int(os.environ.get("MYHUB_MAX_AI_ITEMS", "15"))
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
HEADERS = {"User-Agent":"Mozilla/5.0 (compatible; MyHub/0.5; +https://myhub.pythonanywhere.com)"}

def clean_text(value: str | None, max_length: int = 320) -> str:
    if not value:
        return ""
    value = html.unescape(TAG_RE.sub(" ", value))
    value = SPACE_RE.sub(" ", value).strip()
    if len(value) > max_length:
        value = value[: max_length - 1].rstrip() + "…"
    return value

def make_id(source: str, stable: str) -> str:
    return hashlib.sha256(f"{source}|{stable}".encode("utf-8")).hexdigest()

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

def collect_rss(source) -> list[dict]:
    parsed = feedparser.parse(source["url"], request_headers=HEADERS)
    if parsed.bozo and not parsed.entries:
        print(f"[ERROR] {source['name']}: {parsed.bozo_exception}")
        return []
    items = []
    for entry in parsed.entries[:50]:
        link = entry.get("link")
        title = clean_text(entry.get("title"), 220)
        if not link or not title:
            continue
        summary = entry.get("summary") or entry.get("description") or (entry.get("content") or [{}])[0].get("value", "")
        items.append({
            "id": make_id(source["name"], entry.get("id") or entry.get("guid") or link),
            "source": source["name"],
            "source_type": "news",
            "category": source["category"],
            "language": source["language"],
            "title": title,
            "summary": clean_text(summary),
            "url": link,
            "published_at": published_iso(entry),
        })
    print(f"[OK] {source['name']}: {len(items)} RSS items")
    return items

def collect_html(source) -> list[dict]:
    try:
        response = requests.get(source["url"], headers=HEADERS, timeout=20)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"[ERROR] {source['name']}: {exc}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    pattern = re.compile(source["link_pattern"])
    found = {}
    for a in soup.find_all("a", href=True):
        href = a.get("href","").strip()
        parsed = urlparse(href)
        path = parsed.path if parsed.scheme else href.split("?",1)[0]
        if not pattern.match(path):
            continue
        title = clean_text(a.get_text(" ", strip=True), 220)
        if len(title) < 18:
            continue
        url = urljoin(source["base_url"], href)
        found[url] = title

    now = datetime.now(timezone.utc).isoformat()
    items = [{
        "id": make_id(source["name"], url),
        "source": source["name"],
        "source_type": "news",
        "category": source["category"],
        "language": source["language"],
        "title": title,
        "summary": "",
        "summary_pl": "",
        "url": url,
        "published_at": now,
    } for url, title in list(found.items())[:30]]

    print(f"[OK] {source['name']}: {len(items)} HTML items")
    return items


def collect_reddit() -> list[dict]:
    items = []
    for index, subreddit in enumerate(REDDIT_SUBREDDITS):
        if index:
            # Reddit potrafi zwracać 429/403 przy kilku feedach odpytywanych seryjnie.
            time.sleep(3)
        url = f"https://www.reddit.com/r/{subreddit}/new/.rss"
        parsed = feedparser.parse(url, request_headers=HEADERS)
        if parsed.bozo and not parsed.entries:
            print(f"[WARN] Reddit r/{subreddit}: first attempt failed: {parsed.bozo_exception}; retrying")
            time.sleep(8)
            parsed = feedparser.parse(url, request_headers=HEADERS)
        if parsed.bozo and not parsed.entries:
            print(f"[ERROR] Reddit r/{subreddit}: {parsed.bozo_exception}")
            continue

        for entry in parsed.entries[:25]:
            link = entry.get("link")
            title = clean_text(entry.get("title"), 220)
            if not link or not title:
                continue

            body = clean_text(entry.get("summary") or entry.get("description"), 420)
            haystack = f"{title} {body}".lower()
            matched = []
            for rule in REDDIT_KEYWORDS:
                if subreddit not in rule["subreddits"]:
                    continue
                phrase = rule["phrase"]
                if phrase.lower() in haystack:
                    matched.append(phrase)

            items.append({
                "id": make_id(f"Reddit:{subreddit}", entry.get("id") or link),
                "source": f"r/{subreddit}",
                "source_type": "reddit",
                "category": "Reddit",
                "language": "en",
                "title": title,
                "summary": body,
                "url": link,
                "published_at": published_iso(entry),
                "matched_keywords": matched,
                "priority": bool(matched),
            })

        print(f"[OK] Reddit r/{subreddit}: {sum(1 for i in items if i['source'] == 'r/' + subreddit)} items")
    return items


def youtube_get(path: str, params: dict) -> dict:
    params = {**params, "key": YOUTUBE_API_KEY}
    response = requests.get(
        f"https://www.googleapis.com/youtube/v3/{path}",
        params=params,
        headers=HEADERS,
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def collect_youtube() -> list[dict]:
    if not YOUTUBE_API_KEY:
        print("[YT] YOUTUBE_API_KEY missing; skipping YouTube.")
        return []

    items = []
    for channel in YOUTUBE_CHANNELS:
        try:
            channel_data = youtube_get(
                "channels",
                {"part": "contentDetails", "forHandle": channel["handle"]},
            )
            channel_items = channel_data.get("items", [])
            if not channel_items:
                print(f"[YT ERROR] {channel['name']}: channel not found")
                continue

            uploads = (
                channel_items[0]
                .get("contentDetails", {})
                .get("relatedPlaylists", {})
                .get("uploads")
            )
            if not uploads:
                continue

            playlist = youtube_get(
                "playlistItems",
                {
                    "part": "snippet,contentDetails",
                    "playlistId": uploads,
                    "maxResults": 10,
                },
            )

            count = 0
            for entry in playlist.get("items", []):
                snippet = entry.get("snippet", {})
                video_id = entry.get("contentDetails", {}).get("videoId")
                title = clean_text(snippet.get("title"), 220)
                if not video_id or not title:
                    continue
                published = snippet.get("publishedAt") or datetime.now(timezone.utc).isoformat()
                items.append({
                    "id": make_id(f"YouTube:{channel['handle']}", video_id),
                    "source": channel["name"],
                    "source_type": "youtube",
                    "category": "YouTube",
                    "language": "pl",
                    "title": title,
                    "summary": clean_text(snippet.get("description"), 320),
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "published_at": published,
                    "thumbnail_url": (
                        snippet.get("thumbnails", {}).get("medium", {}).get("url")
                        or snippet.get("thumbnails", {}).get("default", {}).get("url", "")
                    ),
                })
                count += 1
            print(f"[OK] YouTube {channel['name']}: {count} items")
        except requests.RequestException as exc:
            print(f"[YT ERROR] {channel['name']}: {exc}")
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
        preserve = {}
        for key in ("summary_pl", "tags"):
            if previous.get(key):
                preserve[key] = previous[key]
        if previous.get("published_at") and item.get("language") == "pl":
            item["published_at"] = previous["published_at"]
        merged[item["id"]] = {**item, **preserve}
    return sorted(merged.values(), key=lambda item: item.get("published_at",""), reverse=True)[:350]

def enrich_with_ai(items: list[dict]) -> int:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[AI] GEMINI_API_KEY missing; skipping.")
        return 0

    client = genai.Client(api_key=api_key)
    processed = 0
    schema = {
        "type":"object",
        "properties":{
            "summary_pl":{"type":"string"},
            "tags":{"type":"array","items":{"type":"string"},"maxItems":4},
        },
        "required":["summary_pl","tags"],
    }

    for item in items:
        if processed >= MAX_AI_ITEMS:
            break
        if item.get("language") == "pl":
            continue
        if item.get("source_type") == "youtube":
            continue
        if item.get("source_type") == "reddit" and not item.get("priority"):
            continue
        if item.get("summary_pl"):
            continue

        source_text = item.get("summary","").strip() or "(Brak opisu w RSS — oprzyj się tylko na tytule.)"
        prompt = f"""Jesteś redaktorem osobistego agregatora newsów gamingowo-technologicznych.
Na podstawie WYŁĄCZNIE poniższego tytułu i opisu:
1. Napisz zwięzłe streszczenie po polsku w 1-2 zdaniach, maksymalnie 260 znaków.
2. Nie dopowiadaj faktów.
3. Dobierz 1-4 krótkie tagi.
Źródło: {item["source"]}
Tytuł: {item["title"]}
Opis: {source_text}"""
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
            tags = [clean_text(str(t),30) for t in result.get("tags",[])[:4] if clean_text(str(t),30)]
            if summary_pl:
                item["summary_pl"] = summary_pl
                item["tags"] = tags
                processed += 1
                print(f"[AI] {item['source']}: {item['title'][:65]}")
        except Exception as exc:
            print(f"[AI ERROR] {item['title'][:65]}: {exc}")
    print(f"[AI] Enriched {processed} EN items with {MODEL}")
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
    print(f"[SAVE] {len(items)} items -> {FEED_PATH}")

def main():
    fresh = []
    for source in SOURCES:
        if source["kind"] == "rss":
            fresh.extend(collect_rss(source))
        else:
            fresh.extend(collect_html(source))
    fresh.extend(collect_reddit())
    fresh.extend(collect_youtube())

    items = merge_items(read_existing(), fresh)
    enrich_with_ai(items)
    write_feed(items)
    print(f"Done. Collected {len(fresh)} fresh items.")

if __name__ == "__main__":
    main()
