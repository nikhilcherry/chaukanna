"""Chaukanna verdict classifier.  `python main.py`  ->  http://0.0.0.0:8010  (PORT to override)."""
import asyncio
import contextlib
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

load_dotenv(Path(__file__).resolve().parent / ".env")

from backends import LLMContext, get_backend  # noqa: E402
from engine import Engine  # noqa: E402
from schemas import ClassifyRequest, Verdict  # noqa: E402

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("classifier")
DEFAULT_PORT = 8010


def _make_engine() -> Engine:
    try:
        backend = get_backend()
    except Exception as e:  # missing key / bad config: still serve the keyword fast path
        log.error("backend init failed (%s: %s); running keyword-only", type(e).__name__, e)
        backend = None
    return Engine(backend)


engine = _make_engine()


async def _warmup() -> None:
    """Open the backend's HTTPS connection before the first real chunk (first Gemini call was ~2.9 s cold)."""
    if not engine.backend or os.getenv("WARMUP", "1") != "1":
        return
    try:
        ctx = LLMContext("warmup", "", [("caller", "en", "Hello, is this a good time to talk?")])
        await engine._run_backend(ctx)  # also seeds the latency estimate used by the wait policy
        log.info("backend %s warmed up in %.0f ms", engine.backend.name, engine.llm_ewma_ms or -1)
    except Exception as e:
        log.warning("warmup failed (%s: %s)", type(e).__name__, str(e)[:120])


async def _sweeper() -> None:
    while True:
        await asyncio.sleep(60)
        engine.sweep()


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    tasks = [asyncio.create_task(_warmup()), asyncio.create_task(_sweeper())]
    yield
    for t in tasks:
        t.cancel()
    await engine.aclose()


app = FastAPI(title="Chaukanna Verdict Classifier", lifespan=lifespan)


@app.post("/classify", response_model=Verdict)
async def classify(req: ClassifyRequest) -> Verdict:
    return await engine.classify(req)


@app.post("/reset/{call_id}")
async def reset(call_id: str) -> dict:
    return {"call_id": call_id, "cleared": engine.reset(call_id)}


@app.get("/health")
async def health() -> dict:
    lat = sorted(engine.llm_latencies)
    pct = (lambda q: round(lat[min(len(lat) - 1, int(q * len(lat)))], 1)) if lat else (lambda q: None)
    return {
        "ok": True,
        "backend": engine.backend.name if engine.backend else "none",
        "active_calls": len(engine.calls),
        "llm_p50_ms": pct(0.5), "llm_p95_ms": pct(0.95),
        "circuit_open": engine.fail_streak >= engine.s.breaker_failures,
        "delivery_otp_policy": engine.s.delivery_otp_policy,
        "known_numbers": len(engine.callers.numbers),
    }


class ScamNumber(BaseModel):
    number: str
    scam_type: str | None = None
    note: str = ""


@app.get("/scam_numbers")
async def list_numbers() -> dict:
    return {"numbers": list(engine.callers.numbers.values()), "risky_country_codes": engine.callers.codes}


@app.post("/scam_numbers")
async def add_number(n: ScamNumber) -> dict:
    try:
        return {"added": engine.callers.add(n.number, n.scam_type, n.note)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/scam_numbers/{number}")
async def remove_number(number: str) -> dict:
    return {"removed": engine.callers.remove(number)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", DEFAULT_PORT)))
