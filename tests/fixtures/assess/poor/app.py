import subprocess

from flask import Flask, request

app = Flask(__name__)
DATABASE = "orders.db"
ORDERS = []


@app.route("/orders", methods=["GET", "POST"])
def orders():
    if request.method == "POST":
        order = {"email": request.form["email"], "phone": request.form["phone"], "item": request.form["item"]}
        ORDERS.append(order)
        print("new order", order)
    return {"orders": ORDERS}


@app.route("/export")
def export():
    name = request.args.get("name", "orders")
    subprocess.run(f"cp {DATABASE} /tmp/{name}.db", shell=True)
    return {"exported": name}


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
