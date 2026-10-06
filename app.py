"""Read-only web app; collection runs separately in GitHub Actions."""
import hashlib
import json
import threading
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, jsonify, render_template, request, send_from_directory, url_for

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
FEED_PATH = BASE_DIR / "data" / "feed.json"
APP_VERSION = "2026.10.06.1"
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


def query_context():
    feed = load_feed()
    all_items = feed["items"]
    section = request.args.get("section", "").strip().lower()
    section = section if section in {*SECTIONS, "priority"} else ""
    language = request.args.get("lang", "").strip().lower()
    language = language if language in {"pl", "en"} else ""
    category = request.args.get("category", "").strip()[:80]
    source = request.args.get("source", "").strip()[:120]
    query = request.args.get("q", "").strip()[:200]
    sort = request.args.get("sort", "newest")
    sort = sort if sort in {"newest", "priority"} else "newest"
    view = "saved" if request.args.get("view") == "saved" else "feed"
    page = max(1, min(request.args.get("page", 1, type=int) or 1, 1000))
    items = all_items
    if section == "priority":
        items = [i for i in items if i.get("priority") or i["matched_keywords"]]
    elif section:
        items = [i for i in items if i["source_type"] == section]
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
    groups = {key: sorted({i["source"] for i in all_items if i["source_type"] == key}, key=str.casefold)
              for key in SECTIONS}
    filtered_count = len(items)
    offset = (page - 1) * PAGE_SIZE
    return dict(items=items[offset:offset + PAGE_SIZE] if view == "feed" else [],
                total_count=len(all_items), filtered_count=filtered_count,
                has_more=offset + PAGE_SIZE < filtered_count and view == "feed", page=page,
                section=section, section_title=SECTIONS.get(section, "Dla Ciebie" if section == "priority" else "Twój daily feed"),
                language=language, category=category, source=source, query=query, sort=sort, view=view,
                available_source_groups=groups,
                categories=sorted({i["category"] for i in all_items if i["category"]}),
                section_counts={key: sum(i["source_type"] == key for i in all_items) for key in SECTIONS},
                priority_count=sum(bool(i.get("priority") or i["matched_keywords"]) for i in all_items),
                updated_at=feed["updated_at"], feed_error=feed["error"], app_version=APP_VERSION)


@app.template_global()
def filter_url(**changes):
    params = {k: v for k, v in request.args.items()
              if k in {"section", "lang", "category", "source", "q", "sort", "view"}}
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
    if request.path in {"/", "/api/feed", "/health"}:
        response.headers["Cache-Control"] = "no-cache"
    return response


if __name__ == "__main__":
    app.run()
