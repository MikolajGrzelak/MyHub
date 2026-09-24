from flask import Flask, render_template, request

from db import get_items, init_db

app = Flask(__name__)


@app.route("/")
def index():
    category = request.args.get("category")
    items = get_items(limit=80, category=category)

    return render_template(
        "index.html",
        items=items,
        active_category=category or "Wszystko",
    )


@app.route("/health")
def health():
    return {"status": "ok"}


init_db()

if __name__ == "__main__":
    app.run(debug=True)
