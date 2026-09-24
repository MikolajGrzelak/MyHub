import json
from pathlib import Path

from flask import Flask, render_template, request

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
FEED_PATH = BASE_DIR / "data" / "feed.json"


def load_items():
    if not FEED_PATH.exists():
        return []

    try:
        with FEED_PATH.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        return payload.get("items", [])
    except (OSError, json.JSONDecodeError):
        return []


@app.route("/")
def index():
    category = request.args.get("category")
    items = load_items()

    if category:
        items = [
            item
            for item in items
            if item.get("category", "").lower() == category.lower()
        ]

    return render_template(
        "index.html",
        items=items[:80],
        active_category=category or "Wszystko",
    )


@app.route("/health")
def health():
    return {"status": "ok", "items": len(load_items())}


if __name__ == "__main__":
    app.run(debug=True)
