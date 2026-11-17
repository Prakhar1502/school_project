/**
 * School Fee Register — Cloudflare Worker backend.
 *
 * Serves the same API as server.py, so index.html works unchanged:
 *   GET    /api/ping
 *   POST   /api/login        {pin}
 *   POST   /api/logout
 *   GET    /api/state?since=<rev>
 *   GET    /api/info
 *   PUT    /api/students/<id>    whole student
 *   PATCH  /api/students/<id>    some fields
 *   DELETE /api/students/<id>
 *   PUT    /api/settings
 *
 * Data lives in a Cloudflare D1 database (binding DB).
 * The PIN is a Worker secret named REGISTER_PIN (Settings → Variables and Secrets).
 * Everything else is served from the static files (index.html etc.).
 */

const APP = "school-fee-register";
const COOKIE = "fee_register_token";
const TOKEN_DAYS = 365;
const MAX_BODY = 1_500_000; // D1 rows hold up to 2 MB; keep well under
const ID_RE = /^[A-Za-z0-9_-]{1,64}$/;
const MAX_FAILS = 8;       // wrong PINs allowed per IP …
const FAIL_WINDOW = 600;   // … per 10 minutes

let schemaReady = false;

async function ensureSchema(db) {
  if (schemaReady) return;
  await db.batch([
    db.prepare("CREATE TABLE IF NOT EXISTS students (id TEXT PRIMARY KEY, doc TEXT NOT NULL, updated TEXT NOT NULL)"),
    db.prepare("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL)"),
    db.prepare("CREATE TABLE IF NOT EXISTS tokens (token_hash TEXT PRIMARY KEY, created INTEGER NOT NULL, agent TEXT)"),
    db.prepare("CREATE TABLE IF NOT EXISTS login_failures (ip TEXT NOT NULL, ts INTEGER NOT NULL)"),
    db.prepare("INSERT OR IGNORE INTO kv (k, v) VALUES ('rev', '0')"),
  ]);
  schemaReady = true;
}

/* ---------------------------------------------------------------- helpers */
const enc = new TextEncoder();

function json(status, obj, headers = {}) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", ...headers },
  });
}

async function sha256(text) {
  const buf = await crypto.subtle.digest("SHA-256", enc.encode(text));
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, "0")).join("");
}

function safeEqual(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function randomToken() {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function readCookie(request) {
  for (const part of (request.headers.get("Cookie") || "").split(";")) {
    const [k, ...v] = part.trim().split("=");
    if (k === COOKIE) return v.join("=");
  }
  return null;
}

function cookieHeader(value, maxAge) {
  return `${COOKIE}=${value}; Max-Age=${maxAge}; Path=/; HttpOnly; Secure; SameSite=Lax`;
}

function sameOrigin(request, url) {
  const origin = request.headers.get("Origin");
  if (!origin) return true;
  try { return new URL(origin).host === url.host; } catch { return false; }
}

async function readBody(request) {
  const len = +(request.headers.get("Content-Length") || 0);
  if (len > MAX_BODY) throw new Error("That's too much data to save at once.");
  const text = await request.text();
  if (text.length > MAX_BODY) throw new Error("That's too much data to save at once.");
  const data = text ? JSON.parse(text) : {};
  if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("Expected an object.");
  return data;
}

async function bump(db) {
  const row = await db.prepare("UPDATE kv SET v = CAST(v AS INTEGER) + 1 WHERE k = 'rev' RETURNING v").first();
  return +row.v;
}

async function validToken(db, token) {
  if (!token) return false;
  const row = await db.prepare("SELECT created FROM tokens WHERE token_hash = ?").bind(await sha256(token)).first();
  return !!row && row.created > Date.now() - TOKEN_DAYS * 86400_000;
}

/* ---------------------------------------------------------------- API */
async function handleApi(request, env, url) {
  const db = env.DB;
  const path = url.pathname;
  const method = request.method;

  if (path === "/api/ping") return json(200, { app: APP, cloud: true });
  if (!db) return json(500, { error: "The database isn't connected. Check the D1 binding named DB in wrangler.jsonc." });
  await ensureSchema(db);

  if (method !== "GET" && !sameOrigin(request, url)) return json(403, { error: "Not allowed" });

  /* sign in / out */
  if (path === "/api/login" && method === "POST") {
    const pinSecret = (env.REGISTER_PIN || "").trim();
    if (!pinSecret) return json(503, { error: "No PIN has been set yet. In Cloudflare, add a secret named REGISTER_PIN to this Worker, then try again." });
    const ip = request.headers.get("CF-Connecting-IP") || "unknown";
    const now = Math.floor(Date.now() / 1000);
    await db.prepare("DELETE FROM login_failures WHERE ts < ?").bind(now - FAIL_WINDOW).run();
    const fails = await db.prepare("SELECT COUNT(*) AS n FROM login_failures WHERE ip = ?").bind(ip).first();
    if (fails && fails.n >= MAX_FAILS) return json(429, { error: "Too many wrong PINs. Wait 10 minutes and try again." });
    let pin = "";
    try { pin = String((await readBody(request)).pin || "").trim(); } catch { /* treat as wrong */ }
    if (!safeEqual(await sha256(pin), await sha256(pinSecret))) {
      await db.prepare("INSERT INTO login_failures (ip, ts) VALUES (?, ?)").bind(ip, now).run();
      await new Promise(r => setTimeout(r, 800));
      return json(403, { error: "Wrong PIN. Try again." });
    }
    const token = randomToken();
    await db.prepare("INSERT INTO tokens (token_hash, created, agent) VALUES (?, ?, ?)")
      .bind(await sha256(token), Date.now(), (request.headers.get("User-Agent") || "").slice(0, 200)).run();
    return json(200, { ok: true }, { "Set-Cookie": cookieHeader(token, TOKEN_DAYS * 86400) });
  }
  if (path === "/api/logout" && method === "POST") {
    const t = readCookie(request);
    if (t) await db.prepare("DELETE FROM tokens WHERE token_hash = ?").bind(await sha256(t)).run();
    return json(200, { ok: true }, { "Set-Cookie": cookieHeader("", 0) });
  }

  /* everything below needs a signed-in device */
  if (!(await validToken(db, readCookie(request)))) return json(401, { error: "PIN needed" });

  if (path === "/api/state" && method === "GET") {
    const since = url.searchParams.get("since") || "-1";
    const revRow = await db.prepare("SELECT v FROM kv WHERE k = 'rev'").first();
    const rev = +(revRow ? revRow.v : 0);
    if (since === String(rev)) return json(200, { rev, changed: false });
    const [studs, set] = await db.batch([
      db.prepare("SELECT id, doc FROM students"),
      db.prepare("SELECT v FROM kv WHERE k = 'settings'"),
    ]);
    const students = studs.results.map(r => ({ ...JSON.parse(r.doc), id: r.id }));
    const settings = set.results.length ? JSON.parse(set.results[0].v) : null;
    return json(200, { rev, students, settings });
  }

  if (path === "/api/info" && method === "GET") {
    return json(200, { lan_urls: [url.origin], cloud: true });
  }

  if (path === "/api/settings" && method === "PUT") {
    let body;
    try { body = await readBody(request); } catch (e) { return json(400, { error: e.message || "Bad data" }); }
    await db.prepare("INSERT INTO kv (k, v) VALUES ('settings', ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v")
      .bind(JSON.stringify(body)).run();
    return json(200, { rev: await bump(db) });
  }

  const m = path.match(/^\/api\/students\/([^/]+)$/);
  if (m && ["PUT", "PATCH", "DELETE"].includes(method)) {
    const id = decodeURIComponent(m[1]);
    if (!ID_RE.test(id)) return json(404, { error: "Not found" });
    if (method === "DELETE") {
      await db.prepare("DELETE FROM students WHERE id = ?").bind(id).run();
      return json(200, { rev: await bump(db) });
    }
    let body;
    try { body = await readBody(request); } catch (e) { return json(400, { error: e.message || "Bad data" }); }
    delete body.id;
    let doc = body;
    if (method === "PATCH") {
      const row = await db.prepare("SELECT doc FROM students WHERE id = ?").bind(id).first();
      if (!row) return json(404, { error: "That student no longer exists." });
      doc = { ...JSON.parse(row.doc), ...body };
    }
    await db.prepare(
      "INSERT INTO students (id, doc, updated) VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET doc = excluded.doc, updated = excluded.updated"
    ).bind(id, JSON.stringify(doc), new Date().toISOString()).run();
    return json(200, { rev: await bump(db) });
  }

  return json(404, { error: "Not found" });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname.startsWith("/api/")) {
      try {
        return await handleApi(request, env, url);
      } catch (e) {
        console.error(e);
        return json(500, { error: "Something went wrong on the server. Try again in a moment." });
      }
    }
    return env.ASSETS.fetch(request);
  },
};
