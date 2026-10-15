import threading
import time
from collections import deque
from dataclasses import dataclass, field

from schemas import ClassifyRequest, Verdict

WINDOW = 15


@dataclass
class Chunk:
    speaker: str
    text: str
    timestamp: float
    language: str


@dataclass
class CallState:
    caller_number: str = ""
    chunks: deque = field(default_factory=lambda: deque(maxlen=WINDOW))
    last_verdict: Verdict | None = None


class CallStore:
    def __init__(self) -> None:
        self._calls: dict[str, CallState] = {}
        self._lock = threading.Lock()

    def append(self, req: ClassifyRequest) -> CallState:
        with self._lock:
            st = self._calls.setdefault(req.call_id, CallState())
            if req.caller_number:
                st.caller_number = req.caller_number
            st.chunks.append(Chunk(req.speaker, req.chunk_text, time.time(), req.language))
            return st

    def get(self, call_id: str) -> CallState | None:
        return self._calls.get(call_id)

    def set_verdict(self, call_id: str, v: Verdict) -> None:
        with self._lock:
            if call_id in self._calls:
                self._calls[call_id].last_verdict = v

    def reset(self, call_id: str) -> bool:
        with self._lock:
            return self._calls.pop(call_id, None) is not None


def render_transcript(st: CallState) -> str:
    return "\n".join(f"[{c.speaker.upper()} | {c.language}] {c.text}" for c in st.chunks)
