"""chunk -> STT -> classifier -> victim data message + n8n events. Same code for live and replay.

Per call (CONTRACTS.md §2/§4):
  - every call gets its own call_id and is reset on the classifier when it ends
  - the bridge decides when to whisper: a clip fires the first time it is recommended in a call,
    and again only if pressure rose since and its cooldown has passed
  - n8n events: telemetry (first p>=1), incident (first p>=threshold, once, reply forwarded to the
    victim), escalation (pressure rose / new flag after the incident), call_ended (if an incident fired).
    Events for a call are sent strictly in order, and queued escalations are coalesced.
"""
from __future__ import annotations

import asyncio
import bisect
import json
import logging
import os
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import httpx

from audio import pcm_to_wav, rms
from config import CLIP_SEVERITY, SAMPLE_RATE, Config
from stt import MockSTT, SarvamError, SarvamSTT

log = logging.getLogger("chaukanna.bridge")

INCIDENT_FIELDS = ("incident_id", "complaint_draft", "family_alert", "approve_url")
Publish = Callable[[dict], Awaitable[bool]]   # True if the message went out

# --------------------------------------------------------------------------- caller numbers
_DEFAULT_SCAM_PREFIXES = "+92,+855,+95"


def normalize_number(raw: str) -> str:
    """'+91 98765-43210 - CBI Officer' -> '+919876543210'. Returns raw.strip() if no number is found."""
    m = re.search(r"\+?\d[\d\s().-]{5,}\d", raw or "")
    if not m:
        return (raw or "").strip()
    s = m.group(0)
    digits = re.sub(r"\D", "", s)
    if s.startswith("+"):
        return "+" + digits
    if len(digits) == 10:
        return "+91" + digits
    return digits


def locally_known_scammer(number: str) -> bool:
    """Cheap check before any verdict exists: scam-compound country codes or KNOWN_SCAM_NUMBERS."""
    if not number:
        return False
    prefixes = [p.strip() for p in os.getenv("KNOWN_SCAM_PREFIXES", _DEFAULT_SCAM_PREFIXES).split(",") if p.strip()]
    known = {normalize_number(n) for n in os.getenv("KNOWN_SCAM_NUMBERS", "").split(",") if n.strip()}
    return number in known or any(number.startswith(p) for p in prefixes)


# --------------------------------------------------------------------------- mock classifier
_SCAM_WORDS = {
    "digital_arrest": ["cbi", "digital arrest", "arrest", "police", "narcotics", "money laundering", "warrant",
                       "पुलिस", "गिरफ्तार", "सीबीआई"],
    "kyc_update": ["kyc", "aadhaar", "aadhar", "pan card", "blocked", "anydesk", "आधार"],
    "bank_impersonation": ["bank", "card", "cvv", "upi", "transaction"],
    "prize_lottery": ["lottery", "prize", "winner", "lucky"],
}


def mock_verdict(call_id: str, text: str, language: str, known_scammer: bool = False) -> dict:
    """Offline keyword heuristic, used when the classifier server is unreachable (or --classifier mock)."""
    t = text.lower()
    scam, hits = "none", 0
    for kind, words in _SCAM_WORDS.items():
        h = sum(w in t for w in words)
        if h > hits:
            scam, hits = kind, h
    otp = any(w in t for w in ("otp", "o.t.p", " pin", "cvv", "password", "ओटीपी", "******"))
    secrecy = any(w in t for w in ("don't tell", "do not tell", "tell no one", "secret", "confidential",
                                   "kisi ko mat", "किसी को न", "किसी को मत"))
    pressure = min(3, hits + int(otp) + int(secrecy) + 2 * int(known_scammer))
    if pressure < 2:
        clip = "none"
    elif otp:
        clip = "warn_otp"
    elif known_scammer:
        clip = "warn_known_scammer"
    elif scam == "digital_arrest":
        clip = "warn_digital_arrest"
    elif secrecy:
        clip = "warn_secrecy"
    else:
        clip = "none"
    return {
        "call_id": call_id, "scam_type": scam, "pressure": pressure, "asks_otp_or_pin": otp,
        "demands_secrecy": secrecy, "confidence": 0.4, "language": language if language in ("hi", "kn") else "en",
        "recommended_whisper_clip": clip, "known_scammer": known_scammer,
        "summary_for_family": "(bridge keyword verdict: classifier unreachable)", "degraded": True,
    }


def normalize_verdict(v: dict) -> dict:
    """Coerce a classifier reply into the Verdict shape; raises ValueError if it is not one."""
    if not isinstance(v, dict) or "pressure" not in v:
        raise ValueError("not a verdict")
    out = dict(v)
    out["pressure"] = max(0, min(3, int(v.get("pressure") or 0)))
    out["scam_type"] = v.get("scam_type") or "none"
    out["asks_otp_or_pin"] = bool(v.get("asks_otp_or_pin"))
    out["demands_secrecy"] = bool(v.get("demands_secrecy"))
    out["recommended_whisper_clip"] = v.get("recommended_whisper_clip") or "none"
    out.setdefault("confidence", 0.0)
    out.setdefault("language", "en")
    out.setdefault("summary_for_family", "")
    return out


def verdict_flags(v: dict) -> frozenset:
    return frozenset(k for k, on in (("otp", v.get("asks_otp_or_pin")), ("secrecy", v.get("demands_secrecy")),
                                     ("known_scammer", v.get("known_scammer"))) if on)


# --------------------------------------------------------------------------- per-call state
@dataclass
class CallState:
    call_id: str
    caller_number: str = ""
    caller_label: str = ""
    victim_id: str = ""
    known_scammer: bool = False
    started: float = field(default_factory=time.time)
    started_mono: float = field(default_factory=time.monotonic)
    transcript: list[dict] = field(default_factory=list)      # sorted by t
    last_verdict: dict | None = None
    last_message: dict | None = None                          # last verdict message (late-joiner snapshot)
    peak_pressure: int = 0
    whispered: dict[str, tuple[float, int]] = field(default_factory=dict)   # clip -> (monotonic, pressure)
    telemetry_sent: bool = False
    incident_sent: bool = False
    n8n_pressure: int = 0
    n8n_flags: frozenset = frozenset()
    incident_reply: dict | None = None
    delivered_whispers: set = field(default_factory=set)     # clips the victim actually received
    victim_seen: bool = False
    ending: bool = False
    ended: bool = False
    events: deque = field(default_factory=deque)
    sender: asyncio.Task | None = None

    def rel(self, mono: float) -> float:
        return max(0.0, mono - self.started_mono)


def fmt_t(t: float) -> str:
    return f"{int(t) // 60:02d}:{int(t) % 60:02d}"


# --------------------------------------------------------------------------- pipeline
class Pipeline:
    def __init__(self, cfg: Config, http: httpx.AsyncClient, publish: Publish, stt=None,
                 classifier: str = "http") -> None:
        self.cfg, self.http, self.publish = cfg, http, publish
        self.stt = stt or (MockSTT() if cfg.mock_stt else SarvamSTT(cfg, http))
        self.classifier = classifier                         # "http" | "mock"
        self._bg: set[asyncio.Task] = set()

    def _spawn(self, coro) -> asyncio.Task:
        t = asyncio.create_task(coro)
        self._bg.add(t)
        t.add_done_callback(self._bg.discard)
        return t

    # ---- call lifecycle -----------------------------------------------------------------
    def new_call(self, call_id: str, caller_number: str = "", victim_id: str = "",
                 caller_label: str = "") -> CallState:
        num = normalize_number(caller_number)
        st = CallState(call_id=call_id, caller_number=num, caller_label=caller_label or caller_number,
                       victim_id=victim_id or self.cfg.victim_id, known_scammer=locally_known_scammer(num))
        log.info("[%s] call started (caller %s%s)", call_id, num or "?",
                 ", KNOWN SCAMMER prefix" if st.known_scammer else "")
        return st

    def call_started_msg(self, st: CallState) -> dict:
        return {"type": "call_started", "call_id": st.call_id, "caller_number": st.caller_number,
                "caller_label": st.caller_label, "known_scammer": st.known_scammer, "ts": st.started}

    async def end_call(self, st: CallState) -> None:
        if st.ended:
            return
        st.ended = True
        dur = time.time() - st.started
        log.info("[%s] call ended after %.0fs, peak pressure %d, %d transcript lines",
                 st.call_id, dur, st.peak_pressure, len(st.transcript))
        await self.publish({"type": "call_ended", "call_id": st.call_id, "ts": time.time(),
                            "peak_pressure": st.peak_pressure, "high_risk": st.peak_pressure >= 2,
                            "duration_seconds": round(dur, 1)})
        if st.incident_sent:
            self.queue_event(st, "call_ended")
        self._spawn(self._reset_classifier(st.call_id))

    async def _reset_classifier(self, call_id: str) -> None:
        if self.classifier != "http":
            return
        try:
            await self.http.post(f"{self.cfg.reset_url_base}/{call_id}", timeout=3)
        except httpx.HTTPError as e:
            log.debug("classifier reset failed for %s: %s", call_id, e)

    # ---- one chunk ----------------------------------------------------------------------
    async def process_chunk(self, st: CallState, speaker: str, pcm: bytes,
                            t_start: float | None = None, audio_end: float | None = None) -> dict | None:
        """t_start: seconds since call start where this audio begins; audio_end: monotonic time the
        last sample of the chunk arrived (latency reference)."""
        if st.ended:
            return None
        audio_end = audio_end if audio_end is not None else time.monotonic()
        if t_start is None:
            t_start = max(0.0, st.rel(audio_end) - len(pcm) / 2 / SAMPLE_RATE)
        if rms(pcm) < self.cfg.silence_rms:
            log.debug("%s/%s: silent chunk skipped", st.call_id, speaker)
            return None
        wav = pcm_to_wav(pcm)
        try:
            text, lang = await self.stt.transcribe(wav, pcm)
        except SarvamError as e:
            log.warning("STT failed: %s", e)
            return None
        if not text or st.ended:
            return None
        entry = {"t": round(t_start, 2), "ts": round(st.started + t_start, 3), "speaker": speaker, "text": text}
        bisect.insort(st.transcript, entry, key=lambda e: e["t"])
        del st.transcript[:-300]
        verdict = self.merge(st, await self.classify(st, speaker, text, lang))
        clip = self.decide_whisper(st, verdict)
        msg = self.verdict_msg(st, speaker, text, lang, verdict, clip)
        msg["latency_ms"] = int((time.monotonic() - audio_end) * 1000)
        if await self.publish(msg) and clip != "none":
            st.delivered_whispers.add(clip)
        st.last_message = msg
        log.info("[%s] %s: %r -> %s p=%d%s", st.call_id, speaker, text[:70], verdict["scam_type"],
                 verdict["pressure"], f" WHISPER {clip}" if clip != "none" else "")
        ev = self.n8n_event_for(st, verdict)
        if ev:
            self.queue_event(st, ev)
        return msg

    def verdict_msg(self, st: CallState, speaker: str, text: str, lang: str, verdict: dict, clip: str) -> dict:
        return {
            "type": "verdict", "call_id": st.call_id, "speaker": speaker, "chunk_text": text,
            "language": lang, "verdict": verdict, "pressure": verdict["pressure"],
            "whisper": clip != "none", "whisper_clip": clip, "ts": time.time(),
            # additive: flat Verdict fields so a client that parses a bare Verdict still works
            "scam_type": verdict["scam_type"], "asks_otp_or_pin": verdict["asks_otp_or_pin"],
            "demands_secrecy": verdict["demands_secrecy"], "known_scammer": bool(verdict.get("known_scammer")),
            "confidence": verdict.get("confidence", 0.0), "recommended_whisper_clip": clip,
            "summary_for_family": verdict.get("summary_for_family", ""), "caller_number": st.caller_number,
        }

    async def classify(self, st: CallState, speaker: str, text: str, lang: str) -> dict:
        if self.classifier == "mock":
            return mock_verdict(st.call_id, self._recent_text(st), lang, st.known_scammer)
        body = {"call_id": st.call_id, "caller_number": st.caller_number, "speaker": speaker,
                "chunk_text": text, "language": lang}
        try:
            r = await self.http.post(self.cfg.classifier_url, json=body, timeout=6)
            r.raise_for_status()
            return normalize_verdict(r.json())
        except (httpx.HTTPError, ValueError, TypeError) as e:
            log.warning("classifier unavailable at %s (%s), using bridge keyword verdict",
                        self.cfg.classifier_url, e.__class__.__name__)
            return mock_verdict(st.call_id, self._recent_text(st), lang, st.known_scammer)

    @staticmethod
    def _recent_text(st: CallState) -> str:
        return " ".join(t["text"] for t in st.transcript[-6:])

    @staticmethod
    def merge(st: CallState, v: dict) -> dict:
        """Calls only get scarier (contract): ratchet pressure and sticky flags across both legs,
        whatever order the classifier replies arrive in."""
        v = dict(v)
        prev = st.last_verdict
        v["pressure"] = max(int(v["pressure"]), st.peak_pressure)
        v["known_scammer"] = bool(v.get("known_scammer")) or st.known_scammer
        if prev:
            for k in ("asks_otp_or_pin", "demands_secrecy", "known_scammer"):
                v[k] = bool(v.get(k)) or bool(prev.get(k))
            if v.get("scam_type", "none") == "none" and prev.get("scam_type", "none") != "none":
                v["scam_type"] = prev["scam_type"]
        v["call_id"] = st.call_id
        st.peak_pressure = v["pressure"]
        st.known_scammer = v["known_scammer"]
        st.last_verdict = v
        return v

    def decide_whisper(self, st: CallState, verdict: dict) -> str:
        """Whisper a clip the first time it is recommended in this call; repeat it only when pressure
        rose since it last played and its cooldown has passed."""
        clip = verdict.get("recommended_whisper_clip") or "none"
        if clip == "none":
            return "none"
        now, p = time.monotonic(), verdict["pressure"]
        prev = st.whispered.get(clip)
        if prev is not None and not (p > prev[1] and now - prev[0] >= self.cfg.whisper_cooldown):
            return "none"
        st.whispered[clip] = (now, p)
        return clip

    @staticmethod
    def strongest_whisper(st: CallState, exclude: set | frozenset = frozenset()) -> str:
        """Most serious clip whispered in this call that the victim has not received
        (replayed to a victim who joins late)."""
        clips = [c for c in st.whispered if c not in exclude]
        return max(clips, key=lambda c: CLIP_SEVERITY.get(c, 1)) if clips else "none"

    # ---- n8n ----------------------------------------------------------------------------
    def n8n_event_for(self, st: CallState, v: dict) -> str | None:
        p, flags = v["pressure"], verdict_flags(v)
        if not st.incident_sent:
            if p >= self.cfg.n8n_pressure:
                st.incident_sent, st.n8n_pressure, st.n8n_flags = True, p, flags
                return "incident"
            if p >= 1 and not st.telemetry_sent:
                st.telemetry_sent = True
                return "telemetry"
            return None
        if p > st.n8n_pressure or flags - st.n8n_flags:
            st.n8n_pressure, st.n8n_flags = p, st.n8n_flags | flags
            return "escalation"
        return None

    def queue_event(self, st: CallState, event: str) -> None:
        if not self.cfg.n8n_url:
            return
        st.events.append(event)
        if st.sender is None or st.sender.done():
            st.sender = self._spawn(self._send_events(st))

    async def _send_events(self, st: CallState) -> None:
        while st.events:
            ev = st.events.popleft()
            if ev == "escalation" and "escalation" in st.events:   # a newer one carries the latest verdict
                continue
            try:
                await self._post_event(st, ev)
            except Exception:
                log.exception("n8n %s failed", ev)

    def n8n_body(self, st: CallState, event: str) -> dict:
        lines = sorted(st.transcript, key=lambda e: e["t"])
        body = {
            "event": event, "call_id": st.call_id, "victim_id": st.victim_id, "caller_number": st.caller_number,
            "ts": time.time(), "verdict": st.last_verdict or {},
            "transcript": [dict(e) for e in lines],
            "transcript_text": "\n".join(f'[{fmt_t(e["t"])}] {e["speaker"]}: {e["text"]}' for e in lines),
        }
        if event == "call_ended":
            body["duration_seconds"] = round(time.time() - st.started, 1)
            body["peak_pressure"] = st.peak_pressure
        return body

    async def _post_event(self, st: CallState, event: str) -> None:
        body = self.n8n_body(st, event)
        wait = self.cfg.n8n_incident_timeout if event == "incident" else 10.0
        t0 = time.monotonic()
        for attempt in (1, 2, 3):
            try:
                r = await self.http.post(self.cfg.n8n_url, json=body, timeout=httpx.Timeout(wait, connect=5.0))
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:      # never reached n8n: safe to retry
                log.warning("n8n %s attempt %d: %s", event, attempt, e.__class__.__name__)
                await asyncio.sleep(attempt)
                continue
            except httpx.HTTPError as e:                                 # sent, but no reply: don't resend
                log.warning("n8n %s for %s: no reply within %.0fs (%s)", event, st.call_id, wait, e.__class__.__name__)
                return
            if r.status_code in (429, 502, 503, 504) and attempt < 3:
                log.warning("n8n %s attempt %d: HTTP %d", event, attempt, r.status_code)
                await asyncio.sleep(attempt)
                continue
            if r.is_error:
                log.warning("n8n %s for %s: HTTP %d %s", event, st.call_id, r.status_code, r.text[:200])
                return
            log.info("[%s] n8n %s delivered (pressure %d, %.0f ms)", st.call_id, event,
                     body["verdict"].get("pressure", 0), (time.monotonic() - t0) * 1000)
            if event == "incident":
                await self._forward_incident(st, r)
            return
        log.error("n8n %s for %s gave up after 3 attempts", event, st.call_id)

    async def _forward_incident(self, st: CallState, r: httpx.Response) -> None:
        try:
            reply = r.json()
        except (ValueError, json.JSONDecodeError):
            log.info("[%s] n8n incident reply was not JSON; nothing to forward", st.call_id)
            return
        if not isinstance(reply, dict) or not any(k in reply for k in INCIDENT_FIELDS):
            log.info("[%s] n8n incident reply carries no incident fields; nothing to forward", st.call_id)
            return
        st.incident_reply = {**reply, "type": "incident", "call_id": st.call_id, "ts": time.time()}
        await self.publish(st.incident_reply)

    async def drain(self, timeout: float = 60.0) -> None:
        """Wait for background work (n8n sends, resets) to finish."""
        if self._bg:
            await asyncio.wait(set(self._bg), timeout=timeout)
