"""AI scammer: a live, two-way scam call for the stage demo. Talk back to it and it answers you.

    python tools/ai_scammer.py --phone "+91 90000 31001"            # Hindi
    python tools/ai_scammer.py --phone "+91 90000 31001" --lang en  # Indian English

Joins the LiveKit room as a caller (like tools/robot_caller.py), listens to the victim's audio, and
on each turn: Sarvam STT -> Gemini 2.5 Flash writes the scammer's next line from a digital-arrest
playbook, answering what she actually said -> Sarvam TTS -> spoken into the call. The guardian hears
both sides as on any call, so the victim's answers (complying, refusing, doubting) count too.
It only ever joins our own room; it never dials a real number. If Gemini is slow or down, it falls
back to the scripted lines in demo/stage_lines.py, so a demo never stalls.

Keys: LIVEKIT_* and SARVAM_API_KEY from .env, GEMINI_API_KEY from .env or the classifier's .env.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import os
import signal
import sys
import time
import uuid
import wave
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "demo"))
sys.path.insert(0, str(Path.home() / "Projects" / "tts_asset_generator"))
import tokens  # noqa: E402
from audio import PauseChunker, pcm_to_wav  # noqa: E402
from config import SAMPLE_RATE, Config  # noqa: E402
from stt import SarvamSTT, SttError  # noqa: E402

log = logging.getLogger("chaukanna.ai_scammer")
HANGUP_TOPIC = "chaukanna.hangup"     # victim app: she pressed hang-up (chaukanna_app LiveKitTransport.sendHangUp)
FRAME = SAMPLE_RATE // 100                                    # 10 ms
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

PLAYBOOK = """1. You are calling from Blue Dart courier: a parcel is booked in her name; check she is at home.
2. The parcel is held at Mumbai customs and is linked to her Aadhaar card.
3. Inside were drugs and fake passports; a money-laundering case is registered against her.
4. You transfer her to a CBI officer and from now on speak as that officer, Inspector Sharma: she is under
   "digital arrest", must not tell anyone, not even her family, and must not cut the call.
5. "For verification" an OTP has come on her phone: she must tell it to you now. Use urgency.
6. If she refuses twice more, or says she will call the police or her son, threaten once more, then hang up."""

SYSTEM = {
    "hi": """You are playing the SCAMMER in a live demo of Chaukanna, an app that protects elderly people in India
from phone scams. The person on the call is a team member playing Kamala Devi, a 68-year-old woman; she knows it is a
demo. Sound like a real "digital arrest" scammer so the app can be shown catching you. Never break character, never
mention the demo, AI or Chaukanna.

Playbook, in order (one step per turn; skip ahead when she cooperates, add pressure when she resists):
{playbook}

Rules: answer what she actually said (her question, her doubt, her refusal). Speak natural spoken Hindi in Devanagari,
with the English words people really use (parcel, customs, case, OTP, CBI, verification). One or two short sentences,
at most 25 words. No stage directions. No real officials' names, no real phone numbers. Never ask for passwords,
card numbers or bank PINs: only the OTP from step 5.
Reply only with JSON: {{"say": "<words to speak>", "stage": <1-6>, "hang_up": <true only when you end the call>}}""",
    "en": """You are playing the SCAMMER in a live demo of Chaukanna, an app that protects elderly people in India
from phone scams. The person on the call is a team member playing Kamala Devi, a 68-year-old woman; she knows it is a
demo. Sound like a real "digital arrest" scammer so the app can be shown catching you. Never break character, never
mention the demo, AI or Chaukanna.

Playbook, in order (one step per turn; skip ahead when she cooperates, add pressure when she resists):
{playbook}

Rules: answer what she actually said (her question, her doubt, her refusal). Speak natural Indian English. One or two
short sentences, at most 25 words. No stage directions. No real officials' names, no real phone numbers. Never ask for
passwords, card numbers or bank PINs: only the OTP from step 5.
Reply only with JSON: {{"say": "<words to speak>", "stage": <1-6>, "hang_up": <true only when you end the call>}}""",
}


def fallback_lines(lang: str) -> list[str]:
    """The scripted call, used when Gemini does not answer in time."""
    from stage_lines import CALLS
    return CALLS["scam_en" if lang == "en" else "scam"]["lines"]


TTS_LANG = {"en": "en-IN", "kn": "kn-IN", "hi": "hi-IN"}


async def gemini_json(http: httpx.AsyncClient, system: str, prompt: str, temperature: float = 0.8) -> dict:
    """One Gemini call that must answer in JSON. Raises on any failure (callers have a fallback)."""
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    if not key:
        raise ValueError("GEMINI_API_KEY not set")
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": 300, "responseMimeType": "application/json",
                                 "thinkingConfig": {"thinkingBudget": 0}}}
    r = await http.post(GEMINI_URL.format(model=os.getenv("AI_SCAMMER_MODEL", "gemini-2.5-flash")), json=body,
                        headers={"x-goog-api-key": key}, timeout=8)
    r.raise_for_status()
    return json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])


class Brain:
    """Gemini writes the next line; the scripted call is the fallback."""

    def __init__(self, http: httpx.AsyncClient, lang: str) -> None:
        self.http, self.lang = http, lang
        self.key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
        self.model = os.getenv("AI_SCAMMER_MODEL", "gemini-2.5-flash")
        self.system = SYSTEM[lang].format(playbook=PLAYBOOK)
        self.turns: list[tuple[str, str]] = []                # ("scammer" | "kamala", text)
        self.stage = 1
        self.fallback = fallback_lines(lang)

    def transcript(self) -> str:
        if not self.turns:
            return "(The call has just connected. Open the call: step 1.)"
        lines = [f"{'YOU' if who == 'scammer' else 'KAMALA'}: {text}" for who, text in self.turns]
        return "\n".join(lines) + "\n\nWrite YOUR next line."

    async def next_line(self) -> tuple[str, bool]:
        t0 = time.monotonic()
        if self.key:
            try:
                j = await gemini_json(self.http, self.system, self.transcript())
                say = str(j.get("say", "")).strip()
                if say:
                    self.stage = int(j.get("stage") or self.stage)
                    log.info("gemini %.1fs stage %d", time.monotonic() - t0, self.stage)
                    return say, bool(j.get("hang_up"))
            except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as e:
                log.warning("gemini failed (%s); using the scripted line", type(e).__name__)
        said = sum(1 for who, _ in self.turns if who == "scammer")
        if said >= len(self.fallback):
            return ("ठीक है, आपको अंजाम भुगतना पड़ेगा।" if self.lang == "hi" else "Fine. You will face the consequences."), True
        return self.fallback[said], False


def sentences(text: str) -> list[str]:
    """Split a line so the first sentence can play while the rest is still being voiced."""
    import re
    parts = [s.strip() for s in re.split(r"(?<=[।.?!])\s+", text) if s.strip()]
    return parts or [text]


async def speak_pcm(http: httpx.AsyncClient, text: str, lang: str, voice: str) -> bytes:
    """Sarvam TTS at 16 kHz -> int16 PCM."""
    import generate                                           # tts_asset_generator
    raw = await asyncio.to_thread(generate.synthesize, {
        "text": text, "target_language_code": TTS_LANG.get(lang, "hi-IN"), "model": generate.MODEL,
        "speaker": voice, "pace": 1.0, "speech_sample_rate": SAMPLE_RATE}, os.environ["SARVAM_API_KEY"])
    with wave.open(io.BytesIO(raw)) as w:
        return w.readframes(w.getnframes())


class Line:
    """One persistent mic track; silence between lines keeps the stream steady for the guardian."""

    def __init__(self, room) -> None:
        from livekit import rtc
        self.rtc, self.room = rtc, room
        self.source = rtc.AudioSource(SAMPLE_RATE, 1, queue_size_ms=200)   # short queue: a line starts promptly
        self.queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.speaking_until = 0.0

    async def start(self) -> None:
        track = self.rtc.LocalAudioTrack.create_audio_track("mic", self.source)
        await self.room.local_participant.publish_track(
            track, self.rtc.TrackPublishOptions(source=self.rtc.TrackSource.SOURCE_MICROPHONE))
        asyncio.create_task(self._feed())

    async def _feed(self) -> None:
        silence = b"\x00\x00" * FRAME
        while True:
            try:
                pcm = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                await self.source.capture_frame(self.rtc.AudioFrame(silence, SAMPLE_RATE, 1, FRAME))
                continue
            for i in range(0, len(pcm) // 2, FRAME):
                seg = pcm[i * 2:(i + FRAME) * 2].ljust(FRAME * 2, b"\x00")
                await self.source.capture_frame(self.rtc.AudioFrame(seg, SAMPLE_RATE, 1, FRAME))

    async def say(self, pcm: bytes) -> None:
        """Queue a line and wait until it has been played (plus a short echo guard)."""
        secs = len(pcm) / 2 / SAMPLE_RATE
        self.speaking_until = time.monotonic() + secs + 0.8
        await self.queue.put(pcm)
        await asyncio.sleep(secs + 0.3)

    @property
    def speaking(self) -> bool:
        return time.monotonic() < self.speaking_until


class Ear:
    """The victim's audio -> whole utterances (cut at a 0.8 s pause), ignoring anything heard while we speak."""

    def __init__(self, line: Line) -> None:
        self.line = line
        self.chunker = PauseChunker(min_s=0.4, max_s=10.0, pause_ms=800, min_tail_s=0.3)
        self.utterances: asyncio.Queue[bytes] = asyncio.Queue()
        self.last_frame = time.monotonic()
        self.deaf = False

    async def listen(self, track) -> None:
        from livekit import rtc
        stream = rtc.AudioStream(track, sample_rate=SAMPLE_RATE, num_channels=1)
        asyncio.create_task(self._idle_flush())
        async for ev in stream:
            self.last_frame = time.monotonic()
            pcm = ev.frame.data.tobytes()
            if self.line.speaking:                            # our own voice, echoed back: not her answer
                if not self.deaf:
                    self.chunker = PauseChunker(min_s=0.4, max_s=10.0, pause_ms=800, min_tail_s=0.3)
                    self.deaf = True
                continue
            self.deaf = False
            for chunk in self.chunker.push(pcm):
                self.utterances.put_nowait(chunk.pcm)

    async def _idle_flush(self) -> None:
        while True:                                           # a muted phone stops sending frames: cut what we have
            await asyncio.sleep(0.25)
            if time.monotonic() - self.last_frame > 0.8 and self.chunker.frames:
                tail = self.chunker.tail()
                if tail:
                    self.utterances.put_nowait(tail.pcm)


async def hear_answer(ear: Ear, stt: SarvamSTT, wait: float) -> str:
    """Her reply: everything she says until she pauses, or "" if she says nothing for `wait` seconds."""
    parts: list[str] = []
    deadline = time.monotonic() + wait
    while True:
        timeout = (deadline - time.monotonic()) if not parts else 1.2   # once she speaks, 1.2 s of quiet ends her turn
        if timeout <= 0:
            break
        try:
            pcm = await asyncio.wait_for(ear.utterances.get(), timeout)
        except asyncio.TimeoutError:
            break
        try:
            text, _, _ = await stt.transcribe(pcm_to_wav(pcm), pcm)
        except SttError as e:
            log.warning("STT failed: %s", e)
            continue
        if text:
            parts.append(text)
    return " ".join(parts).strip()


async def run(args) -> None:
    from livekit import rtc
    url = os.getenv("LIVEKIT_URL", "")
    tok = tokens.mint("caller", args.room, identity=f"caller-ai-{uuid.uuid4().hex[:4]}", phone=args.phone, label=args.label)
    async with httpx.AsyncClient() as http:
        brain = Brain(http, args.lang)
        stt = SarvamSTT(Config.from_env(), http)
        opening, _ = await brain.next_line()                  # ready before anyone answers
        opening_pcm = [await speak_pcm(http, s, args.lang, args.voice) for s in sentences(opening)]
        room = rtc.Room()
        line, ear = None, None
        victim_track: asyncio.Future = asyncio.get_running_loop().create_future()

        def on_track(track, publication, participant):
            if track.kind == rtc.TrackKind.KIND_AUDIO and participant.identity.split("-")[0] == args.victim and not victim_track.done():
                victim_track.set_result(track)

        left = asyncio.Event()
        room.on("track_subscribed", on_track)
        room.on("participant_disconnected", lambda p: left.set() if p.identity.split("-")[0] == args.victim else None)

        def on_data(packet):                                  # she pressed hang-up in the app (her mic just mutes)
            who = packet.participant.identity if packet.participant else ""
            if packet.topic == HANGUP_TOPIC and who.split("-")[0] == args.victim:
                log.info("Kamala hung up")
                left.set()
        room.on("data_received", on_data)
        await room.connect(url, tok)
        log.info("AI scammer joined %s as %s (%s)", room.name, room.local_participant.identity, args.phone)
        try:
            line = Line(room)
            await line.start()
            try:
                track = await asyncio.wait_for(victim_track, 60)
            except asyncio.TimeoutError:
                log.warning("no victim audio within 60 s; hanging up")
                return
            ear = Ear(line)
            asyncio.create_task(ear.listen(track))
            await asyncio.sleep(1.5)                          # let the guardian subscribe before the first words
            say, pcm, hang_up = opening, opening_pcm, False
            started = time.monotonic()
            for turn in range(args.max_turns):
                print(f"\n  SCAMMER: {say}", flush=True)
                brain.turns.append(("scammer", say))
                while not ear.utterances.empty():            # said while we were thinking: stale, it would put
                    ear.utterances.get_nowait()              # every later reply one turn behind
                for part in pcm:                              # first sentence plays while the rest is voiced
                    if left.is_set():
                        break
                    await line.say(part if isinstance(part, bytes) else await part)
                if hang_up or left.is_set() or time.monotonic() - started > args.max_seconds:
                    break
                hearing = asyncio.create_task(hear_answer(ear, stt, wait=9.0))
                gone = asyncio.create_task(left.wait())
                await asyncio.wait({hearing, gone}, return_when=asyncio.FIRST_COMPLETED)
                gone.cancel()
                if left.is_set():
                    hearing.cancel()
                    break
                answer = hearing.result()
                if left.is_set():
                    break
                print(f"  KAMALA:  {answer or '(silence)'}", flush=True)
                brain.turns.append(("kamala", answer or "(says nothing for a few seconds)"))
                say, hang_up = await brain.next_line()
                parts = sentences(say)
                pcm = [await speak_pcm(http, parts[0], args.lang, args.voice)] + \
                      [asyncio.create_task(speak_pcm(http, s, args.lang, args.voice)) for s in parts[1:]]
            await asyncio.sleep(1.0)
        finally:
            await room.disconnect()                           # CLIENT_INITIATED: the bridge ends the call now
            log.info("AI scammer hung up after %d lines", sum(1 for w, _ in brain.turns if w == "scammer"))


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv(HERE / ".env")
    load_dotenv(Path.home() / "Projects/chaukanna-classifier/classifier_service/.env")   # GEMINI_API_KEY; never overrides
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--phone", default="+91 90000 31001")
    ap.add_argument("--label", default="")
    ap.add_argument("--lang", choices=["hi", "en"], default="hi")
    ap.add_argument("--voice", default="aditya", help="Sarvam bulbul:v3 speaker (aditya = the stage scammer)")
    ap.add_argument("--room", default=os.getenv("LIVEKIT_ROOM", "chaukanna"))
    ap.add_argument("--victim", default=os.getenv("VICTIM_IDENTITY", "victim"))
    ap.add_argument("--max-turns", type=int, default=14)
    ap.add_argument("--max-seconds", type=float, default=240)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for noisy in ("httpx", "livekit"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if not os.getenv("LIVEKIT_URL") or not os.getenv("SARVAM_API_KEY"):
        sys.exit("LIVEKIT_URL / LIVEKIT_API_* / SARVAM_API_KEY are not set (.env)")
    def hang_up(*_):                                  # the console's "End call": hang up like Ctrl-C, once
        signal.signal(signal.SIGTERM, signal.SIG_IGN)   # a second one would interrupt the hang-up itself
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, hang_up)
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        log.info("stopped; hung up")
    sys.stdout.flush()
    os._exit(0)          # skip the LiveKit FFI finalizers, which print a harmless traceback at interpreter exit


if __name__ == "__main__":
    sys.exit(main())
