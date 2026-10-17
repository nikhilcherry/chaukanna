"""Tiny token minter + static host for scammer_dialer.html (stdlib http.server).

    python token_server.py            # http://localhost:8787  (open it, that's the dialer)

Callers can only join as identity "caller-*", can publish audio, and cannot read data
messages meant for the victim. The phone number goes into participant metadata, which
the bridge reads as caller_number.

GET /victim-token?key=<VICTIM_TOKEN_KEY> -> {"token","url"} for the Flutter app's
--dart-define=LIVEKIT_TOKEN_URL. It is off (404) unless VICTIM_TOKEN_KEY is set, because a
victim token can read the guardian's data messages and the dialer is meant to be public.

GET /console/ is the guardian console (console/index.html): every call the bridge heard, replayed
chunk by chunk, or followed live. Its call API (/console/api/...) carries transcripts, so it only
answers on this machine (loopback) unless ?key=<CONSOLE_KEY> matches, and it sends no CORS header.
/console/api/health checks every part of the system for the console's status strip, and
/console/api/network joins the call logs, the classifier's lists and Supabase (through the n8n
feed workflow, CONTRACTS §7) into one graph.
"""
import hmac
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlsplit

from dotenv import load_dotenv
from livekit import api

import calllog
import tokens
from config import DEFAULT_CALL_LOG_DIR

load_dotenv()
HERE = Path(__file__).parent
CONSOLE = HERE / "console"
STATIC = {".html": "text/html; charset=utf-8", ".json": "application/json", ".jsonl": "application/x-ndjson",
          ".js": "text/javascript", ".css": "text/css", ".png": "image/png", ".jpg": "image/jpeg", ".svg": "image/svg+xml"}


def mint(room: str, identity: str, name: str, phone: str) -> str:
    grants = api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True, can_publish_data=False)
    return (api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
            .with_identity(identity).with_name(name or identity)
            .with_metadata(json.dumps({"phone": phone})).with_grants(grants).to_jwt())


def call_log_dir() -> str:
    return os.getenv("CALL_LOG_DIR", DEFAULT_CALL_LOG_DIR)


# --------------------------------------------------------------------------- system checks (console)
UA = "chaukanna-console/1"           # Cloudflare in front of n8n rejects urllib's default user agent
_cache: dict[str, tuple[float, object]] = {}
_cache_lock = threading.Lock()


def cached(key: str, ttl: float, fn):
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
    val = fn()
    with _cache_lock:
        _cache[key] = (time.monotonic(), val)
    return val


def get_json(url: str, headers: dict | None = None, timeout: float = 4.0):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"null")


def probe(fn) -> dict:
    """Run one check; never raises. {"ok", "ms", "data" | "error"}."""
    t0 = time.monotonic()
    try:
        return {"ok": True, "data": fn(), "ms": int((time.monotonic() - t0) * 1000)}
    except urllib.error.HTTPError as e:
        err = f"HTTP {e.code}"
    except (urllib.error.URLError, OSError) as e:
        err = str(getattr(e, "reason", e))[:120]
    except ValueError:
        err = "not JSON"
    return {"ok": False, "error": err, "ms": int((time.monotonic() - t0) * 1000)}


def classifier_base() -> str:
    u = os.getenv("CLASSIFIER_URL", "http://localhost:8010/classify").rstrip("/")
    return u[: -len("/classify")] if u.endswith("/classify") else u


def n8n_urls() -> tuple[str, str]:
    """(health URL, console feed URL) derived from N8N_WEBHOOK_URL; CONSOLE_FEED_URL overrides the feed."""
    hook = os.getenv("N8N_WEBHOOK_URL", "")
    if not hook:
        return "", os.getenv("CONSOLE_FEED_URL", "")
    p = urlsplit(hook)
    base = f"{p.scheme}://{p.netloc}"
    return base + "/healthz", os.getenv("CONSOLE_FEED_URL") or base + "/webhook/chaukanna-network"


def supabase_feed() -> dict:
    """Supabase incidents, scam numbers and trusted contacts via the n8n feed (no transcripts)."""
    _, url = n8n_urls()
    key = os.getenv("CONSOLE_FEED_KEY", "")
    if not url or not key:
        return {"ok": False, "error": "CONSOLE_FEED_KEY / N8N_WEBHOOK_URL not set", "ms": 0}
    return cached("feed", 30, lambda: probe(lambda: get_json(url, {"X-Chaukanna-Key": key}, timeout=8)))


def system_health() -> dict:
    health_url, _ = n8n_urls()
    with ThreadPoolExecutor(4) as ex:
        cls = ex.submit(probe, lambda: get_json(classifier_base() + "/health", timeout=2))
        n8n = ex.submit(probe, lambda: urllib.request.urlopen(
            urllib.request.Request(health_url, headers={"User-Agent": UA}), timeout=3).status) if health_url else None
        feed = ex.submit(supabase_feed)
        cls, n8n, feed = cls.result(), (n8n.result() if n8n else {"ok": False, "error": "N8N_WEBHOOK_URL not set"}), feed.result()
    st = calllog.read_status(call_log_dir()) if call_log_dir() else None
    age = round(time.time() - st["ts"], 1) if st else None
    bridge_ok = st is not None and age is not None and age < 3 * float(st.get("every_s") or 5)
    fam = (feed.get("data") or {}).get("trusted_contacts") or []
    out = {
        "livekit": {"ok": bridge_ok, "detail": f"room {st.get('room')}" if bridge_ok else "the bridge is not in the room"},
        "bridge": {"ok": bridge_ok, "age_s": age, "in_call": bool(st and st.get("in_call")),
                   "detail": ("in a call" if st.get("in_call") else "listening") if bridge_ok else
                   (f"last heartbeat {age:.0f}s ago" if age is not None else "no heartbeat yet")},
        "victim_phone": {"ok": bool(bridge_ok and st.get("victim_present")),
                         "detail": "connected" if bridge_ok and st.get("victim_present") else "not in the room"},
        "classifier": {"ok": cls["ok"] and not (cls.get("data") or {}).get("circuit_open"),
                       "detail": (f"{cls['data'].get('backend')} · {cls['data'].get('known_numbers')} listed numbers"
                                  + (" · model circuit open" if cls["data"].get("circuit_open") else "")) if cls["ok"] else cls["error"]},
        "n8n": {"ok": n8n["ok"], "detail": f"{n8n['ms']} ms" if n8n["ok"] else n8n.get("error", "")},
        "supabase": {"ok": feed["ok"], "detail": (f"{len(feed['data'].get('incidents', []))} incidents" if feed["ok"]
                                                  else feed.get("error", ""))},
        "telegram": {"ok": bool(feed["ok"] and any(c.get("telegram_ready") for c in fam)),
                     "detail": ("family chat id set" if any(c.get("telegram_ready") for c in fam) else
                                "no real family chat id yet") if feed["ok"] else "unknown (Supabase unreachable)"},
        "calls_log": {"ok": bool(call_log_dir()), "detail": call_log_dir() or "CALL_LOG_DIR is off"},
        "checked": time.time(),
    }
    return out


def network() -> dict:
    base = classifier_base()
    with ThreadPoolExecutor(3) as ex:
        nums = ex.submit(probe, lambda: get_json(base + "/scam_numbers", timeout=2))
        trusted = ex.submit(probe, lambda: get_json(base + "/trusted_numbers", timeout=2))
        feed = ex.submit(supabase_feed)
        nums, trusted, feed = nums.result(), trusted.result(), feed.result()
    return {
        "calls": calllog.summarize(call_log_dir(), limit=300) if call_log_dir() else [],
        "classifier": {"ok": nums["ok"], "scam_numbers": (nums.get("data") or {}).get("numbers", []),
                       "trusted": (trusted.get("data") or {}).get("numbers", []), "error": nums.get("error")},
        "supabase": {"ok": feed["ok"], **({k: feed["data"].get(k, []) for k in ("incidents", "scam_numbers", "trusted_contacts")}
                                          if feed["ok"] else {"error": feed.get("error")})},
        "default_victim_id": os.getenv("VICTIM_ID", "demo-victim-1"),
        "checked": time.time(),
    }


class H(BaseHTTPRequestHandler):
    def _send(self, code, body: bytes, ctype="application/json", cors=True, extra=()):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if cors:
            self.send_header("Access-Control-Allow-Origin", "*")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _console_allowed(self, q: dict) -> bool:
        want = os.getenv("CONSOLE_KEY", "")
        if want and hmac.compare_digest(q.get("key", "").encode(), want.encode()):
            return True
        return self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

    def _console(self, u) -> None:
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        rest = u.path[len("/console/"):]
        if rest.startswith("api/"):
            if not self._console_allowed(q):
                return self._send(403, b'{"error":"the console API answers on this machine only"}', cors=False)
            if rest in ("api/health", "api/network"):
                body = cached(rest, 4, system_health) if rest == "api/health" else cached(rest, 8, network)
                return self._send(200, json.dumps(body, ensure_ascii=False).encode(), cors=False,
                                  extra=[("Cache-Control", "no-store")])
            if rest == "api/calls":
                rows = calllog.summarize(call_log_dir())
                return self._send(200, json.dumps({"calls": rows, "dir_set": bool(call_log_dir())}).encode(),
                                  cors=False, extra=[("Cache-Control", "no-store")])
            m = re.fullmatch(r"api/calls/([A-Za-z0-9_-]{1,80})", rest)
            if m:
                start = int(q["from"]) if q.get("from", "").isdigit() else 0
                recs = calllog.read_call(call_log_dir(), m.group(1), start) if call_log_dir() else None
                if recs is None:
                    return self._send(404, b'{"error":"no such call"}', cors=False)
                return self._send(200, json.dumps({"from": start, "records": recs}, ensure_ascii=False).encode(),
                                  cors=False, extra=[("Cache-Control", "no-store")])
            return self._send(404, b'{"error":"not found"}', cors=False)
        if rest == "":
            rest = "index.html"
        f = (CONSOLE / rest).resolve()
        if not re.fullmatch(r"[A-Za-z0-9_./-]{1,120}", rest) or ".." in rest or CONSOLE.resolve() not in f.parents \
                or not f.is_file() or f.suffix not in STATIC:
            return self._send(404, b'{"error":"not found"}')
        self._send(200, f.read_bytes(), STATIC[f.suffix])

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/console":
            return self._send(302, b"", "text/plain", extra=[("Location", "/console/" + (f"?{u.query}" if u.query else ""))])
        if u.path.startswith("/console/"):
            return self._console(u)
        if u.path in ("/", "/scammer_dialer.html"):
            return self._send(200, (HERE / "scammer_dialer.html").read_bytes(), "text/html; charset=utf-8")
        if u.path == "/token":
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            room = q.get("room") or os.getenv("LIVEKIT_ROOM", "chaukanna")
            ident = re.sub(r"[^a-zA-Z0-9_-]", "", q.get("identity", ""))[:40] or "dialer"
            if not ident.startswith("caller-"):
                ident = "caller-" + ident
            tok = mint(room, ident, q.get("name", ""), q.get("phone", ""))
            return self._send(200, json.dumps({"token": tok, "url": os.getenv("LIVEKIT_URL", ""), "room": room, "identity": ident}).encode())
        if u.path == "/victim-token":
            want = os.getenv("VICTIM_TOKEN_KEY", "")
            got = parse_qs(u.query).get("key", [""])[0]
            if not want or not hmac.compare_digest(got.encode(), want.encode()):
                return self._send(404, b'{"error":"not found"}')
            room = os.getenv("LIVEKIT_ROOM", "chaukanna")
            tok = tokens.mint("victim", room, ttl=tokens.parse_ttl(os.getenv("VICTIM_TOKEN_TTL", "12h")))
            return self._send(200, json.dumps({"token": tok, "url": os.getenv("LIVEKIT_URL", ""), "room": room, "identity": "victim"}).encode())
        self._send(404, b'{"error":"not found"}')


if __name__ == "__main__":
    port = int(os.getenv("TOKEN_SERVER_PORT", "8787"))
    print(f"dialer + token server on http://0.0.0.0:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
