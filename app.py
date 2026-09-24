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
            return json.load(f).get("items", [])
    except (OSError, json.JSONDecodeError):
        return []

@app.route("/")
def index():
    all_items = load_items()
    category = request.args.get("category", "").strip()
    language = request.args.get("lang", "").strip().lower()
    source = request.args.get("source", "").strip()
    section = request.args.get("section", "").strip().lower()
    items = all_items
    if category:
        items = [i for i in items if i.get("category","").lower() == category.lower()]
    if language in {"pl","en"}:
        items = [i for i in items if i.get("language","en").lower() == language]
    if source:
        items = [i for i in items if i.get("source","") == source]
    if section in {"news","reddit","youtube","deal","priority"}:
        if section == "priority":
            items = [i for i in items if i.get("priority")]
        else:
            items = [i for i in items if i.get("source_type","news") == section]
    sources = sorted({i.get("source","") for i in all_items if i.get("source")})
    return render_template("index.html", items=items[:120], total_count=len(all_items),
                           category=category, language=language, source=source, section=section,
                           available_sources=sources)

@app.route("/health")
def health():
    items = load_items()
    return {"status":"ok","items":len(items),
            "pl":sum(1 for i in items if i.get("language")=="pl"),
            "en":sum(1 for i in items if i.get("language","en")=="en")}

if __name__ == "__main__":
    app.run(debug=True)
