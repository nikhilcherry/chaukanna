"""Tiny token minter + static host for scammer_dialer.html (stdlib http.server).

    python token_server.py            # http://localhost:8787  (open it, that's the dialer)

Callers can only join as identity "caller-*", can publish audio, and cannot read data
messages meant for the victim. The phone number goes into participant metadata, which
the bridge reads as caller_number.

GET /victim-token?key=<VICTIM_TOKEN_KEY> -> {"token","url"} for the Flutter app's
--dart-define=LIVEKIT_TOKEN_URL. It is off (404) unless VICTIM_TOKEN_KEY is set, because a
victim token can read the guardian's data messages and the dialer is meant to be public.
"""
import hmac
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
from livekit import api

import tokens

load_dotenv()
HERE = Path(__file__).parent


def mint(room: str, identity: str, name: str, phone: str) -> str:
    grants = api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True, can_publish_data=False)
    return (api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
            .with_identity(identity).with_name(name or identity)
            .with_metadata(json.dumps({"phone": phone})).with_grants(grants).to_jwt())


class H(BaseHTTPRequestHandler):
    def _send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
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
