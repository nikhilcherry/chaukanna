"""Robot scammer: join the room as a caller and stream a WAV into it over WebRTC.

    python tools/robot_caller.py samples/scam_call_hinglish.wav
    python tools/robot_caller.py call.wav --phone "+92 300 1234567" --label "Customs Officer" --no-wait

Uses LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET from .env. On stage this is the
"robot scammer" demo mode: the victim's phone really hears the scam audio, and the live bridge
judges it exactly as it would a human caller. Stereo files: the left (caller) channel is used.
tests/test_live_e2e.py drives the same code against a local livekit-server.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tokens  # noqa: E402
from audio import load_wav_channels  # noqa: E402
from config import SAMPLE_RATE  # noqa: E402

log = logging.getLogger("chaukanna.robot")
FRAME = SAMPLE_RATE // 100                                    # 10 ms


async def stream_pcm(room, pcm: bytes, track_name: str = "mic") -> None:
    """Publish a mic track and play 16 kHz mono int16 PCM into it at real-time pace."""
    from livekit import rtc
    source = rtc.AudioSource(SAMPLE_RATE, 1)
    track = rtc.LocalAudioTrack.create_audio_track(track_name, source)
    await room.local_participant.publish_track(
        track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
    n = len(pcm) // 2
    for i in range(0, n, FRAME):
        seg = pcm[i * 2:(i + FRAME) * 2]
        if len(seg) < FRAME * 2:
            seg += b"\x00" * (FRAME * 2 - len(seg))
        await source.capture_frame(rtc.AudioFrame(seg, SAMPLE_RATE, 1, FRAME))   # blocks: real-time pace
    await source.wait_for_playout()
    await room.local_participant.unpublish_track(track.sid)
    await source.aclose()


def silence(seconds: float) -> bytes:
    return b"\x00\x00" * int(SAMPLE_RATE * seconds)


async def wait_for_identity(room, prefix: str, timeout: float) -> bool:
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if any(p.identity == prefix or p.identity.startswith(prefix + "-") for p in room.remote_participants.values()):
            return True
        await asyncio.sleep(0.2)
    return False


async def robot_call(url: str, token: str, pcm: bytes, lead_in: float = 1.5, linger: float = 1.0,
                     wait_victim: float = 0.0, victim_identity: str = "victim") -> None:
    from livekit import rtc
    room = rtc.Room()
    await room.connect(url, token)
    log.info("robot caller joined %s as %s", room.name, room.local_participant.identity)
    try:
        if wait_victim and not await wait_for_identity(room, victim_identity, wait_victim):
            log.warning("no victim joined within %.0fs; calling anyway", wait_victim)
        # lead-in silence: lets the guardian subscribe before the first words
        await stream_pcm(room, silence(lead_in) + pcm)
        await asyncio.sleep(linger)
    finally:
        await room.disconnect()                               # CLIENT_INITIATED: the bridge ends the call now
        log.info("robot caller hung up")


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("wav")
    ap.add_argument("--phone", default="+91 98765 43210")
    ap.add_argument("--label", default="CBI Officer (robot)")
    ap.add_argument("--room", default=os.getenv("LIVEKIT_ROOM", "chaukanna"))
    ap.add_argument("--url", default=os.getenv("LIVEKIT_URL", ""))
    ap.add_argument("--lead-in", type=float, default=1.5)
    ap.add_argument("--linger", type=float, default=1.0, help="seconds to stay after the audio ends")
    ap.add_argument("--no-wait", action="store_true", help="don't wait for the victim to join first")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not a.url or not os.getenv("LIVEKIT_API_KEY"):
        sys.exit("LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET are not set (.env)")
    pcm = load_wav_channels(a.wav)[0]
    tok = tokens.mint("caller", a.room, identity=f"caller-robot-{uuid.uuid4().hex[:4]}", phone=a.phone, label=a.label)
    asyncio.run(robot_call(a.url, tok, pcm, a.lead_in, a.linger, 0 if a.no_wait else 60,
                           os.getenv("VICTIM_IDENTITY", "victim")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
