"""Web app and Steam-ID queue; price collection runs in GitHub Actions."""
import hashlib
import json
import math
import re
import sqlite3
import threading
import unicodedata
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, jsonify, render_template, request, send_from_directory, url_for

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
FEED_PATH = BASE_DIR / "data" / "feed.json"
WATCHLIST_PATH = BASE_DIR / "data" / "game_watchlist.json"
HISTORY_PATH = BASE_DIR / "data" / "price_history.json"
TRACKED_PATH = BASE_DIR / "data" / "tracked_games.json"
TRACKING_DB = BASE_DIR / "data" / "tracking.db"
APP_VERSION = "2026.10.08.5"
PAGE_SIZE = 36
SECTIONS = {"news": "News", "reddit": "Reddit", "youtube": "YouTube", "deal": "Okazje"}
_feed_lock = threading.Lock()
_feed_cache = {"signature": None, "items": [], "updated_at": None, "error": None}


def safe_url(value):
    if not isinstance(value, str):
        return ""
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme in {"http", "https"} and parsed.netloc else ""
    except ValueError:
        return ""


def timestamp(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.replace(tzinfo=dt.tzinfo or timezone.utc).timestamp()
    except (ValueError, TypeError, OverflowError, OSError):
        return 0


def price_number(value):
    """Accept numbers or our exact PLN display format, never an arbitrary text price."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not re.fullmatch(r"\d+(?:[.,]\d{1,2})?(?: zł)?", value):
            return None
        value = value.removesuffix(" zł").replace(",", ".")
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (TypeError, ValueError):
        return None


def deal_signals(item):
    current = price_number(item.get("current_price", item.get("price")))
    historical = price_number(item.get("historical_low", item.get("historical_price")))
    target = price_number(item.get("target_price"))
    verified = item.get("active") is True and item.get("price_verified") is True and current is not None
    candidates = [price_number(item.get(key)) for key in ("retail_price_value", "keyshop_price_value", "retail_price", "keyshop_price")]
    candidates = [v for v in candidates if v is not None] or [current]
    low = bool(verified and historical is not None and any(v is not None and abs(v - historical) < 0.005 for v in candidates))
    # Legacy GG entries used priority for both the target and the historical low.
    budget = bool(verified and str(item.get("currency") or "PLN").upper() == "PLN" and ((target is not None and current <= target) or
                  (target is None and item.get("priority") is True and not low)))
    return {"current_price": current, "historical_low": historical,
            "within_target": budget, "is_historical_low": low, "deal_qualified": low or budget}


def normalize_item(raw):
    if not isinstance(raw, dict) or not raw.get("title") or not safe_url(raw.get("url")):
        return None
    if raw.get("source_type") == "deal" and raw.get("active") is False:
        return None
    item = dict(raw)
    for key in ("title", "summary", "summary_pl", "source", "category", "language"):
        item[key] = str(item.get(key) or "")
    kind = item.get("source_type")
    item["source_type"] = kind if isinstance(kind, str) and kind in SECTIONS else "news"
    item["id"] = str(item.get("id") or hashlib.sha256(item["url"].encode()).hexdigest())
    item["thumbnail_url"] = safe_url(item.get("thumbnail_url"))
    for key in ("tags", "matched_keywords"):
        values = item.get(key)
        item[key] = [str(v) for v in values[:8]] if isinstance(values, list) else []
    if item["source_type"] == "reddit":
        item["summary_pl"] = ""
    if item["source_type"] == "deal":
        item.update(deal_signals(item))
    return item


def load_feed():
    """Cache by file signature; retain the last good feed during interrupted uploads."""
    with _feed_lock:
        try:
            stat = FEED_PATH.stat()
            signature = (str(FEED_PATH), stat.st_mtime_ns, stat.st_size)
            if signature != _feed_cache["signature"]:
                payload = json.loads(FEED_PATH.read_text(encoding="utf-8"))
                if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
                    raise ValueError("Invalid feed structure")
                items = [item for raw in payload["items"] if (item := normalize_item(raw))]
                items = list({item["id"]: item for item in items}.values())
                items.sort(key=lambda item: timestamp(item.get("published_at")), reverse=True)
                _feed_cache.update(signature=signature, items=items,
                                   updated_at=payload.get("updated_at"), error=None)
            else:
                _feed_cache["error"] = None
        except (OSError, ValueError, TypeError) as exc:
            _feed_cache["error"] = type(exc).__name__
        return dict(_feed_cache)


def load_items():
    return load_feed()["items"]


def fold(value):
    value = unicodedata.normalize("NFKD", str(value).casefold().replace("ł", "l"))
    return "".join(char for char in value if not unicodedata.combining(char))


def read_json(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return fallback


def tracking_catalog():
    """Public Steam IDs only; personal selections never leave the browser."""
    metadata = read_json(TRACKED_PATH, {})
    metadata = metadata.get("games", []) if isinstance(metadata, dict) else []
    metadata = metadata if isinstance(metadata, list) else []
    known = {str(g.get("steam_app_id")): g for g in metadata if isinstance(g, dict)}
    # SQLite is runtime state and must never be replaced by a deployment upload.
    TRACKING_DB.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(TRACKING_DB, timeout=10)) as conn, conn:
        conn.execute("CREATE TABLE IF NOT EXISTS requests (app_id TEXT PRIMARY KEY)")
        ids = [r[0] for r in conn.execute("SELECT app_id FROM requests ORDER BY rowid LIMIT 100")]
    return [known.get(app_id, {"steam_app_id": int(app_id), "name": f"Steam {app_id}", "status": "pending"}) for app_id in dict.fromkeys([*known, *ids])][:100]


def steam_id(value):
    if not isinstance(value, str) or len(value) > 500:
        return None
    value = value.strip()
    if value.isascii() and value.isdigit() and 0 < int(value) <= 4294967295:
        return str(int(value))
    try:
        url = urlsplit(value)
        match = re.match(r"^/app/(\d+)(?:/|$)", url.path)
        if url.scheme == "https" and url.hostname == "store.steampowered.com" and not url.username and not url.password and url.port in (None, 443) and match:
            return steam_id(match[1])
    except ValueError:
        pass
    return None


@app.route("/api/tracking", methods=["GET", "POST"])
def tracking():
    if request.method == "GET":
        return jsonify(games=tracking_catalog())
    if request.headers.get("Origin") not in {request.host_url.rstrip("/"), f"https://{request.host}"} or not request.is_json:
        return jsonify(error="Nieprawidłowe żądanie."), 403
    if request.content_length is None or request.content_length > 2048:
        return jsonify(error="Żądanie jest za duże."), 413
    payload = request.get_json(silent=True)
    app_id = steam_id(payload.get("steam") if isinstance(payload, dict) else None)
    if not app_id:
        return jsonify(error="Wklej link https://store.steampowered.com/app/… albo poprawny Steam App ID."), 400
    defaults = read_json(WATCHLIST_PATH, {})
    defaults = defaults.get("games", []) if isinstance(defaults, dict) else []
    defaults = [g for g in defaults if isinstance(g, dict)] if isinstance(defaults, list) else []
    known = next((g for g in [*defaults, *tracking_catalog()] if str(g.get("steam_app_id")) == app_id), None)
    if known:
        if known.get("status") == "rejected":
            return jsonify(error="To nie jest samodzielna gra na PC (Windows) albo identyfikator nie istnieje."), 400
        return jsonify(steam_app_id=app_id, status=known.get("status", "ready"))
    if len(tracking_catalog()) >= 100:
        return jsonify(error="Limit nowych gier został osiągnięty."), 429
    with closing(sqlite3.connect(TRACKING_DB, timeout=10)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0] >= 100:
            return jsonify(error="Limit nowych gier został osiągnięty."), 429
        conn.execute("INSERT OR IGNORE INTO requests VALUES (?)", (app_id,))
    return jsonify(steam_app_id=app_id, status="pending"), 202


def game_matches(item, game):
    if str(item.get("steam_app_id") or "") == game["id"]:
        return True
    title = fold(item["title"])
    name = fold(game["name"])
    # A title mention is a link to a discussion, never proof of compatibility.
    return bool(re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", title))


def game_catalog(all_items):
    payload = read_json(WATCHLIST_PATH, {})
    raw_games = payload.get("games", []) if isinstance(payload, dict) else []
    raw_games = [dict(g, default=True) for g in raw_games if isinstance(g, dict)] if isinstance(raw_games, list) else []
    extra = tracking_catalog()
    raw_games += [dict(g, default=False) for g in extra]
    history = read_json(HISTORY_PATH, {})
    history = history.get("games", {}) if isinstance(history, dict) else {}
    prices = {str(i.get("steam_app_id")): i for i in all_items if i["source_type"] == "deal" and
              i["source"] == "GG.deals" and i.get("active") is True and i.get("price_verified") is True}
    games = []
    seen = set()
    posts = [(i, fold(i["title"])) for i in all_items if i["source_type"] != "deal"]
    for raw in raw_games if isinstance(raw_games, list) else []:
        if not isinstance(raw, dict):
            continue
        try:
            app_id = str(int(raw["steam_app_id"]))
        except (ValueError, TypeError, KeyError):
            continue
        if int(app_id) <= 0 or app_id in seen:
            continue
        seen.add(app_id)
        game = {"id": app_id, "name": str(raw.get("name") or f"Steam {app_id}"),
                "default": raw.get("default", False), "watch_status": raw.get("status", "ready"),
                "price": prices.get(app_id), "history": history.get(app_id, []) if isinstance(history, dict) else [],
                "url": f"https://store.steampowered.com/app/{app_id}/"}
        game["history"] = [p for p in game["history"][-120:] if isinstance(p, dict) and
                           timestamp(p.get("at")) and price_number(p.get("current")) is not None] if isinstance(game["history"], list) else []
        pattern = re.compile(r"(?<!\w)" + re.escape(fold(game["name"])) + r"(?!\w)")
        related = [i for i, title in posts if str(i.get("steam_app_id") or "") == app_id or pattern.search(title)]
        game["related_count"] = len(related)
        announcements = [i.get("published_at") for i in related if i.get("is_game_update") and str(i.get("steam_app_id")) == app_id]
        game["latest_announcement"] = max(announcements, key=timestamp) if announcements else None
        games.append(game)
    return games


def query_context():
    feed = load_feed()
    all_items = feed["items"]
    section = request.args.get("section", "news").strip().lower()
    section = section if section in {*SECTIONS, "priority"} else "news"
    language = request.args.get("lang", "").strip().lower()
    language = language if language in {"pl", "en"} else ""
    category = request.args.get("category", "").strip()[:80]
    source = request.args.get("source", "").strip()[:120]
    query = request.args.get("q", "").strip()[:200]
    sort = request.args.get("sort", "newest")
    sort = sort if sort in {"newest", "priority"} else "newest"
    view = request.args.get("view", "feed")
    view = view if view in {"saved", "games", "hardware", "tracking"} else "feed"
    games = game_catalog(all_items) if request.path != "/api/feed" or view == "games" or section == "deal" else []
    game_id = request.args.get("game", "")
    selected_game = next((g for g in games if g["id"] == game_id), None) if view == "games" else None
    page = max(1, min(request.args.get("page", 1, type=int) or 1, 1000))
    items = all_items
    if section == "priority":
        items = [i for i in items if i.get("priority") or i["matched_keywords"]]
    elif section:
        items = [i for i in items if i["source_type"] == section]
    if section == "deal":
        items = [g["price"] or normalize_item({"id": f"steam-price-{g['id']}", "title": g["name"],
                 "url": g["url"], "source": "GG.deals", "source_type": "deal", "language": "pl",
                 "steam_app_id": g["id"], "watch_status": g["watch_status"], "platform_label": "PC · Steam"})
                 for g in games if g["watch_status"] != "rejected"]
        if request.args.get("low") == "1":
            items = [i for i in items if i.get("is_historical_low")]
    if category:
        items = [i for i in items if i["category"].casefold() == category.casefold()]
    if language:
        items = [i for i in items if i["language"].lower() == language]
    if source:
        items = [i for i in items if i["source"] == source]
    if query:
        words = fold(query).split()
        items = [i for i in items if all(word in fold(" ".join(
            [i["title"], i["summary"], i["summary_pl"], i["source"],
             *i["tags"], *i["matched_keywords"]])) for word in words)]
    if sort == "priority":
        items = sorted(items, key=lambda i: bool(i.get("priority") or i["matched_keywords"]), reverse=True)
    home = False
    if selected_game:
        items = [i for i in all_items if i["source_type"] != "deal" and game_matches(i, selected_game)]
    groups = {key: sorted({i["source"] for i in all_items if i["source_type"] == key}, key=str.casefold)
              for key in SECTIONS}
    filtered_count = len(items)
    offset = (page - 1) * PAGE_SIZE
    show_items = view == "feed" or selected_game is not None
    offers = section == "deal" and view == "feed"
    return dict(items=(items if offers else items[offset:offset + PAGE_SIZE]) if show_items else [],
                total_count=len(all_items), filtered_count=filtered_count,
                has_more=offset + PAGE_SIZE < filtered_count and show_items and not offers, page=page,
                low_only=request.args.get("low") == "1", offers=offers,
                section=section, section_title=(selected_game["name"] if selected_game else "Edytuj śledzone gry" if view == "tracking" else "Twoje gry" if view == "games" else "Twój sprzęt" if view == "hardware" else SECTIONS.get(section, "Dla Ciebie")),
                language=language, category=category, source=source, query=query, sort=sort, view=view,
                available_source_groups=groups,
                categories=sorted({i["category"] for i in all_items if i["category"]}),
                section_counts={key: sum(i["source_type"] == key for i in all_items) for key in SECTIONS},
                priority_count=sum(bool(i.get("priority") or i["matched_keywords"]) for i in all_items),
                games=games, selected_game=selected_game, home=home,
                hub_games=[{k: v for k, v in g.items() if k != "history"} for g in games],
                hardware_items=[i for i in all_items if i["source_type"] != "deal" and any(term in fold(i["title"] + " " + i["source"] + " " + " ".join(i["matched_keywords"])) for term in ("legion go", "legiongo", "z1 extreme", "z1e", "steam deck", "steamdeck", "rog ally"))][:30],
                visit_items=[{"id": i["id"], "date": i.get("first_seen_at") or i.get("published_at"), "kind": i["source_type"]} for i in all_items if i["source_type"] != "deal" or i.get("deal_qualified")],
                updated_at=feed["updated_at"], feed_error=feed["error"], app_version=APP_VERSION)


@app.template_global()
def filter_url(**changes):
    params = {k: v for k, v in request.args.items()
              if k in {"section", "lang", "category", "source", "q", "sort", "view", "game", "low"}}
    for key, value in changes.items():
        if value:
            params[key] = value
        else:
            params.pop(key, None)
    return url_for("index", **params)


@app.route("/")
def index():
    return render_template("index.html", **query_context())


@app.route("/api/feed")
def api_feed():
    context = query_context()
    return jsonify(html=render_template("_cards.html", **context), items=context["items"],
                   count=context["filtered_count"], has_more=context["has_more"], page=context["page"],
                   updated_at=context["updated_at"], degraded=bool(context["feed_error"]))


@app.route("/service-worker.js")
def service_worker():
    response = send_from_directory(app.static_folder, "service-worker.js", mimetype="application/javascript")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Service-Worker-Allowed"] = "/"
    return response


@app.route("/offline")
def offline():
    return render_template("offline.html", app_version=APP_VERSION)


@app.route("/health")
def health():
    feed = load_feed()
    items = feed["items"]
    return {"status": "degraded" if feed["error"] else "ok", "items": len(items),
            "pl": sum(i["language"] == "pl" for i in items),
            "en": sum(i["language"] == "en" for i in items),
            "updated_at": feed["updated_at"], "version": APP_VERSION}, 503 if feed["error"] else 200


@app.after_request
def response_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if request.path in {"/", "/api/feed", "/api/tracking", "/health"}:
        response.headers["Cache-Control"] = "no-cache"
    return response


if __name__ == "__main__":
    app.run()
