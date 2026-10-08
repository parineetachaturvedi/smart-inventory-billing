"""Smart Inventory & Billing System
Flask backend + one JSON file (data/store.json) as storage.
Layers inside this one file:  routes -> service helpers -> load_data()/save_data() -> store.json
"""
import io
import json
import os
import threading
from datetime import date, datetime, timedelta
from functools import wraps

from flask import Flask, jsonify, render_template, request, send_file, session
from werkzeug.security import check_password_hash, generate_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE, "data", "store.json")
LOCK = threading.Lock()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-in-production")


# ---------------------------------------------------------------- data layer
def default_data():
    today = date.today().isoformat()
    products = [
        ("Classmate Notebook", "Stationery", 60, 45, 10, "ABC Suppliers"),
        ("Blue Gel Pen", "Stationery", 10, 8, 15, "ABC Suppliers"),
        ("Parle-G Biscuit", "Grocery", 10, 0, 20, "Fresh Traders"),
        ("Basmati Rice 1kg", "Grocery", 110, 30, 10, "Fresh Traders"),
    ]
    return {
        "users": [{"id": 1, "name": "Admin", "email": "admin@example.com",
                   "password": generate_password_hash("admin123"), "role": "admin"}],
        "categories": ["Stationery", "Grocery"],
        "products": [{"id": 101 + i, "name": n, "category": c, "price": p, "quantity": q,
                      "low_stock_limit": l, "supplier": s, "created_at": today}
                     for i, (n, c, p, q, l, s) in enumerate(products)],
        "customers": [{"id": 201, "name": "Rahul", "phone": "9876543210"}],
        "sales": [],
        "sale_items": [],
    }


def load_data():
    if not os.path.exists(DATA_FILE):
        save_data(default_data())
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, DATA_FILE)  # atomic write: file never half-written


def next_id(rows, start=1):
    return max([r["id"] for r in rows], default=start - 1) + 1


def find(rows, row_id):
    return next((r for r in rows if r["id"] == row_id), None)


# --------------------------------------------------------------------- auth
def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if "user_id" not in session:
            return jsonify(error="Please log in."), 401
        return fn(*a, **kw)
    return wrapper


@app.get("/")
def index():
    return render_template("app.html")


@app.post("/api/login")
def login():
    body = request.get_json(force=True)
    with LOCK:
        users = load_data()["users"]
    user = next((u for u in users if u["email"].lower() == body.get("email", "").lower()), None)
    if not user or not check_password_hash(user["password"], body.get("password", "")):
        return jsonify(error="Wrong email or password."), 401
    session["user_id"], session["name"] = user["id"], user["name"]
    return jsonify(name=user["name"])


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/me")
def me():
    return jsonify(name=session.get("name")) if "user_id" in session else (jsonify(error="no"), 401)


# ----------------------------------------------------------------- products
def clean_product(body):
    try:
        name = str(body["name"]).strip()
        price = float(body["price"])
        qty = int(body["quantity"])
        limit = int(body.get("low_stock_limit", 10))
    except (KeyError, ValueError, TypeError):
        raise ValueError("Name, price and quantity are required and must be valid numbers.")
    if not name or price < 0 or qty < 0 or limit < 0:
        raise ValueError("Name is required; price and quantity cannot be negative.")
    return {"name": name, "category": str(body.get("category", "General")).strip() or "General",
            "price": price, "quantity": qty, "low_stock_limit": limit,
            "supplier": str(body.get("supplier", "")).strip()}


@app.get("/api/products")
@login_required
def products_list():
    with LOCK:
        return jsonify(load_data()["products"])


@app.post("/api/products")
@login_required
def products_add():
    with LOCK:
        data = load_data()
        try:
            p = clean_product(request.get_json(force=True))
        except ValueError as e:
            return jsonify(error=str(e)), 400
        p.update(id=next_id(data["products"], 101), created_at=date.today().isoformat())
        data["products"].append(p)
        if p["category"] not in data["categories"]:
            data["categories"].append(p["category"])
        save_data(data)
    return jsonify(p), 201


@app.put("/api/products/<int:pid>")
@login_required
def products_update(pid):
    with LOCK:
        data = load_data()
        p = find(data["products"], pid)
        if not p:
            return jsonify(error="Product not found."), 404
        try:
            p.update(clean_product(request.get_json(force=True)))
        except ValueError as e:
            return jsonify(error=str(e)), 400
        save_data(data)
    return jsonify(p)


@app.delete("/api/products/<int:pid>")
@login_required
def products_delete(pid):
    with LOCK:
        data = load_data()
        if not find(data["products"], pid):
            return jsonify(error="Product not found."), 404
        data["products"] = [p for p in data["products"] if p["id"] != pid]
        save_data(data)
    return jsonify(ok=True)


@app.post("/api/products/<int:pid>/stock")
@login_required
def stock_adjust(pid):
    """Add (+) or remove (-) stock. Body: {"delta": 20}"""
    with LOCK:
        data = load_data()
        p = find(data["products"], pid)
        if not p:
            return jsonify(error="Product not found."), 404
        try:
            delta = int(request.get_json(force=True)["delta"])
        except (KeyError, ValueError, TypeError):
            return jsonify(error="Enter a whole number."), 400
        if p["quantity"] + delta < 0:
            return jsonify(error="Stock cannot go below zero."), 400
        p["quantity"] += delta
        save_data(data)
    return jsonify(p)


# ---------------------------------------------------------------- customers
@app.get("/api/customers")
@login_required
def customers_list():
    with LOCK:
        return jsonify(load_data()["customers"])


@app.post("/api/customers")
@login_required
def customers_add():
    body = request.get_json(force=True)
    name, phone = str(body.get("name", "")).strip(), str(body.get("phone", "")).strip()
    if not name:
        return jsonify(error="Customer name is required."), 400
    with LOCK:
        data = load_data()
        c = {"id": next_id(data["customers"], 201), "name": name, "phone": phone}
        data["customers"].append(c)
        save_data(data)
    return jsonify(c), 201


@app.delete("/api/customers/<int:cid>")
@login_required
def customers_delete(cid):
    with LOCK:
        data = load_data()
        data["customers"] = [c for c in data["customers"] if c["id"] != cid]
        save_data(data)
    return jsonify(ok=True)


# ------------------------------------------------------------------ billing
@app.post("/api/sales")
@login_required
def sales_create():
    """Body: {"customer_id": 201 | null, "items": [{"product_id": 101, "quantity": 3}]}"""
    body = request.get_json(force=True)
    items = body.get("items") or []
    if not items:
        return jsonify(error="Add at least one item to the bill."), 400
    with LOCK:
        data = load_data()
        lines, total = [], 0
        # validate everything first so a failed bill changes nothing
        for it in items:
            p = find(data["products"], int(it["product_id"]))
            qty = int(it["quantity"])
            if not p or qty <= 0:
                return jsonify(error="Invalid item in bill."), 400
            if p["quantity"] < qty:
                return jsonify(error=f"Only {p['quantity']} left of {p['name']}."), 400
            lines.append((p, qty))
        sale_id = next_id(data["sales"], 301)
        for p, qty in lines:
            sub = p["price"] * qty
            total += sub
            p["quantity"] -= qty  # automatic stock update
            data["sale_items"].append({"sale_id": sale_id, "product_id": p["id"], "name": p["name"],
                                       "quantity": qty, "price": p["price"], "subtotal": sub})
        cid = body.get("customer_id")
        sale = {"id": sale_id, "invoice_number": f"INV-{len(data['sales']) + 1:04d}",
                "customer_id": int(cid) if cid else None, "total_amount": total,
                "sale_date": date.today().isoformat(),
                "created_at": datetime.now().strftime("%H:%M")}
        data["sales"].append(sale)
        save_data(data)
    return jsonify(sale), 201


def sale_detail(data, sid):
    sale = find(data["sales"], sid)
    if not sale:
        return None
    cust = find(data["customers"], sale["customer_id"]) if sale["customer_id"] else None
    return {**sale, "customer": cust["name"] if cust else "Walk-in customer",
            "items": [i for i in data["sale_items"] if i["sale_id"] == sid]}


@app.get("/api/sales")
@login_required
def sales_list():
    with LOCK:
        data = load_data()
    out = [sale_detail(data, s["id"]) for s in reversed(data["sales"])]
    return jsonify(out)


@app.get("/api/sales/<int:sid>/invoice")
def invoice_pdf(sid):
    if "user_id" not in session:
        return "Please log in.", 401
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    with LOCK:
        d = sale_detail(load_data(), sid)
    if not d:
        return "Sale not found.", 404
    buf, st = io.BytesIO(), getSampleStyleSheet()
    rows = [["Item", "Qty", "Price (Rs.)", "Subtotal (Rs.)"]]
    rows += [[i["name"], i["quantity"], f"{i['price']:.2f}", f"{i['subtotal']:.2f}"] for i in d["items"]]
    rows.append(["", "", "Total", f"{d['total_amount']:.2f}"])
    table = Table(rows, colWidths=[230, 50, 90, 100])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#14313b")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -2), 0.4, colors.grey),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT")]))
    SimpleDocTemplate(buf, pagesize=A4).build([
        Paragraph("Smart Inventory &amp; Billing System", st["Title"]),
        Paragraph(f"Invoice: <b>{d['invoice_number']}</b>", st["Normal"]),
        Paragraph(f"Date: {d['sale_date']} {d.get('created_at', '')}", st["Normal"]),
        Paragraph(f"Customer: {d['customer']}", st["Normal"]),
        Spacer(1, 16), table, Spacer(1, 16), Paragraph("Thank you for shopping with us!", st["Normal"])])
    buf.seek(0)
    return send_file(buf, mimetype="application/pdf", download_name=f"{d['invoice_number']}.pdf")


# ---------------------------------------------------------------- dashboard
@app.get("/api/dashboard")
@login_required
def dashboard():
    with LOCK:
        data = load_data()
    today = date.today()
    prods = data["products"]
    days = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    daily = {d: 0 for d in days}
    for s in data["sales"]:
        if s["sale_date"] in daily:
            daily[s["sale_date"]] += s["total_amount"]
    top = {}
    for i in data["sale_items"]:
        top[i["name"]] = top.get(i["name"], 0) + i["quantity"]
    top = sorted(top.items(), key=lambda x: -x[1])[:5]
    return jsonify(
        total_products=len(prods),
        low_stock=sum(1 for p in prods if 0 < p["quantity"] <= p["low_stock_limit"]),
        out_of_stock=sum(1 for p in prods if p["quantity"] == 0),
        today_sales=sum(s["total_amount"] for s in data["sales"] if s["sale_date"] == today.isoformat()),
        total_orders=len(data["sales"]),
        daily=daily, top=top)


if __name__ == "__main__":
    load_data()  # creates data/store.json with sample data on first run
    app.run(debug=True)
