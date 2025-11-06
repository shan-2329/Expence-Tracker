from flask import Flask, render_template

app = Flask(__name__)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/about")
def about():
    return render_template("index.html", section="about")

@app.route("/amenities")
def amenities():
    return render_template("index.html", section="amenities")

@app.route("/services")
def services():
    return render_template("index.html", section="services")

@app.route("/location")
def location():
    return render_template("index.html", section="location")

@app.route("/contact")
def contact():
    return render_template("index.html", section="contact")

if __name__ == "__main__":
    app.run(debug=True)
