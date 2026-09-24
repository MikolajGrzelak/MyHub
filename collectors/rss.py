from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlparse

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
DEAL_KEYWORDS_PATH = DATA_DIR / "deal_keywords.json"
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
MODEL = os.environ.get("MYHUB_SUMMARY_MODEL", "gemini-3.5-flash-lite")
MAX_AI_ITEMS = int(os.environ.get("MYHUB_MAX_AI_ITEMS", "15"))
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
HEADERS = {"User-Agent":"Mozilla/5.0 (compatible; MyHub/0.5; +https://myhub.pythonanywhere.com)"}

HARDWARE_TERMS = [
    "gpu", "cpu", "apu", "ryzen", "radeon", "geforce", "nvidia", "amd", "intel",
    "snapdragon", "mediatek", "ram", "vram", "ssd", "nvme", "pcie", "motherboard",
    "płyta główna", "procesor", "karta graficzna", "sterownik", "driver", "bios",
    "firmware", "laptop", "monitor", "oled", "mini-led", "handheld", "legion go",
    "steam deck", "rog ally", "xbox handheld", "playstation handheld", "console",
    "konsola", "windows", "linux", "steamos", "android", "iphone", "ipad", "macbook",
    "wi-fi", "wifi", "router", "thunderbolt", "usb4", "egpu"
]

GAME_NEWS_TERMS = [
    "premiera", "release", "data premiery", "trailer", "zwiastun", "gameplay",
    "rozgrywka", "patch", "łatka", "aktualizacja", "update", "dlc", "dodatek",
    "remaster", "remake", "demo", "beta", "sequel", "kontynuacja", "zapowiedz",
    "zapowiedź", "announced", "launch", "opóźn", "delay", "wymagania", "requirements",
    "fps", "performance", "wydajność", "wersja", "port", "crossplay", "cross-save",
    "tryb", "mode", "expansion", "season", "sezon", "patch notes"
]

OFFTOPIC_TERMS = [
    "youtuber", "streamer", "influencer", "promocję kanału", "kanału o",
    "zarobki", "przychody", "akcje spółki", "giełda", "ceo", "pozew", "sąd",
    "afera", "kontrowers", "cosplay", "film", "serial", "anime", "merch",
    "gadżet kolekcjonerski", "twitter", "x.com", "tiktok", "instagram",
    "wiek graczy", "age verification", "branża", "gaming industry"
]


def is_relevant_news(item: dict) -> bool:
    if item.get("source_type", "news") != "news":
        return True

    text = f"{item.get('title','')} {item.get('summary','')}".lower()

    if any(term in text for term in OFFTOPIC_TERMS):
        return False

    if item.get("category") == "Tech":
        return any(term in text for term in HARDWARE_TERMS)

    if item.get("category") == "Gaming":
        return any(term in text for term in GAME_NEWS_TERMS)

    return False


def clean_cdaction_title(text: str) -> str:
    # This is only a fallback for listing-card text. The canonical title is
    # taken from the article page below.
    text = clean_text(text, 500)
    text = re.sub(r"^Newsy(?:\s+\d+)?\s+", "", text, flags=re.I)
    text = re.sub(
        r"\s+(?:Przed chwilą|\d+\s+minut(?:a|y)?\s+temu|\d+\s+godzin(?:a|y)?\s+temu|\d{2}\.\d{2}\.\d{4}).*$",
        "",
        text,
        flags=re.I,
    )
    return text.strip()


def extract_article_title(soup: BeautifulSoup) -> str | None:
    # Prefer explicit article metadata, then the page H1.
    for attrs in (
        {"property": "og:title"},
        {"name": "twitter:title"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            title = clean_text(tag.get("content"), 500)
            if title:
                return re.sub(r"\s*[|–-]\s*CD-Action.*$", "", title, flags=re.I).strip()

    h1 = soup.find("h1")
    if h1:
        title = clean_text(h1.get_text(" ", strip=True), 500)
        if title:
            return title
    return None

def clean_ppe_title(text: str) -> str:
    text = clean_text(text, 360)

    # PPE listing anchors often contain section/comment counters before the real title.
    # Examples: "Gry 29V 0 Gry 29V 0 <headline> Dzisiaj, 14:41"
    text = re.sub(
        r"^(?:(?:Gry|Filmy i seriale|Technologie|Publicystyka|Promocje)\s+\d+V?\s+\d+\s+){1,3}",
        "",
        text,
        flags=re.I,
    )

    # PPE also emits variants such as "Gry 532V Pilne 3 Gry 532V Pilne 3 ...".
    # Strip repeated category + vote counter + optional label + counter blocks.
    prefix = re.compile(
        r"^(?:Gry|Filmy i seriale|Technologie|Publicystyka|Promocje)"
        r"\s+\d+V?(?:\s+[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż-]+)?\s+\d+\s+",
        flags=re.I,
    )
    for _ in range(4):
        cleaned = prefix.sub("", text, count=1)
        if cleaned == text:
            break
        text = cleaned

    # Date/time belongs in published_at, never in the headline.
    text = re.sub(
        r"\s+(?:Dzisiaj|Wczoraj)\s*,?\s*\d{1,2}:\d{2}\s*$",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\s+\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?\s*,?\s*\d{1,2}:\d{2}\s*$",
        "",
        text,
        flags=re.I,
    )
    return text.strip()


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
    # feedparser already normalizes Atom/RSS dates when possible.
    for field in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = entry.get(field)
        if parsed:
            try:
                dt = datetime(*parsed[:6], tzinfo=timezone.utc)
                return dt.isoformat()
            except (TypeError, ValueError):
                pass

    # Some Atom feeds (including Reddit) expose ISO-8601 strings rather than RFC 2822.
    for field in ("published", "updated", "created"):
        raw = entry.get(field)
        if not raw:
            continue

        raw = str(raw).strip()
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except ValueError:
            pass

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


def _parse_datetime_value(raw: str) -> str | None:
    raw = str(raw).strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def _find_json_date(value) -> str | None:
    if isinstance(value, dict):
        for key in ("datePublished", "dateCreated", "uploadDate", "dateModified"):
            if value.get(key):
                parsed = _parse_datetime_value(value[key])
                if parsed:
                    return parsed
        for child in value.values():
            parsed = _find_json_date(child)
            if parsed:
                return parsed
    elif isinstance(value, list):
        for child in value:
            parsed = _find_json_date(child)
            if parsed:
                return parsed
    return None


def _relative_time_to_iso(text: str) -> str | None:
    lowered = text.lower()
    now = datetime.now(timezone.utc)

    patterns = [
        (r"(\d+)\s*min(?:ut|uty|uta)?\s*temu", 60),
        (r"(\d+)\s*godz(?:in|iny|ina)?\s*temu", 3600),
        (r"(\d+)\s*dni?\s*temu", 86400),
        (r"(\d+)\s*minutes?\s*ago", 60),
        (r"(\d+)\s*hours?\s*ago", 3600),
        (r"(\d+)\s*days?\s*ago", 86400),
    ]
    for pattern, seconds in patterns:
        match = re.search(pattern, lowered)
        if match:
            delta = int(match.group(1)) * seconds
            return datetime.fromtimestamp(now.timestamp() - delta, tz=timezone.utc).isoformat()

    if "przed chwilą" in lowered or "just now" in lowered:
        return now.isoformat()
    return None


def extract_published_from_soup(soup: BeautifulSoup) -> str | None:
    # Common OpenGraph/article metadata.
    for attrs in (
        {"property": "article:published_time"},
        {"name": "article:published_time"},
        {"property": "og:published_time"},
        {"name": "date"},
        {"itemprop": "datePublished"},
        {"name": "pubdate"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            parsed = _parse_datetime_value(tag.get("content"))
            if parsed:
                return parsed

    # <time datetime="...">
    for tag in soup.find_all("time"):
        raw = (tag.get("datetime") or tag.get("content") or "").strip()
        parsed = _parse_datetime_value(raw)
        if parsed:
            return parsed

    # JSON-LD / embedded structured data.
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        parsed = _find_json_date(payload)
        if parsed:
            return parsed

    # Last resort: source-visible relative time (e.g. "9 min temu").
    return _relative_time_to_iso(clean_text(soup.get_text(" ", strip=True), 12000))

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
        raw_title = clean_text(a.get_text(" ", strip=True), 360)
        title = raw_title
        listing_published_at = _relative_time_to_iso(raw_title)
        if source["name"] == "PPE":
            today_match = re.search(r"Dzisiaj\s*,?\s*(\d{1,2}):(\d{2})", raw_title, flags=re.I)
            yesterday_match = re.search(r"Wczoraj\s*,?\s*(\d{1,2}):(\d{2})", raw_title, flags=re.I)
            if today_match or yesterday_match:
                m = today_match or yesterday_match
                local_now = datetime.now().astimezone()
                local_date = local_now.date()
                if yesterday_match:
                    local_date = datetime.fromtimestamp(local_now.timestamp() - 86400).date()
                local_dt = datetime.combine(local_date, datetime.min.time(), tzinfo=local_now.tzinfo).replace(
                    hour=int(m.group(1)), minute=int(m.group(2))
                )
                listing_published_at = local_dt.astimezone(timezone.utc).isoformat()
        if source["name"] == "CD-Action":
            title = clean_cdaction_title(title)
        elif source["name"] == "PPE":
            title = clean_ppe_title(title)
        if len(title) < 18:
            continue
        url = urljoin(source["base_url"], href)
        found[url] = {"title": title, "published_at": listing_published_at}

    urls = list(found)[:30]
    detail_pages = _parallel_fetch(urls, workers=8)

    items = []
    for url in urls:
        meta = found[url]
        title = meta["title"]
        body = detail_pages.get(url)
        published_at = None
        summary = ""
        if body:
            detail_soup = BeautifulSoup(body, "html.parser")
            published_at = extract_published_from_soup(detail_soup) or meta.get("published_at")

            if source["name"] == "CD-Action":
                canonical_title = extract_article_title(detail_soup)
                if canonical_title:
                    title = canonical_title

            description = detail_soup.find("meta", attrs={"name": "description"})
            if description and description.get("content"):
                summary = clean_text(description.get("content"), 320)

        items.append({
            "id": make_id(source["name"], url),
            "source": source["name"],
            "source_type": "news",
            "category": source["category"],
            "language": source["language"],
            "title": title,
            "summary": summary,
            "summary_pl": "",
            "url": url,
            "published_at": published_at or meta.get("published_at"),
        })

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



def read_deal_keywords() -> list[str]:
    try:
        payload = json.loads(DEAL_KEYWORDS_PATH.read_text(encoding="utf-8"))
        return [
            clean_text(str(value), 80)
            for value in payload.get("keywords", [])
            if clean_text(str(value), 80)
        ]
    except (OSError, json.JSONDecodeError):
        return []


def looks_inactive(text: str) -> bool:
    lowered = text.lower()
    markers = [
        "okazja zakończona",
        "ta okazja wygasła",
        "oferta wygasła",
        "promocja zakończona",
        "zakończono",
        "wygasła",
        "expired",
    ]
    return any(marker in lowered for marker in markers)


def extract_pepper_current_price(soup: BeautifulSoup, title: str = "") -> str:
    # Pepper pages contain many unrelated prices (recommendations, ads, widgets).
    # Only inspect the main deal/article area and prefer visible live-price text.
    root = (
        soup.find("article")
        or soup.select_one('[data-t="deal"]')
        or soup.select_one("main")
        or soup
    )

    # First inspect elements whose semantics/classes explicitly indicate a deal price.
    selectors = [
        '[data-t="deal-price"]',
        '[data-t*="price"]',
        '[itemprop="price"]',
        '[class*="thread-price"]',
        '[class*="deal-price"]',
        '[class*="price"]',
    ]
    old_words = ("old", "rrp", "list", "strike", "original", "before", "previous", "regular", "line-through")

    for selector in selectors:
        for tag in root.select(selector):
            attrs = " ".join(tag.get("class", [])) + " " + str(tag.get("data-t", "")) + " " + str(tag.get("style", ""))
            if any(word in attrs.lower() for word in old_words):
                continue
            if tag.name in {"s", "del"} or tag.find_parent(["s", "del"]):
                continue
            raw = tag.get("content") or tag.get("value") or tag.get_text(" ", strip=True)
            if not raw:
                continue
            matches = re.findall(r"(?<!\d)(\d{1,5}(?:[ .]\d{3})*(?:[,.]\d{1,2})?)\s*zł", str(raw), flags=re.I)
            if matches:
                return f"{matches[0]} zł"
            if re.fullmatch(r"\s*\d+(?:[.,]\d{1,2})?\s*", str(raw)):
                return f"{str(raw).strip().replace('.', ',')} zł"

    # Pepper reliably exposes the deal's live price in the page title/OG metadata
    # on many layouts. These are safer than scanning arbitrary JSON.
    for tag in [
        soup.find("meta", attrs={"property": "og:title"}),
        soup.find("meta", attrs={"name": "twitter:title"}),
        soup.find("title"),
    ]:
        if not tag:
            continue
        raw = tag.get("content") if tag.name == "meta" else tag.get_text(" ", strip=True)
        if not raw:
            continue
        matches = re.findall(r"(?<!\d)(\d{1,5}(?:[ .]\d{3})*(?:[,.]\d{1,2})?)\s*zł", raw, flags=re.I)
        if matches:
            return f"{matches[0]} zł"

    # Last resort: look near the H1 only, not across the whole page.
    h1 = soup.find("h1")
    if h1:
        container = h1
        for _ in range(4):
            if container.parent:
                container = container.parent
        local = BeautifulSoup(str(container), "html.parser")
        for tag in local.find_all(["s", "del"]):
            tag.decompose()
        for tag in local.find_all(style=re.compile(r"line-through", re.I)):
            tag.decompose()
        text = clean_text(local.get_text(" ", strip=True), 12000)
        matches = re.findall(r"(?<!\d)(\d{1,5}(?:[ .]\d{3})*(?:[,.]\d{1,2})?)\s*zł", text, flags=re.I)
        if matches:
            return f"{matches[0]} zł"

    return ""


def extract_price_from_soup(soup: BeautifulSoup) -> str:
    # 1) Prefer schema.org Offer data. Pepper often exposes the live price here
    # even when the UI also shows an old crossed-out price.
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue

        stack = payload if isinstance(payload, list) else [payload]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
                continue
            if not isinstance(node, dict):
                continue

            node_type = str(node.get("@type", "")).lower()
            if node_type in {"offer", "aggregateoffer", "product"}:
                candidate = node.get("price") or node.get("lowPrice")
                if candidate is None and isinstance(node.get("offers"), dict):
                    candidate = node["offers"].get("price") or node["offers"].get("lowPrice")
                if candidate is not None:
                    value = str(candidate).strip().replace(".", ",")
                    if re.fullmatch(r"\d+(?:,\d{1,2})?", value):
                        return f"{value} zł"

            stack.extend(node.values())

    # 2) Pepper's page state can contain the price in JSON even if there is no
    # convenient visible selector.
    raw_html = str(soup)
    json_patterns = [
        r'"(?:dealPrice|currentPrice|price)"\s*:\s*"?(\d+(?:[.,]\d{1,2})?)"?',
        r'"price"\s*:\s*\{\s*"amount"\s*:\s*"?(\d+(?:[.,]\d{1,2})?)"?',
    ]
    for pattern in json_patterns:
        match = re.search(pattern, raw_html, flags=re.I)
        if match:
            return f"{match.group(1).replace('.', ',')} zł"

    # 3) Prefer a single visible current-price element and reject anything
    # explicitly styled/marked as old, previous or crossed out.
    selectors = [
        '[itemprop="price"]',
        'meta[property="product:price:amount"]',
        'meta[property="og:price:amount"]',
        '[data-t*="price"]',
        '[class*="price"]',
    ]
    for selector in selectors:
        for tag in soup.select(selector):
            raw = tag.get("content") or tag.get("value") or tag.get_text(" ", strip=True)
            if not raw:
                continue
            classes = " ".join(tag.get("class", []))
            style = tag.get("style", "")
            attrs_text = f"{classes} {style} {tag.get('data-t','')} {tag.get('aria-label','')}".lower()
            if any(word in attrs_text for word in (
                "old", "rrp", "list", "strike", "original", "before",
                "previous", "regular", "line-through"
            )):
                continue
            if tag.name in {"s", "del"} or tag.find_parent(["s", "del"]):
                continue

            prices = re.findall(r"\d{1,5}(?:[ .]\d{3})*(?:[,.]\d{1,2})?\s*zł", clean_text(str(raw), 300), flags=re.I)
            if prices:
                return clean_text(prices[0], 40)

            numeric = re.fullmatch(r"\s*(\d+(?:[.,]\d{1,2})?)\s*", str(raw))
            if numeric:
                return f"{numeric.group(1).replace('.', ',')} zł"

    # 4) Final Pepper-friendly fallback. Remove likely old-price elements and
    # take the first remaining PLN amount; the live price is displayed first.
    fallback = BeautifulSoup(str(soup), "html.parser")
    for tag in fallback.find_all(["s", "del"]):
        tag.decompose()
    for tag in fallback.find_all(style=re.compile(r"line-through", re.I)):
        tag.decompose()
    for tag in fallback.find_all(class_=re.compile(r"(old|rrp|previous|original|regular).*price|price.*(old|rrp|previous|original|regular)", re.I)):
        tag.decompose()

    text = clean_text(fallback.get_text(" ", strip=True), 50000)
    prices = re.findall(r"\d{1,5}(?:[ .]\d{3})*(?:[,.]\d{1,2})?\s*zł", text, flags=re.I)
    return clean_text(prices[0], 40) if prices else ""

def extract_price(text: str) -> str:
    patterns = [
        r"(\d{1,3}(?:[ .]\d{3})*(?:[,.]\d{1,2})?\s*zł)",
        r"(\d+(?:[,.]\d{1,2})?\s*zł)",
        r"(\$\s*\d[\d\s.,]*)",
        r"(\d[\d\s.,]*\s*€)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return clean_text(match.group(1), 40)
    return ""

def extract_temperature(text: str) -> str:
    match = re.search(r"(-?\d{1,5})\s*°", text)
    return match.group(1) if match else ""



def _fetch_html(url: str, timeout: int = 15) -> tuple[str, str]:
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return url, response.text


def _parallel_fetch(urls: list[str], workers: int = 6) -> dict[str, str]:
    results = {}
    unique_urls = list(dict.fromkeys(urls))
    if not unique_urls:
        return results

    with ThreadPoolExecutor(max_workers=min(workers, len(unique_urls))) as pool:
        futures = {pool.submit(_fetch_html, url): url for url in unique_urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                _, body = future.result()
                results[url] = body
            except requests.RequestException as exc:
                print(f"[DEAL WARN] {url}: {exc}")
    return results


def collect_pepper_deals(keywords: list[str]) -> list[dict]:
    search_urls = {
        f"https://www.pepper.pl/search?q={quote_plus(keyword)}": keyword
        for keyword in keywords
    }
    search_pages = _parallel_fetch(list(search_urls), workers=6)

    found = {}
    for search_url, body in search_pages.items():
        keyword = search_urls[search_url]
        soup = BeautifulSoup(body, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if "/promocje/" not in href:
                continue
            url = urljoin("https://www.pepper.pl", href)
            title = clean_text(a.get_text(" ", strip=True), 220)
            if len(title) < 12:
                continue
            meta = found.setdefault(url, {"title": title, "keywords": []})
            if keyword not in meta["keywords"]:
                meta["keywords"].append(keyword)

    detail_urls = list(found)[:50]
    detail_pages = _parallel_fetch(detail_urls, workers=8)

    items = []
    now = datetime.now(timezone.utc).isoformat()
    for url in detail_urls:
        body = detail_pages.get(url)
        if not body:
            continue
        page = BeautifulSoup(body, "html.parser")
        text = clean_text(page.get_text(" ", strip=True), 5000)
        if looks_inactive(text):
            continue

        meta = found[url]
        h1 = page.find("h1")
        title = clean_text(h1.get_text(" ", strip=True) if h1 else meta["title"], 220)
        published_at = extract_published_from_soup(page) or now
        items.append({
            "id": make_id("Pepper", url),
            "source": "Pepper",
            "source_type": "deal",
            "category": "Okazje",
            "language": "pl",
            "title": title,
            "summary": "",
            "url": url,
            "published_at": published_at,
            "matched_keywords": meta["keywords"],
            "price": extract_pepper_current_price(page, title),
            "temperature": extract_temperature(text),
            "active": True,
        })

    print(f"[OK] Pepper: {len(items)} active deals from {len(found)} candidates")
    return items


def collect_lowcychin_deals(keywords: list[str]) -> list[dict]:
    search_urls = {
        f"https://www.lowcychin.pl/?s={quote_plus(keyword)}": keyword
        for keyword in keywords
    }
    search_pages = _parallel_fetch(list(search_urls), workers=6)

    found = {}
    blocked_paths = ("/category/", "/tag/", "/author/", "/page/", "/kontakt", "/regulamin")

    for search_url, body in search_pages.items():
        keyword = search_urls[search_url]
        soup = BeautifulSoup(body, "html.parser")
        for heading in soup.find_all(["h2", "h3"]):
            a = heading.find("a", href=True)
            if not a:
                continue
            url = urljoin("https://www.lowcychin.pl", a["href"])
            parsed = urlparse(url)
            if parsed.netloc not in {"lowcychin.pl", "www.lowcychin.pl"}:
                continue
            if any(part in parsed.path for part in blocked_paths):
                continue
            title = clean_text(a.get_text(" ", strip=True), 220)
            if len(title) < 12:
                continue
            meta = found.setdefault(url, {"title": title, "keywords": []})
            if keyword not in meta["keywords"]:
                meta["keywords"].append(keyword)

    detail_urls = list(found)[:50]
    detail_pages = _parallel_fetch(detail_urls, workers=8)

    items = []
    now = datetime.now(timezone.utc).isoformat()
    for url in detail_urls:
        body = detail_pages.get(url)
        if not body:
            continue
        page = BeautifulSoup(body, "html.parser")
        text = clean_text(page.get_text(" ", strip=True), 5000)
        if looks_inactive(text):
            continue

        meta = found[url]
        h1 = page.find("h1")
        title = clean_text(h1.get_text(" ", strip=True) if h1 else meta["title"], 220)
        published_at = extract_published_from_soup(page) or now
        items.append({
            "id": make_id("LowcyChin", url),
            "source": "ŁowcyChin",
            "source_type": "deal",
            "category": "Okazje",
            "language": "pl",
            "title": title,
            "summary": "",
            "url": url,
            "published_at": published_at,
            "matched_keywords": meta["keywords"],
            "price": extract_price_from_soup(page),
            "active": True,
        })

    print(f"[OK] ŁowcyChin: {len(items)} active deals from {len(found)} candidates")
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
    # Deals are ephemeral: only active deals seen in the current run survive.
    merged = {
        item["id"]: item
        for item in existing
        if item.get("source_type") != "deal"
    }
    now = datetime.now(timezone.utc).isoformat()
    for item in fresh:
        previous = merged.get(item["id"], {})
        preserve = {}
        for key in ("summary_pl", "tags"):
            if previous.get(key):
                preserve[key] = previous[key]

        # Always prefer the publication date from the source.
        # If a scraper could not read it this run, keep the previous source date;
        # only brand-new undated items fall back to first-seen time.
        if not item.get("published_at"):
            item["published_at"] = previous.get("published_at") or now

        merged[item["id"]] = {**item, **preserve}

    return sorted(
        merged.values(),
        key=lambda item: item.get("published_at") or "",
        reverse=True,
    )[:450]

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
        # AI translation/summaries are only for news. Reddit and YouTube stay verbatim.
        if item.get("source_type", "news") != "news":
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

    deal_keywords = read_deal_keywords()
    fresh.extend(collect_pepper_deals(deal_keywords))
    fresh.extend(collect_lowcychin_deals(deal_keywords))

    items = merge_items(read_existing(), fresh)
    before_filter = len(items)
    items = [item for item in items if is_relevant_news(item)]
    print(f"[FILTER] kept {len(items)}/{before_filter} items after relevance filtering")
    enrich_with_ai(items)
    write_feed(items)
    print(f"Done. Collected {len(fresh)} fresh items.")

if __name__ == "__main__":
    main()
