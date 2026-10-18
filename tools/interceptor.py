"""Agent interception mode: when a call turns into a scam, a Chaukanna agent joins and talks to the victim.

    python tools/interceptor.py                       # standby: joins at each agent's auto_pressure, or when the console asks
    python tools/interceptor.py --agent bank-fraud-desk
    python tools/interceptor.py --no-auto             # only when the console's "Intercept now" asks
    python tools/interceptor.py --now                 # intercept the call that is on right now, then exit

Agents are JSON profiles in agents/ (name, voice, language, instructions, auto_pressure). Add your own there,
or from the stage page ("+ agent"). The agent joins the LiveKit room as `agent-<id>` and publishes its voice to
the victim only (track subscription permissions): the caller cannot hear it. The victim's app sees the agent,
stops the caller hearing her and mutes the caller for her (chaukanna_app LiveKitTransport.setIntercepted), so the
agent has taken over her side of the call. It knows the scam so far from the bridge's call log, talks in her
language (Sarvam STT -> Gemini -> Sarvam TTS, as tools/ai_scammer.py), and writes its lines to the same call log
for the console. The bridge ignores agents (role "agent"), so nothing it says is judged as the caller.
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

import httpx

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))
import calllog  # noqa: E402
import tokens  # noqa: E402
from ai_scammer import Ear, Line, gemini_json, hear_answer, sentences, speak_pcm  # noqa: E402
from config import DEFAULT_CALL_LOG_DIR, Config  # noqa: E402
from stt import SarvamSTT  # noqa: E402

log = logging.getLogger("chaukanna.interceptor")
AGENTS = HERE / "agents"
CALLS = Path(os.getenv("CALL_LOG_DIR") or DEFAULT_CALL_LOG_DIR)
REQUEST = "_intercept.json"            # the console asks (token_server POST /console/api/intercept)
STATUS = "_agent.json"                 # what the stage page shows: standby / on a call

FALLBACK = {
    "hi": ["कमला जी, मैं चौकन्ना से बोल रही हूँ। यह कॉल एक धोखा है।",
           "किसी को भी OTP, PIN या पैसे मत दीजिए। अभी फ़ोन काट दीजिए।",
           "आपके बेटे रवि को खबर कर दी गई है। आप सुरक्षित हैं, घबराइए मत।"],
    "en": ["Kamala ji, this is Chaukanna. This call is a scam.",
           "Do not share any OTP, PIN or money with him. Please hang up now.",
           "Your son Ravi has been told. You are safe, do not worry."],
    "kn": ["ಕಮಲಾ ಅವರೇ, ನಾನು ಚೌಕನ್ನದಿಂದ ಮಾತನಾಡುತ್ತಿದ್ದೇನೆ. ಈ ಕರೆ ಮೋಸ.",
           "ಯಾರಿಗೂ OTP, PIN ಅಥವಾ ಹಣ ಕೊಡಬೇಡಿ. ಈಗಲೇ ಫೋನ್ ಇಡಿ.",
           "ನಿಮ್ಮ ಮಗ ರವಿಗೆ ತಿಳಿಸಲಾಗಿದೆ. ನೀವು ಸುರಕ್ಷಿತ."],
}
LANG_NAME = {"hi": "spoken Hindi in Devanagari (with the English words people use, like OTP)",
             "en": "simple Indian English", "kn": "simple spoken Kannada in Kannada script"}


def load_agents() -> dict[str, dict]:
    out = {}
    for f in sorted(AGENTS.glob("*.json")):
        try:
            a = json.loads(f.read_text())
            out[a["id"]] = a
        except (ValueError, KeyError, OSError):
            log.warning("skipping unreadable agent profile %s", f.name)
    return out


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def call_context(call_id: str) -> dict:
    """What the guardian knows about the call so far, from the bridge's call log."""
    recs = calllog.read_call(CALLS, call_id) or []
    start = next((r for r in recs if r.get("type") == "call_started"), {})
    vs = [r for r in recs if r.get("type") == "verdict"]
    last = vs[-1] if vs else {}
    return {
        "caller": start.get("caller_number", ""), "peak": max([int(v.get("pressure") or 0) for v in vs] or [0]),
        "scam_type": last.get("scam_type", "none"), "otp": any(v.get("asks_otp_or_pin") for v in vs),
        "secrecy": any(v.get("demands_secrecy") for v in vs),
        "language": next((v.get("language") for v in reversed(vs) if v.get("speaker") == "victim" and v.get("language")),
                         last.get("language", "hi")),
        "lines": [(v.get("speaker"), v.get("chunk_text", "")) for v in vs][-14:],
        "ended": any(r.get("type") == "call_ended" for r in recs),
    }


def system_prompt(agent: dict, ctx: dict, lang: str) -> str:
    lines = "\n".join(f"{'CALLER' if s == 'caller' else 'KAMALA'}: {t}" for s, t in ctx["lines"]) or "(nothing yet)"
    return f"""You are {agent['name']}. {agent['instructions']}

You have just joined a phone call to protect Kamala Devi, a 68-year-old woman, from a caller that Chaukanna's scam
guardian has flagged. Only Kamala can hear you; the caller cannot hear you, and he can no longer hear her.
What the guardian knows: scam type {ctx['scam_type'].replace('_', ' ')}; risk {ctx['peak']} of 3; caller's number
{ctx['caller'] or 'unknown'}; he asked for an OTP: {'yes' if ctx['otp'] else 'no'}; he demanded secrecy:
{'yes' if ctx['secrecy'] else 'no'}.
The call so far:
{lines}

Speak {LANG_NAME.get(lang, LANG_NAME['hi'])}. Be warm, calm and brief: one or two short sentences, at most 25 words.
Answer what she says. When she says she has hung up or is safe, close kindly and end.
Reply only with JSON: {{"say": "<words to speak>", "end": <true when the conversation is done>}}"""


async def intercept(http: httpx.AsyncClient, agent: dict, call_id: str, args) -> None:
    from livekit import rtc
    sink = calllog.CallLog(CALLS)
    ctx = call_context(call_id)
    lang = ctx["language"] if agent.get("language", "auto") == "auto" else agent["language"]
    lang = lang if lang in FALLBACK else "hi"
    turns: list[tuple[str, str]] = []
    fallback = list(FALLBACK[lang])

    async def next_line() -> tuple[str, bool]:
        prompt = "\n".join(f"{'YOU' if w == 'agent' else 'KAMALA'}: {t}" for w, t in turns) or \
            "(You have just joined the call. Speak first: tell her who you are and that this call is a scam.)"
        try:
            j = await gemini_json(http, system_prompt(agent, call_context(call_id), lang), prompt, temperature=0.5)
            say = str(j.get("say", "")).strip()
            if say:
                return say, bool(j.get("end"))
        except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as e:
            log.warning("gemini failed (%s); using a scripted line", type(e).__name__)
        return (fallback.pop(0), not fallback) if fallback else ("", True)

    say, end = await next_line()
    first = [await speak_pcm(http, s, lang, agent["voice"]) for s in sentences(say)]
    tok = tokens.mint("agent", args.room, identity=f"agent-{agent['id']}"[:40], label=agent["name"])
    room = rtc.Room()
    left = asyncio.Event()
    victim_track: asyncio.Future = asyncio.get_running_loop().create_future()

    def on_track(track, publication, participant):
        if track.kind == rtc.TrackKind.KIND_AUDIO and participant.identity.split("-")[0] == args.victim and not victim_track.done():
            victim_track.set_result(track)

    room.on("track_subscribed", on_track)
    room.on("participant_disconnected", lambda p: left.set() if p.identity.split("-")[0] == args.victim else None)
    await room.connect(os.environ["LIVEKIT_URL"], tok)

    async def watch_call_end():                     # the victim stays in the room between calls: leave with the call
        while not left.is_set():
            b = read_json(CALLS / "_bridge.json")
            if not b.get("in_call") or b.get("call_id") != call_id:
                left.set()
            await asyncio.sleep(0.5)
    asyncio.create_task(watch_call_end())
    write_status("on_call", agent=agent["name"], call_id=call_id)
    sink.write({"type": "agent", "event": "joined", "call_id": call_id, "agent": agent["name"], "lang": lang, "ts": time.time()})
    log.info("[%s] %s joined (%s)", call_id, agent["name"], lang)
    try:
        line = Line(room)
        await line.start()
        # only the victim may hear the agent: the caller and everyone else get nothing
        room.local_participant.set_track_subscription_permissions(
            allow_all_participants=False,
            participant_permissions=[rtc.ParticipantTrackPermission(participant_identity=args.victim, allow_all=True)])
        try:
            track = await asyncio.wait_for(victim_track, 15)
        except asyncio.TimeoutError:
            log.warning("victim audio not found; speaking anyway")
            track = None
        ear = Ear(line)
        if track is not None:
            asyncio.create_task(ear.listen(track))
        await asyncio.sleep(0.8)
        pcm: list = first
        for _ in range(args.max_turns):
            print(f"\n  AGENT:  {say}", flush=True)
            turns.append(("agent", say))
            sink.write({"type": "agent", "event": "said", "call_id": call_id, "agent": agent["name"], "text": say, "ts": time.time()})
            while not ear.utterances.empty():
                ear.utterances.get_nowait()
            for part in pcm:
                if left.is_set():
                    break
                await line.say(part if isinstance(part, bytes) else await part)
            if end or left.is_set():
                break
            answer = await hear_answer(ear, SarvamSTT(Config.from_env(), http), wait=10.0)
            if left.is_set():
                break
            print(f"  KAMALA: {answer or '(silence)'}", flush=True)
            turns.append(("kamala", answer or "(says nothing)"))
            say, end = await next_line()
            if not say:
                break
            parts = sentences(say)
            pcm = [await speak_pcm(http, parts[0], lang, agent["voice"])] + \
                  [asyncio.create_task(speak_pcm(http, s, lang, agent["voice"])) for s in parts[1:]]
        await asyncio.sleep(0.5)
    finally:
        sink.write({"type": "agent", "event": "left", "call_id": call_id, "agent": agent["name"], "ts": time.time()})
        await room.disconnect()
        log.info("[%s] %s left", call_id, agent["name"])


def write_status(state: str, **kw) -> None:
    try:
        CALLS.mkdir(parents=True, exist_ok=True)
        tmp = CALLS / (STATUS + ".tmp")
        tmp.write_text(json.dumps({"state": state, "ts": time.time(), **kw}))
        tmp.replace(CALLS / STATUS)
    except OSError:
        pass


async def standby(args) -> None:
    agents = load_agents()
    if args.agent not in agents:
        sys.exit(f"no agent {args.agent!r} in {AGENTS} (have: {', '.join(agents)})")
    done: set[str] = set()              # calls already intercepted
    last_req = read_json(CALLS / REQUEST).get("ts", 0)
    async with httpx.AsyncClient() as http:
        while True:
            agents = load_agents()                                    # profiles added from the console show up at once
            default = agents.get(args.agent) or next(iter(agents.values()))
            auto = None if args.no_auto else int(default.get("auto_pressure") or 3)
            write_status("standby", agent=default["name"], agent_id=default["id"], auto_pressure=auto)
            bridge = read_json(CALLS / "_bridge.json")
            call_id = bridge.get("call_id") if bridge.get("in_call") else ""
            req = read_json(CALLS / REQUEST)
            chosen = None
            if req.get("ts", 0) > last_req:
                last_req = req["ts"]
                if call_id and req.get("call_id") == call_id and call_id not in done:
                    chosen = agents.get(req.get("agent")) or default
            if not chosen and call_id and call_id not in done and (args.now or auto is not None):
                ctx = call_context(call_id)
                if args.now or (not ctx["ended"] and ctx["peak"] >= auto):
                    chosen = default
            if chosen:
                done.add(call_id)
                try:
                    await intercept(http, chosen, call_id, args)
                except Exception:
                    log.exception("interception failed")
                if args.now:
                    return
            elif args.now and not call_id:
                log.info("no call is on right now; waiting for one")
            await asyncio.sleep(0.5)


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv(HERE / ".env")
    load_dotenv(Path.home() / "Projects/chaukanna-classifier/classifier_service/.env")   # GEMINI_API_KEY; never overrides
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--agent", default="chaukanna-safety", help="default agent profile id (agents/<id>.json)")
    ap.add_argument("--no-auto", action="store_true", help="never join on its own; only when the console asks")
    ap.add_argument("--now", action="store_true", help="intercept the call that is on now (or the next one), then exit")
    ap.add_argument("--room", default=os.getenv("LIVEKIT_ROOM", "chaukanna"))
    ap.add_argument("--victim", default=os.getenv("VICTIM_IDENTITY", "victim"))
    ap.add_argument("--max-turns", type=int, default=8)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for noisy in ("httpx", "livekit"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        asyncio.run(standby(args))
    except KeyboardInterrupt:
        pass
    sys.stdout.flush()
    os._exit(0)          # skip the LiveKit FFI finalizers (harmless traceback at exit)


if __name__ == "__main__":
    sys.exit(main())
