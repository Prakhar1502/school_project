#!/usr/bin/env python3
"""
School Fee Register - laptop server.

Runs the fee register on this computer and lets phones on the same Wi-Fi use it.
Needs only Python 3.8 or newer. No other installs.

    python server.py            start on port 8000
    python server.py --port 9000
    python server.py --reset-pin

Data is kept in the "data" folder next to this file:
    data/fees.db        all students, payments and settings
    data/backups/       a dated copy of fees.db, made every day (last 60 kept)
"""
import argparse
import datetime as dt
import hashlib
import hmac
import http.server
import json
import os
import re
import secrets
import socket
import sqlite3
import sys
import threading
import time
import webbrowser
from urllib.parse import urlparse, parse_qs

APP = "school-fee-register"
BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
BACKUPS = os.path.join(DATA, "backups")
DB_PATH = os.path.join(DATA, "fees.db")
INDEX = os.path.join(BASE, "index.html")
MAX_BODY = 2 * 1024 * 1024
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
COOKIE = "fee_register_token"
TOKEN_DAYS = 365

LOCK = threading.Lock()
FAILED = {}  # ip -> [timestamps of wrong PINs]


# ---------------------------------------------------------------- database
def connect():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init_db():
    os.makedirs(BACKUPS, exist_ok=True)
    with LOCK, connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS students (id TEXT PRIMARY KEY, doc TEXT NOT NULL, updated TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tokens (token_hash TEXT PRIMARY KEY, created TEXT NOT NULL, agent TEXT);
            """
        )
        con.execute("INSERT OR IGNORE INTO kv (k, v) VALUES ('rev', '0')")


def kv_get(con, k, default=None):
    row = con.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return row[0] if row else default


def kv_set(con, k, v):
    con.execute("INSERT INTO kv (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))


def bump(con):
    rev = int(kv_get(con, "rev", "0")) + 1
    kv_set(con, "rev", str(rev))
    return rev


def now_iso():
    return dt.datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- PIN
def hash_pin(pin, salt):
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 200_000).hex()


def has_pin():
    with LOCK, connect() as con:
        return kv_get(con, "pin_hash") is not None


def set_pin(pin):
    salt = secrets.token_hex(16)
    with LOCK, connect() as con:
        kv_set(con, "pin_salt", salt)
        kv_set(con, "pin_hash", hash_pin(pin, salt))
        con.execute("DELETE FROM tokens")  # sign out every device


def check_pin(pin):
    with LOCK, connect() as con:
        salt, ph = kv_get(con, "pin_salt"), kv_get(con, "pin_hash")
    if not salt or not ph:
        return False
    return hmac.compare_digest(hash_pin(pin, salt), ph)


def ask_pin():
    print()
    print("  Choose a PIN for the fee register (4 to 12 digits).")
    print("  You'll type it once on each phone or laptop that opens the register.")
    while True:
        pin = input("  New PIN: ").strip()
        if not re.fullmatch(r"\d{4,12}", pin):
            print("  Use 4 to 12 digits only.")
            continue
        again = input("  Type the PIN again: ").strip()
        if pin != again:
            print("  The two PINs didn't match. Try again.")
            continue
        set_pin(pin)
        print("  PIN saved.\n")
        return


def token_hash(t):
    return hashlib.sha256(t.encode()).hexdigest()


def new_token(agent):
    t = secrets.token_urlsafe(32)
    with LOCK, connect() as con:
        con.execute("INSERT INTO tokens (token_hash, created, agent) VALUES (?, ?, ?)", (token_hash(t), now_iso(), (agent or "")[:200]))
    return t


def valid_token(t):
    if not t:
        return False
    with LOCK, connect() as con:
        row = con.execute("SELECT created FROM tokens WHERE token_hash=?", (token_hash(t),)).fetchone()
    if not row:
        return False
    try:
        return dt.datetime.fromisoformat(row[0]) > dt.datetime.now() - dt.timedelta(days=TOKEN_DAYS)
    except ValueError:
        return False


def drop_token(t):
    if t:
        with LOCK, connect() as con:
            con.execute("DELETE FROM tokens WHERE token_hash=?", (token_hash(t),))


def too_many_failures(ip):
    cutoff = time.time() - 600
    FAILED[ip] = [x for x in FAILED.get(ip, []) if x > cutoff]
    return len(FAILED[ip]) >= 8


# ---------------------------------------------------------------- backups
def backup_now():
    name = os.path.join(BACKUPS, "fees-" + dt.date.today().isoformat() + ".db")
    if os.path.exists(name):
        return
    with LOCK:
        src = connect()
        dst = sqlite3.connect(name)
        with dst:
            src.backup(dst)
        dst.close()
        src.close()
    files = sorted(f for f in os.listdir(BACKUPS) if f.startswith("fees-") and f.endswith(".db"))
    for old in files[:-60]:
        try:
            os.remove(os.path.join(BACKUPS, old))
        except OSError:
            pass


def backup_loop():
    while True:
        try:
            backup_now()
        except Exception as e:  # never stop the server over a backup
            print("  Backup failed:", e)
        time.sleep(3600)


# ---------------------------------------------------------------- network
def lan_ips():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # no packet is sent; this only picks the Wi-Fi address
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and not ip.startswith("169.254."):
                ips.add(ip)
    except OSError:
        pass
    private = [ip for ip in ips if ip.startswith(("192.168.", "10.")) or re.match(r"^172\.(1[6-9]|2\d|3[01])\.", ip)]
    return sorted(private) or sorted(ips)


# ---------------------------------------------------------------- HTTP
class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "FeeRegister/1.0"

    def log_message(self, fmt, *args):
        pass  # keep the window quiet

    # helpers
    def send_json(self, code, obj, extra_headers=None):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or []):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def no_content(self):
        self.send_response(204)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def token(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return v
        return None

    def authed(self):
        return valid_token(self.token())

    def read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("That's too much data to save at once.")
        raw = self.rfile.read(n) if n else b"{}"
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Expected an object.")
        return data

    def same_origin(self):
        # Block other websites from posting to the register through the browser.
        origin = self.headers.get("Origin")
        if not origin:
            return True
        return urlparse(origin).netloc == self.headers.get("Host")

    # routes
    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            try:
                with open(INDEX, "rb") as f:
                    body = f.read()
            except OSError:
                self.send_error(500, "index.html is missing next to server.py")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if u.path == "/api/ping":
            return self.send_json(200, {"app": APP})
        if not u.path.startswith("/api/"):
            return self.send_json(404, {"error": "Not found"})
        if not self.authed():
            return self.send_json(401, {"error": "PIN needed"})
        if u.path == "/api/state":
            since = parse_qs(u.query).get("since", ["-1"])[0]
            with LOCK, connect() as con:
                rev = int(kv_get(con, "rev", "0"))
                if since == str(rev):
                    return self.send_json(200, {"rev": rev, "changed": False})
                students = []
                for sid, doc in con.execute("SELECT id, doc FROM students"):
                    d = json.loads(doc)
                    d["id"] = sid
                    students.append(d)
                settings = kv_get(con, "settings")
            return self.send_json(200, {"rev": rev, "students": students, "settings": json.loads(settings) if settings else None})
        if u.path == "/api/info":
            port = self.server.server_address[1]
            return self.send_json(200, {"lan_urls": ["http://%s:%d" % (ip, port) for ip in lan_ips()]})
        return self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        u = urlparse(self.path)
        if not self.same_origin():
            return self.send_json(403, {"error": "Not allowed"})
        if u.path == "/api/login":
            ip = self.client_address[0]
            if too_many_failures(ip):
                return self.send_json(429, {"error": "Too many wrong PINs. Wait 10 minutes and try again."})
            try:
                pin = str(self.read_json().get("pin", "")).strip()
            except (ValueError, json.JSONDecodeError):
                pin = ""
            if not check_pin(pin):
                FAILED.setdefault(ip, []).append(time.time())
                time.sleep(1)
                return self.send_json(403, {"error": "Wrong PIN. Try again."})
            t = new_token(self.headers.get("User-Agent"))
            cookie = "%s=%s; Max-Age=%d; Path=/; HttpOnly; SameSite=Lax" % (COOKIE, t, TOKEN_DAYS * 86400)
            return self.send_json(200, {"ok": True}, [("Set-Cookie", cookie)])
        if u.path == "/api/logout":
            drop_token(self.token())
            return self.send_json(200, {"ok": True}, [("Set-Cookie", "%s=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax" % COOKIE)])
        return self.send_json(404, {"error": "Not found"})

    def write_route(self, method):
        u = urlparse(self.path)
        if not self.same_origin():
            return self.send_json(403, {"error": "Not allowed"})
        if not self.authed():
            return self.send_json(401, {"error": "PIN needed"})
        try:
            body = self.read_json() if method != "DELETE" else {}
        except (ValueError, json.JSONDecodeError) as e:
            return self.send_json(400, {"error": str(e) if isinstance(e, ValueError) else "Bad data"})
        body.pop("id", None)

        if u.path == "/api/settings" and method == "PUT":
            with LOCK, connect() as con:
                kv_set(con, "settings", json.dumps(body, ensure_ascii=False))
                rev = bump(con)
            return self.send_json(200, {"rev": rev})

        m = re.fullmatch(r"/api/students/([^/]+)", u.path)
        if not m or not ID_RE.match(m.group(1)):
            return self.send_json(404, {"error": "Not found"})
        sid = m.group(1)
        with LOCK, connect() as con:
            row = con.execute("SELECT doc FROM students WHERE id=?", (sid,)).fetchone()
            if method == "PUT":
                doc = body
            elif method == "PATCH":
                if not row:
                    return self.send_json(404, {"error": "That student no longer exists."})
                doc = json.loads(row[0])
                doc.update(body)
            else:  # DELETE
                con.execute("DELETE FROM students WHERE id=?", (sid,))
                rev = bump(con)
                return self.send_json(200, {"rev": rev})
            con.execute(
                "INSERT INTO students (id, doc, updated) VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET doc=excluded.doc, updated=excluded.updated",
                (sid, json.dumps(doc, ensure_ascii=False), now_iso()),
            )
            rev = bump(con)
        return self.send_json(200, {"rev": rev})

    def do_PUT(self):
        self.write_route("PUT")

    def do_PATCH(self):
        self.write_route("PATCH")

    def do_DELETE(self):
        self.write_route("DELETE")


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    ap = argparse.ArgumentParser(description="School Fee Register")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    ap.add_argument("--reset-pin", action="store_true", help="choose a new PIN (signs out every device)")
    ap.add_argument("--no-browser", action="store_true", help="don't open the browser on start")
    args = ap.parse_args()

    if sys.version_info < (3, 8):
        print("Python 3.8 or newer is needed. Download it from https://www.python.org/downloads/")
        sys.exit(1)

    init_db()
    if args.reset_pin or not has_pin():
        ask_pin()
    try:
        backup_now()
    except Exception as e:
        print("  Backup failed:", e)
    threading.Thread(target=backup_loop, daemon=True).start()

    try:
        httpd = Server(("0.0.0.0", args.port), Handler)
    except OSError:
        print("\n  Port %d is busy. Is the register already open in another window?" % args.port)
        print("  Close that window, or start with:  python server.py --port 8001\n")
        input("  Press Enter to close.")
        sys.exit(1)

    local = "http://localhost:%d" % args.port
    print("=" * 60)
    print("  School Fee Register is running.")
    print()
    print("  On this laptop:   " + local)
    for ip in lan_ips():
        print("  On your phone:    http://%s:%d   (same Wi-Fi)" % (ip, args.port))
    print()
    print("  Keep this window open while using the register.")
    print("  Data: " + DB_PATH)
    print("  Close this window (or press Ctrl+C) to stop.")
    print("=" * 60)
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(local)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")


if __name__ == "__main__":
    main()
