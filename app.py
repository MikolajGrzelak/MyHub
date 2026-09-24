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
    source_groups = {
        "news": set(),
        "reddit": set(),
        "youtube": set(),
        "deal": set(),
    }
    for item in all_items:
        source_name = item.get("source", "")
        if not source_name:
            continue
        source_type = item.get("source_type", "news")
        if source_type not in source_groups:
            source_type = "news"
        source_groups[source_type].add(source_name)

    available_source_groups = {
        key: sorted(values, key=lambda value: value.lower())
        for key, values in source_groups.items()
        if values
    }

    return render_template("index.html", items=items[:120], total_count=len(all_items),
                           category=category, language=language, source=source, section=section,
                           available_source_groups=available_source_groups)

@app.route("/health")
def health():
    items = load_items()
    return {"status":"ok","items":len(items),
            "pl":sum(1 for i in items if i.get("language")=="pl"),
            "en":sum(1 for i in items if i.get("language","en")=="en")}

if __name__ == "__main__":
    app.run(debug=True)
