# Chaukanna audio bridge

Lean daemon on the raw `livekit` rtc SDK (no livekit-agents). Joins a LiveKit room as the hidden observer
`chaukanna-guardian`, turns each participant's audio into 4 s / 16 kHz / mono WAV chunks in memory, and runs

```
audio -> Sarvam STT -> POST /classify (mock fallback) -+-> victim-only data message (transcript, verdict, whisper flag)
                                                       +-> n8n events: telemetry / incident / escalation / call_ended
```

![replay of a scam call](docs/screenshots/replay-scam-call.png)
![redial from a reported number](docs/screenshots/redial-known-scammer.png)

## Run

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # LiveKit URL/key/secret, SARVAM_API_KEY, N8N_WEBHOOK_URL
.venv/bin/python bridge.py      # live mode; reconnects with backoff
```

`N8N_WEBHOOK_URL` must be set, or no n8n event is ever sent (the bridge logs a warning at start).
Message formats for every hop are in `CONTRACTS.md`.

- Identity convention: participant `victim` (override with `VICTIM_IDENTITY`) is the victim; every other non-guardian participant is the caller.
- Each call gets its own `call_id` (`<room>-<uuid8>`): it starts when a caller joins and ends when the caller or the victim leaves (a dropped connection gets `CALL_END_GRACE_SECONDS` to come back). The classifier is reset at call end.
- Data messages (topic `chaukanna.verdict`, victim only): `call_started`, `verdict` (with the bridge's whisper decision), `incident` (n8n's reply), `heartbeat` every 5 s, `call_ended`. A victim who joins mid-call gets a snapshot.
- Caller number comes from participant metadata `{"phone": "..."}` (the dialer sets it), falling back to the display name.
- Shared scam list: at startup the bridge loads the classifier's `GET /scam_numbers`, and when a call becomes an
  incident it POSTs the caller to `/scam_numbers` (`REPORT_SCAMMERS=1`). n8n writes the same number to Supabase,
  so a redial is flagged in `call_started` and whispers `warn_known_scammer` on its first chunk.
- Silent chunks (RMS < `SILENCE_RMS`) are not sent to STT. If STT falls behind, the oldest queued chunk is dropped so the bridge stays live.

## Replay (venue Wi-Fi fallback)

```bash
.venv/bin/python bridge.py --replay-file samples/synthetic_scam_call_hinglish.wav   # real-time, still publishes to LiveKit + n8n
.venv/bin/python bridge.py --replay-file call.wav --no-livekit           # verdict JSON to stdout only
.venv/bin/python bridge.py --replay-file call.wav --mock-stt --speed 8   # offline wiring test, 8x faster
```

Same STT -> classifier -> data channel -> n8n code path as live. If LiveKit is unreachable, replay degrades to stdout.
`samples/` holds SYNTHETIC Sarvam-TTS calls (stereo, caller left / victim right) with cached transcripts; record a rehearsal with `--record-dir` for a real one.

## Scammer dialer

```bash
.venv/bin/python token_server.py     # open http://localhost:8787
```

`scammer_dialer.html` is served from the token server, which mints a `caller-*` token with the typed phone number in metadata.
Set `VICTIM_TOKEN_KEY` to also serve `GET /victim-token?key=<key>` → `{"token","url"}`, so the app can be built with
`--dart-define=LIVEKIT_TOKEN_URL=https://<host>/victim-token?key=<key>` instead of a baked-in token. It is off by
default because a victim token can read the guardian's data messages. `python tokens.py victim --ttl 48h` still works.
Expose it with `hoist` for teammates on other laptops (mic access needs HTTPS). Without the server, paste a LiveKit URL + JWT under "Advanced".

## Tests

`python -m unittest discover -s tests` covers chunking, WAV encoding, resampling, the fast/slow paths with cooldown, and the classifier fallback.
The live LiveKit path (track subscribe -> AudioStream) has not been run against a real server here.
