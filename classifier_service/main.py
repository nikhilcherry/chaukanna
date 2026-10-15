import logging
import time

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

load_dotenv()

from backends import get_backend  # noqa: E402
from schemas import ClassifyRequest, Verdict  # noqa: E402
from store import CallStore  # noqa: E402

log = logging.getLogger("classifier")
app = FastAPI(title="Chaukanna Verdict Classifier")
store = CallStore()
backend = get_backend()


def finalize(v: Verdict, prev: Verdict | None) -> Verdict:
    """Calls only get scarier: ratchet pressure and sticky flags, and derive the
    whisper clip deterministically from the flags so the output is consistent."""
    if prev:
        v.pressure = max(v.pressure, prev.pressure)
        v.asks_otp_or_pin |= prev.asks_otp_or_pin
        v.demands_secrecy |= prev.demands_secrecy
    if v.pressure < 2:
        v.recommended_whisper_clip = "none"
    elif v.asks_otp_or_pin:
        v.recommended_whisper_clip = "warn_otp"
    elif v.scam_type == "digital_arrest":
        v.recommended_whisper_clip = "warn_digital_arrest"
    elif v.demands_secrecy:
        v.recommended_whisper_clip = "warn_secrecy"
    return v


@app.post("/classify", response_model=Verdict)
async def classify(req: ClassifyRequest) -> Verdict:
    st = store.append(req)
    prev = st.last_verdict
    t0 = time.perf_counter()
    try:
        v = await backend.classify(req.call_id, st)
    except Exception as e:
        log.exception("backend failed")
        raise HTTPException(502, f"classification backend failed: {type(e).__name__}: {e}")
    v = finalize(v, prev)
    store.set_verdict(req.call_id, v)
    log.info("call=%s backend=%s %.0fms pressure=%d", req.call_id, backend.name, (time.perf_counter() - t0) * 1000, v.pressure)
    return v


@app.post("/reset/{call_id}")
async def reset(call_id: str) -> dict:
    return {"call_id": call_id, "cleared": store.reset(call_id)}


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "backend": backend.name}
