"""Chaukanna audio bridge.

Joins a LiveKit room as a hidden observer, slices every participant's audio into
4 s / 16 kHz / mono WAV chunks in memory, transcribes them with Sarvam STT, asks the
classifier for a verdict, then:

  fast path: LiveKit data message to the victim only (transcript + verdict + whisper trigger)
  slow path: async POST to the n8n webhook when pressure >= 2 (once per 30 s per call)

`--replay-file call.wav` feeds a recording through the same pipeline in real time.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import os
import sys
import time
import wave
from dataclasses import dataclass, field

import httpx
import numpy as np
from dotenv import load_dotenv

SAMPLE_RATE = 16000
CHUNK_SECONDS = 4
CHUNK_BYTES = SAMPLE_RATE * CHUNK_SECONDS * 2          # int16 mono -> 128,000
MIN_FLUSH_BYTES = SAMPLE_RATE * 2                      # flush a track tail only if >= 1 s
DATA_TOPIC = "chaukanna.verdict"
GUARDIAN_IDENTITY = "chaukanna-guardian"
SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"

log = logging.getLogger("chaukanna.bridge")


# --------------------------------------------------------------------------- config
@dataclass
class Config:
    livekit_url: str = ""
    api_key: str = ""
    api_secret: str = ""
    room: str = "chaukanna"
    victim_identity: str = "victim"
    sarvam_key: str = ""
    stt_model: str = "saaras:v3"
    stt_mode: str = "transcribe"
    classifier_url: str = "http://localhost:8000/classify"
    n8n_url: str = ""
    n8n_cooldown: float = 30.0
    n8n_pressure: int = 2
    silence_rms: float = 120.0
    mock_stt: bool = False

    @classmethod
    def from_env(cls) -> "Config":
        e = os.getenv
        return cls(
            livekit_url=e("LIVEKIT_URL", ""),
            api_key=e("LIVEKIT_API_KEY", ""),
            api_secret=e("LIVEKIT_API_SECRET", ""),
            room=e("LIVEKIT_ROOM", "chaukanna"),
            victim_identity=e("VICTIM_IDENTITY", "victim"),
            sarvam_key=e("SARVAM_API_KEY", ""),
            stt_model=e("SARVAM_STT_MODEL", "saaras:v3"),
            stt_mode=e("SARVAM_STT_MODE", "transcribe"),
            classifier_url=e("CLASSIFIER_URL", "http://localhost:8000/classify"),
            n8n_url=e("N8N_WEBHOOK_URL", ""),
            n8n_cooldown=float(e("N8N_COOLDOWN_SECONDS", "30")),
            n8n_pressure=int(e("N8N_PRESSURE_THRESHOLD", "2")),
            silence_rms=float(e("SILENCE_RMS", "120")),
        )


# --------------------------------------------------------------------------- audio helpers
def pcm_to_wav(pcm: bytes) -> bytes:
    """Raw 16 kHz mono int16 PCM -> WAV file bytes, entirely in memory."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return buf.getvalue()


def rms(pcm: bytes) -> float:
    if not pcm:
        return 0.0
    a = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    return float(np.sqrt(np.mean(a * a)))


def load_wav_16k_mono(path: str) -> bytes:
    """Read any PCM WAV and return 16 kHz mono int16 bytes (linear resample)."""
    with wave.open(path, "rb") as w:
        ch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    dtype = {1: np.uint8, 2: np.int16, 4: np.int32}.get(width)
    if dtype is None:
        raise ValueError(f"unsupported WAV sample width: {width} bytes")
    a = np.frombuffer(raw, dtype=dtype).astype(np.float64)
    if width == 1:
        a = (a - 128) * 256
    elif width == 4:
        a /= 65536
    if ch > 1:
        a = a[: len(a) // ch * ch].reshape(-1, ch).mean(axis=1)
    if rate != SAMPLE_RATE and len(a):
        t_new = np.arange(int(len(a) * SAMPLE_RATE / rate)) * rate / SAMPLE_RATE
        a = np.interp(t_new, np.arange(len(a)), a)
    return np.clip(a, -32768, 32767).astype(np.int16).tobytes()


class Chunker:
    """Accumulates PCM and yields exact 4-second chunks."""

    def __init__(self) -> None:
        self.buf = bytearray()

    def push(self, pcm: bytes) -> list[bytes]:
        self.buf += pcm
        out = []
        while len(self.buf) >= CHUNK_BYTES:
            out.append(bytes(self.buf[:CHUNK_BYTES]))
            del self.buf[:CHUNK_BYTES]
        return out

    def tail(self) -> bytes | None:
        t = bytes(self.buf) if len(self.buf) >= MIN_FLUSH_BYTES else None
        self.buf.clear()
        return t


# --------------------------------------------------------------------------- mock fallbacks
_SCAM_WORDS = {
    "digital_arrest": ["cbi", "digital arrest", "arrest", "police", "narcotics", "money laundering", "warrant", "पुलिस", "गिरफ्तार"],
    "kyc_update": ["kyc", "aadhaar", "aadhar", "pan card", "blocked", "anydesk", "आधार"],
    "bank_impersonation": ["bank", "card", "cvv", "upi", "transaction"],
    "prize_lottery": ["lottery", "prize", "winner", "lucky"],
}


def mock_verdict(call_id: str, text: str, language: str) -> dict:
    """Offline keyword heuristic, used only when the classifier server is unreachable."""
    t = text.lower()
    scam, hits = "none", 0
    for kind, words in _SCAM_WORDS.items():
        h = sum(w in t for w in words)
        if h > hits:
            scam, hits = kind, h
    otp = any(w in t for w in ("otp", "pin", "cvv", "password", "ओटीपी"))
    secrecy = any(w in t for w in ("don't tell", "do not tell", "tell no one", "secret", "confidential", "किसी को न बताएं"))
    pressure = min(3, hits + int(otp) + int(secrecy))
    clip = "warn_otp" if otp else "warn_secrecy" if secrecy else "warn_digital_arrest" if scam == "digital_arrest" else "none"
    return {
        "call_id": call_id, "scam_type": scam, "pressure": pressure, "asks_otp_or_pin": otp,
        "demands_secrecy": secrecy, "confidence": 0.4, "language": language if language in ("hi", "kn") else "en",
        "recommended_whisper_clip": clip, "summary_for_family": "(mock verdict: classifier unreachable)",
    }


MOCK_SCRIPT = [
    "Hello, this is Inspector Sharma from CBI Mumbai.",
    "A parcel in your name contains illegal narcotics and fake passports.",
    "You are under digital arrest. Do not tell anyone and do not disconnect the call.",
    "To verify your account, tell me the OTP that you just received.",
]


# --------------------------------------------------------------------------- pipeline
@dataclass
class CallState:
    call_id: str
    caller_number: str = ""
    victim_id: str = ""
    transcript: list[dict] = field(default_factory=list)
    last_n8n: float = 0.0


class Pipeline:
    """chunk -> STT -> classifier -> (victim data message, n8n). Same code for live and replay."""

    def __init__(self, cfg: Config, http: httpx.AsyncClient, publish) -> None:
        self.cfg, self.http, self.publish = cfg, http, publish   # publish(payload: bytes) coroutine
        self.calls: dict[str, CallState] = {}
        self._bg: set[asyncio.Task] = set()
        self._mock_i = 0

    def call(self, call_id: str) -> CallState:
        return self.calls.setdefault(call_id, CallState(call_id=call_id))

    async def process_chunk(self, call_id: str, speaker: str, pcm: bytes) -> dict | None:
        if rms(pcm) < self.cfg.silence_rms:
            log.debug("%s/%s: silent chunk skipped", call_id, speaker)
            return None
        st = self.call(call_id)
        wav = await asyncio.to_thread(pcm_to_wav, pcm)
        text, lang = await self.transcribe(wav)
        if not text:
            return None
        st.transcript.append({"speaker": speaker, "text": text, "ts": time.time()})
        del st.transcript[:-200]
        verdict = await self.classify(st, speaker, text, lang)
        payload = {
            "type": "verdict", "call_id": call_id, "speaker": speaker, "chunk_text": text,
            "language": lang, "verdict": verdict, "pressure": verdict["pressure"],
            "whisper": verdict["recommended_whisper_clip"] != "none", "ts": time.time(),
        }
        await self.publish(json.dumps(payload, ensure_ascii=False).encode())
        log.info("[%s] %s: %r -> %s p=%d", call_id, speaker, text[:60], verdict["scam_type"], verdict["pressure"])
        self.maybe_fire_n8n(st, verdict)
        return payload

    async def transcribe(self, wav: bytes) -> tuple[str, str]:
        if self.cfg.mock_stt:
            text = MOCK_SCRIPT[self._mock_i % len(MOCK_SCRIPT)]
            self._mock_i += 1
            return text, "en"
        if not self.cfg.sarvam_key:
            raise RuntimeError("SARVAM_API_KEY is not set (use --mock-stt for offline wiring tests)")
        data = {"model": self.cfg.stt_model}
        if self.cfg.stt_model.startswith("saaras"):
            data["mode"] = self.cfg.stt_mode
        try:
            r = await self.http.post(
                SARVAM_STT_URL, headers={"api-subscription-key": self.cfg.sarvam_key},
                files={"file": ("chunk.wav", wav, "audio/wav")}, data=data, timeout=15)
            r.raise_for_status()
        except httpx.HTTPError as e:
            log.warning("Sarvam STT failed: %s", e)
            return "", "en"
        j = r.json()
        code = (j.get("language_code") or "en").split("-")[0]
        return (j.get("transcript") or "").strip(), code if code in ("hi", "kn") else "en"

    async def classify(self, st: CallState, speaker: str, text: str, lang: str) -> dict:
        body = {"call_id": st.call_id, "caller_number": st.caller_number, "speaker": speaker,
                "chunk_text": text, "language": lang}
        try:
            r = await self.http.post(self.cfg.classifier_url, json=body, timeout=6)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("classifier unavailable (%s), using mock fallback", e.__class__.__name__)
            return mock_verdict(st.call_id, " ".join(t["text"] for t in st.transcript[-6:]), lang)

    def maybe_fire_n8n(self, st: CallState, verdict: dict) -> None:
        now = time.monotonic()
        if verdict["pressure"] < self.cfg.n8n_pressure or not self.cfg.n8n_url:
            return
        if st.last_n8n and now - st.last_n8n < self.cfg.n8n_cooldown:
            return
        st.last_n8n = now
        body = {
            "call_id": st.call_id, "caller_number": st.caller_number, "victim_id": st.victim_id,
            "verdict": verdict, "ts": time.time(),
            "transcript": [{"speaker": t["speaker"], "text": t["text"]} for t in st.transcript],
            "transcript_text": "\n".join(f'{t["speaker"]}: {t["text"]}' for t in st.transcript),
        }
        task = asyncio.create_task(self._post_n8n(body))
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    async def _post_n8n(self, body: dict) -> None:
        for attempt in (1, 2, 3):
            try:
                r = await self.http.post(self.cfg.n8n_url, json=body, timeout=10)
                r.raise_for_status()
                log.info("n8n incident fired for %s (pressure %d)", body["call_id"], body["verdict"]["pressure"])
                return
            except httpx.HTTPError as e:
                log.warning("n8n POST attempt %d failed: %s", attempt, e)
                await asyncio.sleep(2 * attempt)

    async def drain(self) -> None:
        if self._bg:
            await asyncio.gather(*self._bg, return_exceptions=True)


# --------------------------------------------------------------------------- live mode
def guardian_token(cfg: Config) -> str:
    from livekit import api
    grants = api.VideoGrants(room_join=True, room=cfg.room, hidden=True, can_publish=False,
                             can_subscribe=True, can_publish_data=True)
    return (api.AccessToken(cfg.api_key, cfg.api_secret).with_identity(GUARDIAN_IDENTITY)
            .with_name("Chaukanna Guardian").with_grants(grants).to_jwt())


def participant_info(p) -> dict:
    try:
        meta = json.loads(p.metadata) if p.metadata else {}
    except ValueError:
        meta = {}
    return meta if isinstance(meta, dict) else {}


async def run_live(cfg: Config, http: httpx.AsyncClient) -> None:
    from livekit import rtc

    room = rtc.Room()
    disconnected = asyncio.Event()
    tracks: dict[str, asyncio.Task] = {}

    async def publish(payload: bytes) -> None:
        try:
            await room.local_participant.publish_data(
                payload, reliable=True, destination_identities=[cfg.victim_identity], topic=DATA_TOPIC)
        except Exception as e:                                    # never let a send kill the pipeline
            log.warning("publish_data failed: %s", e)

    pipe = Pipeline(cfg, http, publish)

    async def consume(track, participant) -> None:
        is_victim = participant.identity == cfg.victim_identity
        speaker = "victim" if is_victim else "caller"
        st = pipe.call(room.name)
        info = participant_info(participant)
        if is_victim:
            st.victim_id = info.get("victim_id") or participant.identity
        else:
            st.caller_number = info.get("phone") or participant.name or participant.identity
        queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=3)

        async def worker() -> None:
            while True:
                pcm = await queue.get()
                try:
                    await pipe.process_chunk(room.name, speaker, pcm)
                except Exception:
                    log.exception("chunk processing failed")

        w = asyncio.create_task(worker())
        stream = rtc.AudioStream(track, sample_rate=SAMPLE_RATE, num_channels=1)
        chunker = Chunker()
        log.info("subscribed to %s (%s)", participant.identity, speaker)
        try:
            async for ev in stream:
                for chunk in chunker.push(ev.frame.data.tobytes()):
                    if queue.full():                              # STT is behind: drop oldest, stay live
                        queue.get_nowait()
                    queue.put_nowait(chunk)
        finally:
            tail = chunker.tail()
            if tail:
                queue.put_nowait(tail)
            while not queue.empty():                              # let the worker finish what is queued
                await asyncio.sleep(0.2)
            w.cancel()
            await stream.aclose()

    @room.on("track_subscribed")
    def _on_sub(track, publication, participant):
        if track.kind != rtc.TrackKind.KIND_AUDIO or participant.identity == GUARDIAN_IDENTITY:
            return
        tracks[publication.sid] = asyncio.create_task(consume(track, participant))

    @room.on("track_unsubscribed")
    def _on_unsub(track, publication, participant):
        log.info("track from %s ended", participant.identity)

    @room.on("disconnected")
    def _on_disc(*_):
        disconnected.set()

    token = os.getenv("LIVEKIT_TOKEN") or guardian_token(cfg)
    await room.connect(cfg.livekit_url, token, options=rtc.RoomOptions(auto_subscribe=True))
    log.info("joined room %s as %s (hidden)", room.name, GUARDIAN_IDENTITY)
    try:
        await disconnected.wait()
    finally:
        for t in tracks.values():
            t.cancel()
        await pipe.drain()
        await room.disconnect()


# --------------------------------------------------------------------------- replay mode
async def run_replay(cfg: Config, http: httpx.AsyncClient, args) -> None:
    pcm = load_wav_16k_mono(args.replay_file)
    chunks = Chunker().push(pcm + b"\x00" * ((-len(pcm)) % CHUNK_BYTES))   # pad the tail to a full chunk
    call_id = args.call_id or f"replay-{os.path.splitext(os.path.basename(args.replay_file))[0]}"
    log.info("replay: %d chunks of %ds from %s", len(chunks), CHUNK_SECONDS, args.replay_file)

    room = None
    publish = None
    if not args.no_livekit:
        try:
            from livekit import rtc
            room = rtc.Room()
            await asyncio.wait_for(room.connect(cfg.livekit_url, os.getenv("LIVEKIT_TOKEN") or guardian_token(cfg)), 15)

            async def publish(payload: bytes) -> None:
                await room.local_participant.publish_data(
                    payload, reliable=True, destination_identities=[cfg.victim_identity], topic=DATA_TOPIC)
            log.info("replay: publishing to room %s", room.name)
        except Exception as e:
            log.warning("replay: LiveKit unavailable (%s) - verdicts print to stdout only", e)
            room = None
    if publish is None:
        async def publish(payload: bytes) -> None:
            print(payload.decode(), flush=True)

    pipe = Pipeline(cfg, http, publish)
    st = pipe.call(call_id)
    st.caller_number, st.victim_id = args.caller_number, args.victim_id
    tick = CHUNK_SECONDS / args.speed
    try:
        for i, chunk in enumerate(chunks):
            started = time.monotonic()
            task = asyncio.create_task(pipe.process_chunk(call_id, args.replay_speaker, chunk))
            await asyncio.sleep(max(0.0, tick - (time.monotonic() - started)))   # real-time pacing
            await task
            log.debug("replay chunk %d/%d done", i + 1, len(chunks))
        await pipe.drain()
    finally:
        if room is not None:
            await room.disconnect()


# --------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="Chaukanna LiveKit audio bridge")
    ap.add_argument("--replay-file", help="WAV to feed through the pipeline instead of live room audio")
    ap.add_argument("--replay-speaker", choices=["caller", "victim"], default="caller")
    ap.add_argument("--caller-number", default="+919876543210")
    ap.add_argument("--victim-id", default="victim")
    ap.add_argument("--call-id", help="override call id (default: room name / replay-<file>)")
    ap.add_argument("--speed", type=float, default=1.0, help="replay speed factor (1.0 = real time)")
    ap.add_argument("--no-livekit", action="store_true", help="replay without joining a room; print verdicts")
    ap.add_argument("--mock-stt", action="store_true", help="skip Sarvam; canned transcript (wiring tests)")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    load_dotenv()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    cfg = Config.from_env()
    cfg.mock_stt = args.mock_stt

    missing = []
    if not cfg.mock_stt and not cfg.sarvam_key:
        missing.append("SARVAM_API_KEY")
    if not args.replay_file and not cfg.livekit_url:
        missing.append("LIVEKIT_URL")
    if not args.replay_file and not os.getenv("LIVEKIT_TOKEN") and not (cfg.api_key and cfg.api_secret):
        missing.append("LIVEKIT_API_KEY/LIVEKIT_API_SECRET")
    if missing:                                                    # replay degrades to stdout without LiveKit
        print("missing config: " + ", ".join(missing), file=sys.stderr)
        return 2

    async def go() -> None:
        async with httpx.AsyncClient() as http:
            if args.replay_file:
                await run_replay(cfg, http, args)
                return
            delay = 1.0
            while True:                                           # reconnect forever with backoff
                try:
                    await run_live(cfg, http)
                    delay = 1.0
                except Exception as e:
                    log.error("room session failed: %s", e)
                log.info("reconnecting in %.0fs", delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)

    try:
        asyncio.run(go())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
