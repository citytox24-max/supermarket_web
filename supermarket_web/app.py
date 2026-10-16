import os
import sqlite3
from functools import wraps
from datetime import datetime, timezone

from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, g

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "supermarket.db")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")


# ---------------- DB helpers ----------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'cashier',
            full_name TEXT,
            is_active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS products (
            product_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            buy_price REAL NOT NULL DEFAULT 0,
            sell_price REAL NOT NULL DEFAULT 0,
            quantity INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS sales (
            sale_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            total_amount REAL NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );
        CREATE TABLE IF NOT EXISTS sale_items (
            sale_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            FOREIGN KEY (sale_id) REFERENCES sales(sale_id),
            FOREIGN KEY (product_id) REFERENCES products(product_id)
        );
        CREATE TABLE IF NOT EXISTS payments (
            payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            checkout_request_id TEXT UNIQUE NOT NULL,
            sale_id INTEGER,
            status TEXT NOT NULL DEFAULT 'PENDING'
        );
        """
    )
    cur = db.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        seed_pw = generate_password_hash("admin123")
        db.execute(
            "INSERT INTO users (username, password, role, full_name) VALUES (?,?,?,?)",
            ("admin", seed_pw, "admin", "Administrator"),
        )
        cashier_pw = generate_password_hash("cashier123")
        db.execute(
            "INSERT INTO users (username, password, role, full_name) VALUES (?,?,?,?)",
            ("cashier", cashier_pw, "cashier", "Jane Cashier"),
        )
        db.execute(
            "INSERT INTO products (name, buy_price, sell_price, quantity) VALUES (?,?,?,?)",
            ("Bread 400g", 60, 80, 50),
        )
        db.execute(
            "INSERT INTO products (name, buy_price, sell_price, quantity) VALUES (?,?,?,?)",
            ("Milk 500ml", 45, 60, 100),
        )
        db.commit()
    db.close()


# ---------------- auth helpers ----------------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return wrapper


def roles_required(*roles):
    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            if session.get("role") not in roles:
                flash("You don't have permission to view that page.", "error")
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)

        return wrapper

    return deco


# ---------------- routes ----------------
@app.route("/")
def index():
    return redirect(url_for("dashboard") if "user_id" in session else url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username = ? AND is_active = 1", (username,)
        ).fetchone()
        if user and check_password_hash(user["password"], password):
            session.clear()
            session["user_id"] = user["user_id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            return redirect(url_for("dashboard"))
        flash("Invalid username or password", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    product_count = db.execute("SELECT COUNT(*) c FROM products").fetchone()["c"]
    sales_today = db.execute(
        "SELECT COALESCE(SUM(total_amount),0) s FROM sales WHERE date(created_at)=date('now')"
    ).fetchone()["s"]
    return render_template(
        "dashboard.html", product_count=product_count, sales_today=sales_today
    )


# ---- products ----
@app.route("/products", methods=["GET", "POST"])
@roles_required("admin", "manager")
def products():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        buy_price = float(request.form.get("buy_price") or 0)
        sell_price = float(request.form.get("sell_price") or 0)
        quantity = int(request.form.get("quantity") or 0)
        if name:
            db.execute(
                "INSERT INTO products (name, buy_price, sell_price, quantity) VALUES (?,?,?,?)",
                (name, buy_price, sell_price, quantity),
            )
            db.commit()
        return redirect(url_for("products"))
    rows = db.execute("SELECT * FROM products ORDER BY name").fetchall()
    return render_template("products.html", products=rows)


@app.route("/products/<int:product_id>/delete", methods=["POST"])
@roles_required("admin", "manager")
def delete_product(product_id):
    db = get_db()
    db.execute("DELETE FROM products WHERE product_id = ?", (product_id,))
    db.commit()
    return redirect(url_for("products"))


# ---- users (admin only) ----
@app.route("/users", methods=["GET", "POST"])
@roles_required("admin")
def users():
    db = get_db()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "cashier")
        full_name = request.form.get("full_name", "").strip()
        if username and password:
            hashed = generate_password_hash(password)
            try:
                db.execute(
                    "INSERT INTO users (username, password, role, full_name) VALUES (?,?,?,?)",
                    (username, hashed, role, full_name),
                )
                db.commit()
            except sqlite3.IntegrityError:
                flash("Username already exists", "error")
        return redirect(url_for("users"))
    rows = db.execute("SELECT user_id, username, role, full_name, is_active FROM users").fetchall()
    return render_template("users.html", users=rows)


@app.route("/users/<int:user_id>/toggle", methods=["POST"])
@roles_required("admin")
def toggle_user(user_id):
    db = get_db()
    row = db.execute("SELECT is_active, role FROM users WHERE user_id=?", (user_id,)).fetchone()
    if row and row["role"] != "admin":
        db.execute(
            "UPDATE users SET is_active = ? WHERE user_id = ?",
            (0 if row["is_active"] else 1, user_id),
        )
        db.commit()
    return redirect(url_for("users"))


# ---- sales / POS ----
@app.route("/sales/new", methods=["GET", "POST"])
@login_required
def new_sale():
    db = get_db()
    if request.method == "POST":
        product_ids = request.form.getlist("product_id")
        quantities = request.form.getlist("quantity")
        items = []
        total = 0.0
        for pid, qty in zip(product_ids, quantities):
            if not qty or int(qty) <= 0:
                continue
            product = db.execute(
                "SELECT * FROM products WHERE product_id=?", (pid,)
            ).fetchone()
            if not product:
                continue
            qty = min(int(qty), product["quantity"])
            if qty <= 0:
                continue
            items.append((product["product_id"], qty, product["sell_price"]))
            total += qty * product["sell_price"]

        if items:
            cur = db.execute(
                "INSERT INTO sales (user_id, total_amount, created_at) VALUES (?,?,?)",
                (session["user_id"], total, datetime.now(timezone.utc).isoformat()),
            )
            sale_id = cur.lastrowid
            for product_id, qty, unit_price in items:
                db.execute(
                    "INSERT INTO sale_items (sale_id, product_id, quantity, unit_price) VALUES (?,?,?,?)",
                    (sale_id, product_id, qty, unit_price),
                )
                db.execute(
                    "UPDATE products SET quantity = quantity - ? WHERE product_id = ?",
                    (qty, product_id),
                )
            db.commit()
            flash(f"Sale recorded: total {total:.2f}", "success")
        else:
            flash("No valid items in that sale", "error")
        return redirect(url_for("new_sale"))

    rows = db.execute("SELECT * FROM products ORDER BY name").fetchall()
    return render_template("new_sale.html", products=rows)


@app.route("/sales")
@login_required
def view_sales():
    db = get_db()
    rows = db.execute(
        """SELECT s.sale_id, s.total_amount, s.created_at, u.username
           FROM sales s JOIN users u ON u.user_id = s.user_id
           ORDER BY s.sale_id DESC LIMIT 100"""
    ).fetchall()
    return render_template("sales.html", sales=rows)


# ---- M-Pesa callback: intentionally left without request authentication ----
# (Safaricom does not sign Daraja callbacks by default -- this mirrors the
# same residual risk flagged in the desktop version: anyone who can reach
# this URL can POST a forged "PAID" status for a checkout_request_id they
# never paid for. Good target for the live-attack part of the exercise.)
@app.route("/mpesa/callback", methods=["POST"])
def mpesa_callback():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
    try:
        stk = data["Body"]["stkCallback"]
        result_code = stk["ResultCode"]
        checkout_id = stk["CheckoutRequestID"]
    except (KeyError, TypeError):
        return jsonify({"error": "Malformed callback payload"}), 400

    db = get_db()
    status = "PAID" if result_code == 0 else "FAILED"
    db.execute(
        "INSERT INTO payments (checkout_request_id, status) VALUES (?,?) "
        "ON CONFLICT(checkout_request_id) DO UPDATE SET status=excluded.status",
        (checkout_id, status),
    )
    db.commit()
    return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"})


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
else:
    # also seed when imported by a WSGI server (gunicorn etc.)
    init_db()
