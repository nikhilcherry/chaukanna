# Chaukanna verdict classifier

Stateful FastAPI microservice: send 4-second transcript chunks, get a strict JSON scam verdict.

```bash
cd classifier_service
pip install -r requirements.txt
cp .env.example .env            # set GEMINI_API_KEY
uvicorn main:app --port 8000
python test_simulator.py        # replays a scam call and an innocent delivery call
```

- `POST /classify` `{call_id, caller_number, speaker, chunk_text, language}` -> verdict (see `schemas.py`)
- `POST /reset/{call_id}` clears a call. Rolling window = last 15 chunks per call.
- `CLASSIFIER_BACKEND=gemini | sarvam | local_laya | mock`. `local_laya` calls an OpenAI-compatible endpoint (`LAYA_URL`) with a 1.5 s timeout, then falls back to Gemini. `mock` is an offline keyword heuristic for wiring tests.
- Within a call, pressure and the OTP/secrecy flags never decrease, and `recommended_whisper_clip` is derived from the flags.
