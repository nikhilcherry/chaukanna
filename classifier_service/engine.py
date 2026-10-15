"""Per-call state + the classify pipeline.

    chunk -> [call lock] append, keyword scan, kick background LLM (max one in flight per call)
          -> optionally wait for the in-flight LLM while it can still land inside the budget
          -> [call lock] merge keywords + latest LLM verdict + previous verdict (pressure ratchets),
             caller-number risk, whisper-once -> Verdict

The response never waits for a slow LLM: Gemini's ~1.5 s verdict lands in the background and is
merged into the next chunk's answer. A failing backend only sets `degraded: true`.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field

import keywords
from backends.base import Backend, LLMContext
from callers import CallerRegistry, CallerRisk
from schemas import ClassifyRequest, LLMVerdict, Verdict, norm_lang

log = logging.getLogger("classifier.engine")

WINDOW = 15
# Whisper priority when several clips become due on the same chunk (higher first).
CLIP_RANK = {"warn_otp": 4, "warn_known_scammer": 3, "warn_digital_arrest": 2, "warn_secrecy": 1}


def _env_f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    budget_ms: float = field(default_factory=lambda: _env_f("CLASSIFY_BUDGET_MS", 400))  # total response budget
    llm_timeout_s: float = field(default_factory=lambda: _env_f("LLM_TIMEOUT_S", 4.0))  # hard cap per LLM run
    ttl_s: float = field(default_factory=lambda: _env_f("CALL_TTL_S", 900))  # forget a call after this much silence
    max_calls: int = field(default_factory=lambda: int(_env_f("MAX_CALLS", 500)))
    delivery_otp_policy: str = field(default_factory=lambda: os.getenv("DELIVERY_OTP_POLICY", "caution"))  # caution | warn
    llm_on_victim: bool = field(default_factory=lambda: os.getenv("LLM_ON_VICTIM_CHUNKS", "0") == "1")
    whisper_gap_chunks: int = field(default_factory=lambda: int(_env_f("WHISPER_GAP_CHUNKS", 2)))
    breaker_failures: int = 3  # consecutive LLM failures that open the circuit...
    breaker_open_s: float = 10.0  # ...for this long (no LLM calls, keyword-only, degraded)


@dataclass
class CallState:
    call_id: str
    caller_number: str = ""
    chunks: deque = field(default_factory=lambda: deque(maxlen=WINDOW))
    n_chunks: int = 0
    kw: keywords.KeywordState = field(default_factory=keywords.KeywordState)
    risk: CallerRisk | None = None
    risk_checked_for: str | None = None
    # background LLM
    llm: LLMVerdict | None = None
    llm_backend: str | None = None
    llm_at_chunk: int = 0  # how many chunks the current llm verdict had seen
    llm_task: asyncio.Task | None = None
    llm_future: asyncio.Future | None = None  # resolves when the current run finishes
    llm_started: float = 0.0
    llm_dirty: bool = False
    llm_error: str | None = None
    # output state
    last: Verdict | None = None
    whispered: list[str] = field(default_factory=list)
    last_whisper_chunk: int = -99
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_seen: float = field(default_factory=time.monotonic)
    closed: bool = False


class Engine:
    def __init__(self, backend: Backend | None, settings: Settings | None = None, callers: CallerRegistry | None = None) -> None:
        self.backend = backend
        self.s = settings or Settings()
        self.callers = callers or CallerRegistry()
        self.calls: dict[str, CallState] = {}
        self.llm_ewma_ms: float | None = None
        self.llm_latencies: deque = deque(maxlen=500)
        self.fail_streak = 0
        self.breaker_until = 0.0
        self._last_sweep = time.monotonic()

    # ------------------------------------------------------------------ lifecycle
    def get(self, call_id: str) -> CallState:
        st = self.calls.get(call_id)
        if st is None:
            st = self.calls[call_id] = CallState(call_id=call_id)
            if len(self.calls) > self.s.max_calls:
                oldest = min(self.calls.values(), key=lambda c: c.last_seen)
                self._drop(oldest.call_id)
        st.last_seen = time.monotonic()
        return st

    def _drop(self, call_id: str) -> bool:
        st = self.calls.pop(call_id, None)
        if st is None:
            return False
        st.closed = True
        if st.llm_task and not st.llm_task.done():
            st.llm_task.cancel()
        return True

    def reset(self, call_id: str) -> bool:
        return self._drop(call_id)

    def sweep(self) -> int:
        """Forget calls idle for longer than ttl_s. Returns how many were dropped."""
        now = time.monotonic()
        self._last_sweep = now
        stale = [cid for cid, st in self.calls.items() if now - st.last_seen > self.s.ttl_s]
        for cid in stale:
            self._drop(cid)
        if stale:
            log.info("expired %d idle call(s)", len(stale))
        return len(stale)

    async def aclose(self) -> None:
        for cid in list(self.calls):
            self._drop(cid)
        if self.backend:
            await self.backend.aclose()

    # ------------------------------------------------------------------ classify
    async def classify(self, req: ClassifyRequest) -> Verdict:
        t0 = time.perf_counter()
        if time.monotonic() - self._last_sweep > 30:
            self.sweep()
        st: CallState | None = None
        try:
            st = self.get(req.call_id)
            async with st.lock:
                st.n_chunks += 1
                idx = st.n_chunks
                text = (req.chunk_text or "").strip()
                lang = norm_lang(req.language)
                st.chunks.append((req.speaker, lang, text))
                if req.caller_number:
                    st.caller_number = req.caller_number
                if st.caller_number and st.risk_checked_for != st.caller_number:
                    st.risk = self.callers.check(st.caller_number)
                    st.risk_checked_for = st.caller_number
                keywords.scan_chunk(st.kw, req.speaker, text, lang)
                if self.backend and text and (req.speaker == "caller" or self.s.llm_on_victim):
                    self._kick_llm(st)
                fut = st.llm_future
            await self._maybe_wait(fut, st, t0)
            async with st.lock:
                v = self._merge(st, idx, lang)
        except Exception as e:  # never 5xx mid-call
            log.exception("classify failed for %s", req.call_id)
            v = self._emergency(st, req, e)
        v.latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        return v

    async def _maybe_wait(self, fut: asyncio.Future | None, st: CallState, t0: float) -> None:
        """Wait for the in-flight LLM run only if it is expected to land inside the budget
        (a ~30 ms local model does; a ~1.5 s Gemini call never does, so we don't wait for it)."""
        if fut is None or fut.done():
            return
        remaining = self.s.budget_ms / 1000 - (time.perf_counter() - t0) - 0.02
        if remaining <= 0:
            return
        if self.llm_ewma_ms is not None:
            expected_left = self.llm_ewma_ms / 1000 * 1.2 - (time.monotonic() - st.llm_started)
            if not 0 <= expected_left <= remaining:  # too slow, or already overdue: don't gamble the budget
                return
        await asyncio.wait({fut}, timeout=remaining)

    # ------------------------------------------------------------------ background LLM
    def _kick_llm(self, st: CallState) -> None:
        if st.llm_task and not st.llm_task.done():
            st.llm_dirty = True  # the running loop picks the new chunk up when it finishes
            return
        st.llm_dirty = False
        st.llm_future = asyncio.get_running_loop().create_future()
        st.llm_started = time.monotonic()  # set before the task runs: _maybe_wait reads it right away
        st.llm_task = asyncio.create_task(self._llm_loop(st), name=f"llm:{st.call_id}")

    def _snapshot(self, st: CallState) -> tuple[int, LLMContext]:
        earlier = None
        if st.llm and st.n_chunks > WINDOW:
            earlier = f"{st.llm.scam_type}, pressure {st.llm.pressure}: {st.llm.summary_for_family}"
        lang = keywords._dominant(st.kw.lang_votes.get("caller", {})) or "en"
        return st.n_chunks, LLMContext(st.call_id, st.caller_number, list(st.chunks), earlier, lang, sorted(st.kw.hits))

    async def _llm_loop(self, st: CallState) -> None:
        loop = asyncio.get_running_loop()
        try:
            while not st.closed:
                st.llm_dirty = False
                snap_idx, ctx = self._snapshot(st)
                if st.llm_future is None or st.llm_future.done():
                    st.llm_future = loop.create_future()
                fut = st.llm_future
                st.llm_started = time.monotonic()
                try:
                    lv = await self._run_backend(ctx)
                    if snap_idx >= st.llm_at_chunk:
                        st.llm, st.llm_at_chunk = lv, snap_idx
                        st.llm_backend = getattr(self.backend, "last_used", self.backend.name)
                    st.llm_error = None
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    st.llm_error = f"{type(e).__name__}: {str(e)[:160]}"
                    log.warning("llm failed for %s: %s", st.call_id, st.llm_error)
                finally:
                    if not fut.done():
                        fut.set_result(None)
                if not st.llm_dirty:
                    break
        finally:
            if st.llm_future and not st.llm_future.done():
                st.llm_future.set_result(None)

    async def _run_backend(self, ctx: LLMContext) -> LLMVerdict:
        if time.monotonic() < self.breaker_until:
            raise RuntimeError("circuit open: backend failing, keyword-only for now")
        t = time.perf_counter()
        try:
            lv = await asyncio.wait_for(self.backend.classify(ctx), timeout=self.s.llm_timeout_s)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.fail_streak += 1
            if self.fail_streak >= self.s.breaker_failures:
                self.breaker_until = time.monotonic() + self.s.breaker_open_s
                log.error("backend failed %d times in a row; keyword-only for %.0fs", self.fail_streak, self.s.breaker_open_s)
            raise
        ms = (time.perf_counter() - t) * 1000
        self.fail_streak = 0
        self.llm_latencies.append(ms)
        self.llm_ewma_ms = ms if self.llm_ewma_ms is None else 0.7 * self.llm_ewma_ms + 0.3 * ms
        return lv

    # ------------------------------------------------------------------ merge
    def _guard_llm(self, lv: LLMVerdict, kv: keywords.KeywordVerdict) -> LLMVerdict:
        """Delivery-OTP policy 'caution': when the only scam evidence in the whole call is a
        delivery rider asking for the OTP, an LLM verdict can't escalate past pressure 1."""
        if kv.delivery_otp and self.s.delivery_otp_policy == "caution" and lv.pressure > 1:
            return lv.model_copy(update={"pressure": 1, "scam_type": "none"})
        return lv

    def _merge(self, st: CallState, idx: int, req_lang: str) -> Verdict:
        kv = keywords.verdict(st.kw, self.s.delivery_otp_policy)
        lv = self._guard_llm(st.llm, kv) if st.llm else None
        prev = st.last
        risk = st.risk

        pressure = max(kv.pressure, lv.pressure if lv else 0, prev.pressure if prev else 0)
        if risk and risk.kind == "listed":
            pressure = max(pressure, 2)
        elif risk:
            pressure = max(pressure, 1)
        otp = kv.asks_otp_or_pin or bool(lv and lv.asks_otp_or_pin) or bool(prev and prev.asks_otp_or_pin)
        secrecy = kv.demands_secrecy or bool(lv and lv.demands_secrecy) or bool(prev and prev.demands_secrecy)

        # Scam type: fresh model opinion > what we already said (sticky) > keyword guess.
        stype = "none"
        for cand in (lv.scam_type if lv else None, prev.scam_type if prev else None, kv.scam_type):
            if cand and cand != "none":
                stype = cand
                break
        if stype == "none" and pressure >= 2:
            stype = (risk.scam_type if risk and risk.scam_type else None) or "other"
        if pressure == 0:
            stype = "none"

        if lv and lv.scam_type == stype:
            conf = max(lv.confidence, kv.confidence if kv.scam_type == stype else 0.0)
        elif kv.scam_type == stype:
            conf = kv.confidence
        elif prev and prev.scam_type == stype:
            conf = prev.confidence
        else:
            conf = 0.6
        if risk and risk.kind == "listed":
            conf = max(conf, 0.9)

        lang = keywords._dominant(st.kw.lang_votes.get("victim", {})) or (lv.language if lv else None) \
            or keywords._dominant(st.kw.lang_votes.get("caller", {})) or req_lang

        summary = lv.summary_for_family if lv and lv.summary_for_family else kv.summary
        if lv:
            extra = []
            if kv.asks_otp_or_pin and not lv.asks_otp_or_pin:
                extra.append("asked for an OTP/PIN")
            if kv.demands_secrecy and not lv.demands_secrecy:
                extra.append("demanded secrecy")
            if "victim_complying" in st.kw.hits and kv.pressure > lv.pressure:
                extra.append("the victim has started complying")
            if extra:
                summary = summary.rstrip(". ") + ". Since then the caller " + " and ".join(extra) + "."
        if risk and risk.kind == "listed":
            summary = "This number is on the Chaukanna scam list. " + summary

        if lv is None:
            source = "keywords"
        elif st.llm_at_chunk == idx and lv.pressure >= kv.pressure:
            source = (st.llm_backend or "llm").split("(")[0]
        else:
            source = "merged"

        v = Verdict(
            call_id=st.call_id, scam_type=stype, pressure=pressure, asks_otp_or_pin=otp, demands_secrecy=secrecy,
            confidence=round(min(max(conf, 0.0), 1.0), 2), language=lang, summary_for_family=summary,
            known_scammer=risk is not None, caller_risk=risk.kind if risk else "none",
            degraded=bool(self.backend) and (st.llm_error is not None or time.monotonic() < self.breaker_until),
            source=source, backend=st.llm_backend, signals=sorted(st.kw.hits),
            llm_chunks_behind=(idx - st.llm_at_chunk) if lv else None, chunk_index=idx,
        )
        clip, reason = self._pick_whisper(st, v, idx)
        v.recommended_whisper_clip, v.whisper_reason = clip, reason
        st.last = v
        return v

    # ------------------------------------------------------------------ whisper once
    def _due_clips(self, st: CallState, v: Verdict) -> dict[str, str]:
        hits = st.kw.hits
        due: dict[str, str] = {}
        if st.risk and st.risk.kind == "listed":
            due["warn_known_scammer"] = st.risk.reason
        if v.pressure >= 2:
            if v.asks_otp_or_pin:
                due["warn_otp"] = f"caller asked for an OTP/PIN: \"{hits['otp']}\"" if "otp" in hits else \
                    f"{v.backend or 'model'} detected a request for an OTP/PIN"
            if v.scam_type == "digital_arrest":
                key = next((k for k in ("digital_arrest", "authority", "legal_threat") if k in hits), None)
                due["warn_digital_arrest"] = f"caller {keywords.LABELS[key]}: \"{hits[key]}\"" if key else \
                    f"{v.backend or 'model'} recognised a digital-arrest script"
            if v.demands_secrecy:
                key = next((k for k in ("secrecy", "isolation") if k in hits), None)
                due["warn_secrecy"] = f"caller {keywords.LABELS[key]}: \"{hits[key]}\"" if key else \
                    f"{v.backend or 'model'} detected a demand for secrecy"
        return due

    def _pick_whisper(self, st: CallState, v: Verdict, idx: int) -> tuple[str, str]:
        """Each clip fires on exactly one chunk per call. At most one clip per chunk; a lower-
        priority clip waits whisper_gap_chunks after the previous whisper, a more serious one doesn't."""
        due = {c: r for c, r in self._due_clips(st, v).items() if c not in st.whispered}
        if not due:
            return "none", ""
        clip = max(due, key=CLIP_RANK.get)
        top = max((CLIP_RANK[c] for c in st.whispered), default=0)
        if st.whispered and CLIP_RANK[clip] <= top and idx - st.last_whisper_chunk < self.s.whisper_gap_chunks:
            return "none", ""
        st.whispered.append(clip)
        st.last_whisper_chunk = idx
        return clip, due[clip]

    def _emergency(self, st: CallState | None, req: ClassifyRequest, err: Exception) -> Verdict:
        """Last-resort answer when the pipeline itself throws: the last verdict, or a neutral one."""
        base = st.last if st and st.last else None
        if base:
            return base.model_copy(update={"recommended_whisper_clip": "none", "whisper_reason": "", "degraded": True})
        return Verdict(call_id=req.call_id, scam_type="none", pressure=0, asks_otp_or_pin=False, demands_secrecy=False,
                       confidence=0.0, language=norm_lang(req.language), summary_for_family="", degraded=True)
