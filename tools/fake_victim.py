"""Scripted victim: join as `victim`, print every guardian message, optionally speak a WAV.

    python tools/fake_victim.py                                   # see exactly what the app receives
    python tools/fake_victim.py --speak victim_lines.wav --out msgs.jsonl --until-call-ended

Uses LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET from .env. tests/test_live_e2e.py uses
the Victim class directly against a local livekit-server.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tokens  # noqa: E402
from audio import load_wav_channels  # noqa: E402
from config import DATA_TOPIC  # noqa: E402

log = logging.getLogger("chaukanna.victim")


class Victim:
    def __init__(self, echo: bool = False) -> None:
        self.messages: list[dict] = []
        self.room = None
        self.echo = echo
        self.events: dict[str, asyncio.Event] = {}

    def event(self, kind: str) -> asyncio.Event:
        return self.events.setdefault(kind, asyncio.Event())

    def _on_data(self, packet) -> None:
        if packet.topic != DATA_TOPIC:
            return
        try:
            msg = json.loads(bytes(packet.data).decode())
        except ValueError:
            log.warning("non-JSON data message")
            return
        msg["_rx"] = time.time()
        msg["_from"] = packet.participant.identity if packet.participant else None
        self.messages.append(msg)
        self.event(msg.get("type", "")).set()
        if self.echo:
            print(json.dumps({k: v for k, v in msg.items() if not k.startswith("_")}, ensure_ascii=False), flush=True)

    async def join(self, url: str, token: str) -> None:
        from livekit import rtc
        self.room = rtc.Room()
        self.room.on("data_received", self._on_data)
        await self.room.connect(url, token)
        log.info("victim joined %s as %s", self.room.name, self.room.local_participant.identity)

    async def speak(self, pcm: bytes, lead_in: float = 0.5) -> None:
        from tools.robot_caller import silence, stream_pcm
        await stream_pcm(self.room, silence(lead_in) + pcm, track_name="victim-mic")

    def of(self, kind: str) -> list[dict]:
        return [m for m in self.messages if m.get("type") == kind]

    async def leave(self) -> None:
        if self.room:
            await self.room.disconnect()


async def amain(a) -> None:
    v = Victim(echo=True)
    tok = tokens.mint("victim", a.room, identity=os.getenv("VICTIM_IDENTITY", "victim"))
    await v.join(a.url, tok)
    try:
        if a.speak:
            asyncio.create_task(v.speak(load_wav_channels(a.speak)[-1], lead_in=a.speak_after))
        if a.until_call_ended:
            await v.event("call_ended").wait()
            await asyncio.sleep(2)
        else:
            await asyncio.Event().wait()
    finally:
        if a.out:
            Path(a.out).write_text("\n".join(json.dumps(m, ensure_ascii=False) for m in v.messages) + "\n")
        await v.leave()


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--room", default=os.getenv("LIVEKIT_ROOM", "chaukanna"))
    ap.add_argument("--url", default=os.getenv("LIVEKIT_URL", ""))
    ap.add_argument("--speak", help="WAV to speak as the victim (stereo: right channel)")
    ap.add_argument("--speak-after", type=float, default=3.0)
    ap.add_argument("--out", help="write received messages as JSONL")
    ap.add_argument("--until-call-ended", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
    if not a.url or not os.getenv("LIVEKIT_API_KEY"):
        sys.exit("LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET are not set (.env)")
    try:
        asyncio.run(amain(a))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
