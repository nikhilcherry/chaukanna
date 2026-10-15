import re

from backends.base import Backend
from schemas import Verdict
from store import CallState, render_transcript

# Offline keyword heuristic so the service and test_simulator run without any API key.
_AUTH = re.compile(r"\b(cbi|police|customs|fedex|narcotics|ed officer|trai|cyber ?crime)\b", re.I)
_THREAT = re.compile(r"(arrest|warrant|case|drugs|money laundering|gair ?kanooni|jail|giraftar|blocked?|frozen)", re.I)
_OTP = re.compile(r"\b(otp|pin|cvv|password)\b", re.I)
_SECRET = re.compile(r"(kisi ko mat|don'?t tell|do not tell|mat batana|confidential|hang up mat|do not disconnect|stay on (the )?(call|line))", re.I)
_TRANSFER = re.compile(r"(transfer|safe account|rbi account|verification amount|anydesk|teamviewer)", re.I)


class MockBackend(Backend):
    name = "mock"

    async def classify(self, call_id: str, st: CallState) -> Verdict:
        caller = " ".join(c.text for c in st.chunks if c.speaker == "caller")
        auth, threat = bool(_AUTH.search(caller)), bool(_THREAT.search(caller))
        otp, secret, xfer = bool(_OTP.search(caller)), bool(_SECRET.search(caller)), bool(_TRANSFER.search(caller))
        score = 0
        if auth:
            score = 1
        if auth and threat:
            score = 2
        if otp or secret or xfer:
            score = 3 if (auth or threat) else 2
        stype = "digital_arrest" if auth and score else "none"
        return Verdict(
            call_id=call_id, scam_type=stype, pressure=score, asks_otp_or_pin=otp, demands_secrecy=secret,
            confidence=0.5 + 0.15 * score if score else 0.9, language=st.chunks[-1].language[:2] if st.chunks[-1].language[:2] in ("hi", "kn", "en") else "en",
            recommended_whisper_clip="none", summary_for_family="(mock heuristic)" if score else "Ordinary call.",
        )
