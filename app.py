from flask import Flask, render_template

app = Flask(__name__)


@app.route("/")
def index():
    items = [
        {
            "source": "MyHub",
            "category": "Start",
            "title": "MyHub is alive",
            "summary": "Pierwsza wersja aplikacji działa. Następny krok: prawdziwe źródła newsów.",
            "url": "#",
        }
    ]
    return render_template("index.html", items=items)


if __name__ == "__main__":
    app.run(debug=True)
