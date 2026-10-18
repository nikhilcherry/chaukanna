"""Stub classifier + stub n8n on one local port, for tests and offline rehearsal. Stdlib only.

    python tools/stubs.py --port 8791
    CLASSIFIER_URL=http://127.0.0.1:8791/classify
    N8N_WEBHOOK_URL=http://127.0.0.1:8791/webhook/chaukanna-verdict

POST /classify          keyword verdict (the bridge's mock), ratcheted per call like the real one
POST /reset/{call_id}   clears a call
GET|POST /scam_numbers  the shared scam list (the bridge adds every incident's caller)
POST /webhook/...       records the n8n event; `incident` gets the CONTRACTS §2 reply after --incident-delay
GET  /_log              everything received, as JSON (tests assert on it)
GET  /health
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import mock_verdict  # noqa: E402

LOCK = threading.Lock()
STATE: dict = {"classify": [], "reset": [], "n8n": [], "scam_numbers": [], "calls": {}}
INCIDENT_DELAY = 0.5


def classify(body: dict) -> dict:
    with LOCK:
        STATE["classify"].append({**body, "_rx": time.time()})
        call = STATE["calls"].setdefault(body["call_id"], {"text": [], "peak": 0, "otp": False, "secrecy": False,
                                                           "clips": set()})
        call["text"].append(body.get("chunk_text", ""))
        v = mock_verdict(body["call_id"], " ".join(call["text"][-6:]), body.get("language", "en"))
        v["pressure"] = call["peak"] = max(call["peak"], v["pressure"])
        v["asks_otp_or_pin"] = call["otp"] = call["otp"] or v["asks_otp_or_pin"]
        v["demands_secrecy"] = call["secrecy"] = call["secrecy"] or v["demands_secrecy"]
        clip = v["recommended_whisper_clip"]
        if clip in call["clips"]:                       # whisper-once, like the real classifier
            v["recommended_whisper_clip"] = "none"
        call["clips"].add(clip)
        v["summary_for_family"] = "stub classifier verdict"
        v.pop("degraded", None)
        v["source"] = "stub"
        return v


def incident_reply(body: dict) -> dict:
    return {"ok": True, "incident_id": str(uuid.uuid4()), "call_id": body.get("call_id"),
            "known_scammer": False, "family_alerted": True, "evidence_saved": True, "blocklisted": False,
            "complaint_draft": {"en": "Stub complaint draft.", "local": "स्टब शिकायत", "language": "hi"},
            "family_alert": "• stub alert line 1\n• stub alert line 2\n• stub alert line 3",
            "approve_url": "http://127.0.0.1/stub-approve"}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code: int, obj) -> None:
        b = json.dumps(obj, ensure_ascii=False, default=list).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}

    def do_GET(self):
        if self.path == "/health":
            return self._json(200, {"ok": True, "backend": "stub"})
        if self.path == "/_log":
            with LOCK:
                return self._json(200, {k: v for k, v in STATE.items() if k != "calls"})
        if self.path == "/scam_numbers":
            with LOCK:
                return self._json(200, {"numbers": list(STATE["scam_numbers"]), "risky_country_codes": {}})
        self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/classify":
            return self._json(200, classify(self._body()))
        if self.path == "/scam_numbers":
            body = self._body()
            with LOCK:
                STATE["scam_numbers"].append(body)
            return self._json(200, {"added": body.get("number", "")})
        if self.path.startswith("/reset/"):
            cid = self.path.rsplit("/", 1)[1]
            with LOCK:
                STATE["reset"].append(cid)
                cleared = STATE["calls"].pop(cid, None) is not None
            return self._json(200, {"call_id": cid, "cleared": cleared})
        if self.path.startswith("/webhook/"):
            body = self._body()
            body["_received_at"] = time.time()
            with LOCK:
                STATE["n8n"].append(body)
            if body.get("event") == "incident":
                time.sleep(INCIDENT_DELAY)
                return self._json(200, incident_reply(body))
            return self._json(200, {"ok": True})
        self._json(404, {"error": "not found"})


def serve(port: int, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((host, port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--incident-delay", type=float, default=0.5)
    a = ap.parse_args()
    INCIDENT_DELAY = a.incident_delay
    print(f"stub classifier + n8n on http://127.0.0.1:{a.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()
