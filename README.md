# Chaukanna verdict classifier

Stateful FastAPI microservice for the Chaukanna scam-call guardian. The audio bridge sends each
~4-second transcript chunk of a live call, and the service answers with a typed scam verdict in
**single-digit milliseconds**, even though the LLM behind it takes ~1.5 s.

```bash
cd classifier_service
pip install -r requirements.txt
cp .env.example .env              # set GEMINI_API_KEY (or CLASSIFIER_BACKEND=none for keyword-only)
python main.py                    # http://0.0.0.0:8010   (or: uvicorn main:app --port 8010)
python test_simulator.py --concurrent      # scam call, innocent call, both call legs at once
python -m pytest -q tests                  # 50+ tests, offline, ~5 s
```

Port **8010** is the default everywhere. Port 8000 on the dev laptop belongs to an unrelated
container that answers 404, which used to make the bridge silently fall back to its mock.

## How it answers in milliseconds

```
chunk ─► [per-call lock] append to rolling window (15 chunks), keyword scan (<1 ms), start LLM in background
      ─► wait for the LLM only if it can land inside the budget (a ~30 ms local model yes, Gemini no)
      ─► [per-call lock] merge keyword verdict + latest LLM verdict + previous verdict ─► Verdict
```

1. **Keyword fast path** (`keywords.py`) runs on every chunk: English, Hindi (Devanagari and
   Hinglish), Kannada (script and Kanglish). It detects OTP/PIN/CVV asks, police/CBI/customs/RBI
   claims, arrest/case/warrant threats, "digital arrest", secrecy ("kisi ko mat batana",
   "ಯಾರಿಗೂ ಹೇಳಬೇಡಿ"), isolation ("call disconnect mat karna"), AnyDesk/screen-share, KYC/Aadhaar,
   fee or "safe account" payments, prizes, relative-in-trouble, and a victim who starts complying
   (reading digits, "bhej diya"). It knows the protective forms: a bank saying "never share your OTP" or
   "OTP kisi ko mat bataiye" is not an OTP ask, and "pin code" is not a PIN. Signals are sticky for the
   call and also match across chunk boundaries.
2. **LLM in the background**, at most **one run in flight per call**. Chunks that arrive during a run
   are coalesced into one follow-up run on the latest transcript. Only caller chunks start a run by
   default, which halves LLM calls; victim chunks are still keyword-scanned and reach the LLM as context.
   The LLM's verdict is merged into the *next* chunk's answer (`llm_chunks_behind: 1`). There is
   no push channel: the next chunk carries the upgraded verdict.
3. **Merge.** `pressure = max(keywords, LLM, previous)`, so it never decreases within a call. OTP and
   secrecy flags are sticky. `scam_type` takes the LLM's fresh opinion, then what was already said,
   then the keyword guess.
4. **Never 5xx mid-call.** If the backend errors or times out, the answer is the keyword verdict merged
   with the last verdict, plus `degraded: true`. Three failures in a row open a 10 s circuit
   breaker (no LLM calls during it). Even an exception inside the pipeline returns the last verdict.
5. **Per-call asyncio lock.** Both legs (caller and victim) of one call can hit `/classify` at the
   same instant. The read-merge-write of the previous verdict is atomic, so a slow high-pressure answer
   can't be overwritten by a fast low one. Calls expire after `CALL_TTL_S` (15 min) without chunks.
   At most `MAX_CALLS` are kept, and the least recently used is evicted first.
6. **Whisper once.** `recommended_whisper_clip` is non-`none` only on the chunk where that clip is
   first due for the call. `whisper_reason` quotes what triggered it. Priority: `warn_otp` >
   `warn_known_scammer` > `warn_digital_arrest` > `warn_secrecy`, and at most one clip per chunk. An
   equal or lower-priority clip waits `WHISPER_GAP_CHUNKS` (2) after the previous whisper; a more
   serious one doesn't wait.
7. **Caller number.** A number on `data/scam_numbers.json` (or added at runtime with
   `POST /scam_numbers`) sets `known_scammer: true` and pressure ≥ 2, and whispers
   `warn_known_scammer` on chunk 1. A scam-compound / scam-wave country code
   (`data/risky_country_codes.json`: +92, +855, +856, +95, +84, ...) also sets `known_scammer: true`,
   with `caller_risk: "risky_country_code"`. It only raises pressure to 1 and doesn't whisper, because
   the known-scammer clip says the number "has already been reported".

### Measured latency (gemini-2.5-flash, laptop, 2026-10-15)

| path | p50 | p95 |
|---|---|---|
| keyword scan + verdict, in process (3 long mixed-script chunks) | ~0.2 ms | < 1 ms |
| `POST /classify` over HTTP, simulator + concurrent legs (n=18) | **4 ms** | **7 ms** |
| background Gemini run (not waited for) | 1.5 s | 1.8 s |
| old design: `/classify` blocking on Gemini | 1.5–1.8 s | 2.9 s (cold) |

## API

`POST /classify` `{call_id, caller_number, speaker: "caller"|"victim", chunk_text, language}`
(`language` may be `hi-IN`; anything other than hi/kn/en maps to en).

Response: the original nine fields, unchanged, plus optional additive fields:

```jsonc
{
  "call_id": "room-1a2b3c4d",
  "scam_type": "digital_arrest",          // digital_arrest|kyc_update|bank_impersonation|prize_lottery|other|none
  "pressure": 3,                          // 0..3, never decreases within a call
  "asks_otp_or_pin": true,
  "demands_secrecy": true,
  "confidence": 0.95,
  "language": "hi",                       // the victim's language (the whisper is played in it)
  "recommended_whisper_clip": "warn_otp", // warn_otp|warn_digital_arrest|warn_secrecy|warn_known_scammer|none; once per call
  "summary_for_family": "Caller claims to be CBI ... Since then the caller asked for an OTP/PIN.",
  // additive:
  "known_scammer": false, "caller_risk": "none",          // listed | risky_country_code | none
  "whisper_reason": "caller asked for an OTP/PIN: \"ke liye apna otp aur bank pin\"",
  "degraded": false,                       // true = backend failing, answer is keywords + last verdict
  "source": "merged",                      // keywords | merged | <backend> (a model verdict covering this chunk decided it)
  "backend": "gemini",                     // backend behind the latest model verdict, e.g. "gemini(fallback)"
  "signals": ["authority", "digital_arrest", "otp", "secrecy", ...],
  "llm_chunks_behind": 1, "chunk_index": 6, "latency_ms": 3.1
}
```

- `POST /reset/{call_id}` forgets a call and cancels its LLM run.
- `GET /health` reports the backend, active calls, background LLM p50/p95, circuit state and the delivery-OTP policy.
- `GET|POST /scam_numbers`, `DELETE /scam_numbers/{number}` manage the known-scam list. Runtime
  additions persist to `data/scam_numbers.local.json`, which is gitignored.

## Backends

`CLASSIFIER_BACKEND=gemini | sarvam | local_laya | mock | none`. Every backend returns the same
`LLMVerdict`; whisper, known-scammer and ratchet logic live in the service.

- `gemini`: gemini-2.5-flash with `response_schema` and thinking off.
- `local_laya`: an OpenAI-compatible local endpoint with a 1.5 s timeout, falling back to Gemini through the generic `FallbackBackend`.
- `mock`: the keyword rules after an artificial delay, for offline wiring tests.
- `none`: keyword fast path only.

## Delivery-OTP policy

A delivery rider asking for the parcel OTP is the one OTP request that is usually legitimate.
gemini-2.5-flash called it `bank_impersonation` at pressure 2 and flash-lite called it `none` at pressure 1.
Pressure 2 fires the n8n incident: the family is paged and a 1930 complaint is drafted.

- `DELIVERY_OTP_POLICY=caution` (default): this case scores pressure 1, `asks_otp_or_pin: true`,
  no whisper, and the summary says "share it only in person". The LLM verdict is capped as well. Any
  other cue escalates normally: a fee, a link, a bank/UPI mention, customs/police, secrecy.
- `DELIVERY_OTP_POLICY=warn`: any OTP request is treated as a scam signal and whispers `warn_otp`.

## Files

`main.py` (API) · `engine.py` (state, lock, background LLM, merge, whisper, TTL) · `keywords.py`
(fast path) · `callers.py` + `data/` (known numbers, country codes) · `prompt.py` · `backends/` ·
`tests/` · `test_simulator.py`.
