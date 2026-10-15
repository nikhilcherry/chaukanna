"""LiveKit access tokens for every role in a Chaukanna room.

    python tokens.py victim --ttl 48h          # JWT for the Flutter app's --dart-define=LIVEKIT_TOKEN
    python tokens.py caller --phone "+91 98765 43210" --label "CBI Officer"

Roles:
  guardian  hidden, subscribe-only, may send data (the bridge)
  victim    publish + subscribe + data          identity "victim"
  caller    publish + subscribe, no data        identity "caller-*", phone/label in metadata
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import timedelta

GUARDIAN_IDENTITY = "chaukanna-guardian"


def parse_ttl(s: str) -> timedelta:
    m = re.fullmatch(r"(\d+)([smhd]?)", s.strip())
    if not m:
        raise ValueError(f"bad ttl {s!r} (use e.g. 90s, 30m, 6h, 2d)")
    n, unit = int(m.group(1)), m.group(2) or "s"
    field = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}[unit]
    return timedelta(**{field: n})


def mint(role: str, room: str, identity: str = "", phone: str = "", label: str = "",
         ttl: timedelta = timedelta(hours=6), key: str = "", secret: str = "") -> str:
    from livekit import api
    key = key or os.environ["LIVEKIT_API_KEY"]
    secret = secret or os.environ["LIVEKIT_API_SECRET"]
    meta: dict = {}
    if role == "guardian":
        identity = identity or GUARDIAN_IDENTITY
        grants = api.VideoGrants(room_join=True, room=room, hidden=True, can_publish=False,
                                 can_subscribe=True, can_publish_data=True)
        name = "Chaukanna Guardian"
    elif role == "victim":
        identity = identity or "victim"
        grants = api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True,
                                 can_publish_data=True)
        meta = {"role": "victim"}
        name = label or "Victim"
    elif role == "caller":
        ident = re.sub(r"[^a-zA-Z0-9_-]", "", identity)[:40] or "dialer"
        identity = ident if ident.startswith("caller-") else "caller-" + ident
        grants = api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True,
                                 can_publish_data=False)
        meta = {"role": "caller", "phone": phone, "label": label}
        name = label or phone or identity
    else:
        raise ValueError(f"unknown role {role!r}")
    return (api.AccessToken(key, secret).with_identity(identity).with_name(name)
            .with_metadata(json.dumps(meta)).with_grants(grants).with_ttl(ttl).to_jwt())


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    ap = argparse.ArgumentParser(description="Mint a LiveKit token for a Chaukanna role")
    ap.add_argument("role", choices=["victim", "caller", "guardian"])
    ap.add_argument("--room", default=os.getenv("LIVEKIT_ROOM", "chaukanna"))
    ap.add_argument("--identity", default="")
    ap.add_argument("--phone", default="")
    ap.add_argument("--label", default="")
    ap.add_argument("--ttl", default="48h", help="lifetime, e.g. 6h or 2d (a token baked into an app build "
                                                  "must outlive the hackathon)")
    a = ap.parse_args()
    if not (os.getenv("LIVEKIT_API_KEY") and os.getenv("LIVEKIT_API_SECRET")):
        sys.exit("LIVEKIT_API_KEY / LIVEKIT_API_SECRET are not set (.env)")
    print(mint(a.role, a.room, a.identity, a.phone, a.label, parse_ttl(a.ttl)))
