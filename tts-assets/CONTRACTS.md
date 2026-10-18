# Chaukanna contracts

How the five Chaukanna repos talk to each other. **The same file is in every repo**
(`chaukanna_app`, `chaukanna-audio-bridge`, `chaukanna-classifier`,
`chaukanna-incident-responder`, `tts_asset_generator`). If you change it, change all five copies.
Fields marked *additive* are optional: a client must work without them and must ignore
fields it does not know.

```
 caller (dialer, caller-*) ─┐                                  ┌─► victim app (identity "victim")
                            ├─ LiveKit room "chaukanna" ───────┤     ▲  data topic chaukanna.verdict (§4)
 victim app (mic) ──────────┘         │                        │     │  whisper clips (§5)
                                      ▼                        │     │
                       audio bridge (hidden "chaukanna-guardian") ───┘
                         │  Sarvam STT per chunk
                         ├─► classifier  POST :8010/classify (§1)
                         └─► n8n  POST /webhook/chaukanna-verdict (§2) ──► Supabase, Telegram, Gemini
 victim app ── approve ──► n8n  approve_url or /webhook/chaukanna-approve (§3)
```

| Thing | Value |
|---|---|
| Classifier | `http://localhost:8010` (8000 on the dev laptop is an unrelated container) |
| n8n | `https://n8n.premortem.tech`, workflow "Chaukanna · Scam-Call Incident Responder" |
| Token server / scammer dialer | `http://localhost:8787` (`chaukanna-audio-bridge/token_server.py`) |
| Guardian console | `http://localhost:8787/console/`: replays every call from the bridge's `calls/*.jsonl` log, follows one live, and joins every call, number, incident and scam list in its Network view (§7) |
| Supabase (local dev) | `http://127.0.0.1:55421`, Studio `:55423` (`chaukanna-incident-responder/supabase/`) |
| LiveKit room | `chaukanna` |
| Demo victim | `victim_id` `demo-victim-1`, name `Kamala Devi`, language `hi` |
| Languages | `hi`, `kn`, `en` (anything else is treated as `en`) |

## §1 Classifier API (`chaukanna-classifier`)

`POST /classify`, one request per transcript chunk of either call leg:

```json
{"call_id": "chaukanna-1a2b3c4d", "caller_number": "+919876543210", "speaker": "caller",
 "chunk_text": "आप अभी digital arrest में हैं", "language": "hi"}
```

`speaker` is `caller` or `victim`. `language` may be `hi-IN`. The answer comes in single-digit
milliseconds: the keyword fast path decides now, and the model verdict (Jev, Gemini fallback)
is merged into the *next* chunk's answer.

```jsonc
{
  "call_id": "chaukanna-1a2b3c4d",
  "scam_type": "digital_arrest",   // digital_arrest | kyc_update | bank_impersonation | prize_lottery | pension_scam
                                   // | relative_emergency | utility_disconnection | insurance_bonus | upi_collect
                                   // | investment_tip | sextortion | other | none  (unknown values: treat as "other")
  "pressure": 3,                   // 0..3, never decreases within a call
  "asks_otp_or_pin": true,         // sticky for the call
  "demands_secrecy": true,         // sticky for the call
  "confidence": 0.95,
  "language": "hi",                // the victim's language, used for the whisper
  "recommended_whisper_clip": "warn_otp",   // §5 clip id or "none"; non-none only when first due
  "summary_for_family": "Caller claims to be CBI ...",
  // additive
  "known_scammer": false, "caller_risk": "none",   // listed | risky_country_code | none
  "whisper_reason": "...", "degraded": false, "source": "merged", "backend": "jev",
  "signals": ["authority", "otp"], "llm_chunks_behind": 1, "chunk_index": 6, "latency_ms": 3.1
}
```

- `POST /reset/{call_id}`: the bridge calls it when a call ends.
- `GET /scam_numbers` returns `{"numbers": [{"number", "scam_type", "note"}], "risky_country_codes": {...}}`.
  The bridge loads it at startup so `call_started.known_scammer` is right before anyone speaks.
- `POST /scam_numbers` `{"number", "scam_type", "note"}` adds a number. The bridge sends one for every
  call that becomes an incident (`REPORT_SCAMMERS=1`), so a redial is flagged on its first chunk.
- `DELETE /scam_numbers/{number}` removes one (use it to reset the demo).
- `GET|POST|DELETE /trusted_numbers` (`{"number", "name", "note"}`): the victim's family / saved contacts
  (demo: `+91 98450 12345`, "Ravi (son)", same as the Supabase `trusted_contacts` seed). A plain OTP
  request from one of them stays at pressure 1 with no whisper; a bank OTP, a threat, secrecy, a fee, an
  app/link or an excuse ("sent to you by mistake", "WhatsApp code") still escalates. Everyday codes
  (delivery, ride, LPG DAC, technician, pickup, gate) are calm from any number. A listed number is never trusted.
- `GET /health`.

The classifier never returns 5xx mid-call. If it is down, the bridge uses its own keyword verdict.

## §2 n8n verdict webhook (bridge → n8n)

`POST https://n8n.premortem.tech/webhook/chaukanna-verdict`

```jsonc
{
  "event": "incident",            // telemetry | incident | escalation | call_ended
  "call_id": "chaukanna-1a2b3c4d",
  "victim_id": "demo-victim-1",
  "caller_number": "+919876543210",
  "ts": 1792170000.0,
  "verdict": { /* the §1 response, after the bridge's ratchet */ },
  "transcript": [{"t": 51.3, "ts": 1792170051.3, "speaker": "caller", "text": "..."}],
  "transcript_text": "[00:51] caller: ...",
  "duration_seconds": 75.0,        // call_ended only
  "peak_pressure": 3               // call_ended only
}
```

When the bridge sends each event, per call, strictly in order:

| event | when |
|---|---|
| `telemetry` | first time pressure reaches 1 (only before an incident) |
| `incident` | first time pressure reaches `N8N_PRESSURE_THRESHOLD` (2). Once per call. |
| `escalation` | after the incident, when pressure rises or a new flag appears (queued ones coalesce) |
| `call_ended` | at hang-up, only if an incident fired |

Victim OTP-like digit runs are already masked (`******`) in `transcript`. n8n masks them again.

**Reply to `incident`** (the bridge waits up to `N8N_INCIDENT_TIMEOUT_SECONDS`, 45 s, then forwards it to the
victim as an `incident` data message, §4):

```jsonc
{
  "ok": true,
  "incident_id": "dac853a9-b632-4aaf-bf22-cfef21e685eb",
  "call_id": "chaukanna-1a2b3c4d",
  "known_scammer": false,
  "family_alerted": true,          // a Telegram alert actually went out
  "evidence_saved": true,          // incident_evidence row written
  "blocklisted": true,             // caller added to / bumped in scam_numbers
  "complaint_draft": {"en": "...", "local": "...", "language": "hi"},
  "family_alert": "• ...\n• ...\n• ...",
  "approve_url": "https://n8n.premortem.tech/webhook-waiting/365?signature=...",
  // additive
  "approve_fallback_url": "https://n8n.premortem.tech/webhook/chaukanna-approve",
  "draft_saved": true, "draft_source": "ai", "citations": {"cited": 5, "verified": 5, "unverified": []},
  "key_evidence": [{"timestamp": "00:51", "speaker": "caller", "category": "otp_demand", "quote": "..."}],
  "scam_type": "digital_arrest", "max_pressure": 3, "report_count": 1, "risk_level": "critical", "lookups_ok": true
}
```

Other events get a short `{"ok": true, ...}`. n8n dedupes by `call_id` through the
`incident_evidence` row: a second `incident` for the same call is treated as an escalation.

## §3 Approval (app → n8n)

The one irreversible step. The app POSTs to the incident's `approve_url` (the n8n Wait node's
resume URL). If that is missing, local (`localhost`), or fails, it POSTs the same body to
`/webhook/chaukanna-approve`, which finds the incident by `incident_id`, then `call_id`, then the
newest pending incident from `caller_number`.

```jsonc
{
  "action": "confirm_1930_report",
  "confirmed_by_human": true,       // anything else -> 400, nothing is filed
  "call_id": "chaukanna-1a2b3c4d",
  "victim_id": "demo-victim-1",
  "incident_id": "dac853a9-...",    // when the app has it
  "caller_number": "+919876543210",
  "scam_type": "digital_arrest", "peak_pressure": 3, "asks_otp_or_pin": true, "demands_secrecy": true,
  "duration_seconds": 75,
  "evidence": ["00:51 OTP demand", "..."],
  "complaint_text": "...",
  // additive
  "complaint_text_local": "...", "complaint_language": "hi", "known_scammer": false,
  "submitted_at": "2026-10-18T05:12:00Z"
}
```

Reply: `{"ok": true, "incident_id", "call_id", "complaint_status": "submitted", "recorded": true, ...}`.
The app trusts a resume URL only if the reply says `{"ok": true}`; otherwise it falls back to the webhook.
cybercrime.gov.in has no filing API, so "submitted" means approved by the victim and recorded with the
evidence; the family gets the incident id to quote on 1930.

## §4 LiveKit room and data messages (bridge → victim app)

Identities: `victim` (the app; one phone per token), `caller-*` (dialer; metadata `{"phone": "+91..."}`,
which becomes `caller_number`), `chaukanna-guardian` (the bridge, hidden). Tokens: `tokens.py victim`,
`token_server.py` `/token` (callers) and `/victim-token?key=...` (only when `VICTIM_TOKEN_KEY` is set).

Topic `chaukanna.verdict`, sent to the victim only. Unknown types and fields are ignored.

| type | fields |
|---|---|
| `call_started` | `call_id`, `caller_number`, `caller_label`, `known_scammer`, `ts` |
| `verdict` | `call_id`, `speaker`, `chunk_text`, `language`, `verdict` (§1), `pressure`, `whisper` (bool), `whisper_clip`, `ts`, plus the §1 fields flattened, `caller_number`, `latency_ms`; `snapshot: true` when replayed to a victim who joined mid-call |
| `incident` | the §2 incident reply plus `type`, `call_id`, `ts` |
| `heartbeat` | `call_id` (empty between calls), `in_call`, `ts`, every 5 s |
| `call_ended` | `call_id`, `ts`, `peak_pressure`, `high_risk`, `duration_seconds` |

A call starts when a `caller-*` joins and ends when the caller or the victim leaves (a dropped
connection gets `CALL_END_GRACE_SECONDS`, 6 s). The app resets all state per call and ignores late
messages for an ended call.

## §5 Whisper clips (`tts_asset_generator` → app)

| clip id | priority | said when |
|---|---|---|
| `warn_otp` | 4 | the caller asks for an OTP / PIN |
| `warn_known_scammer` | 3 | the number is on the scam list |
| `warn_digital_arrest` | 2 | police / CBI / arrest threat |
| `warn_secrecy` | 1 | "don't tell anyone" |

Files: `assets/audio/{clip}_short_{lang}.wav` (< 3 s, played first) and `{clip}_{lang}.wav` (full), for
`hi`, `kn` and `en`, 24 kHz mono, plus `manifest.json` and `lib/generated/whisper_clips.dart`. All of
them are written by `python3 generate.py --out ~/Projects/chaukanna_app/assets/audio`; never edit them by hand.

Who decides: the classifier recommends a clip once per call; the bridge sets `whisper: true` the first
time a clip is recommended, and again only if pressure rose and `WHISPER_COOLDOWN_SECONDS` (20 s) passed;
the app plays only on `whisper: true`, at most once per clip per 20 s, and mutes the victim's mic while
it plays so the caller can't hear it.

## §6 OTP SMS context (victim app → bridge → classifier)

Not every OTP request is a scam: the SMS itself says what the code unlocks. The app reads incoming
SMS (`RECEIVE_SMS`, Android), and for an OTP SMS sends **only** its purpose, the sender and the amount.
**The code never leaves the phone** (the bridge also drops any `service` with 4+ digits).

App → guardian: LiveKit data, topic `chaukanna.otp_sms`, destination `chaukanna-guardian`, from the
victim identity only (callers can't publish data):

```json
{"purpose": "payment", "service": "HDFC Bank", "amount": 49999.0}
```

`purpose`: `payment | upi | card | bank_login | sim | messaging_account` (risk **high**: money or the
account itself), `government_id | other_login` (**medium**), `everyday` (**low**: delivery, ride, LPG DAC,
pickup, technician, gate). The classifier owns the purpose → risk mapping.

Bridge → classifier: `POST /otp_context` `{"call_id", "purpose", "service", "amount", "seconds_before_call"}`,
returns a re-merged §1 verdict that the bridge publishes like a chunk verdict with `speaker: "sms"` and
`chunk_text: "OTP SMS: payment, ₹49,999, from HDFC Bank"`. An SMS seen while no call is on is held and
applied when the next call starts (`seconds_before_call` = its age; dropped after 15 min).

Effect: a **high** OTP during the call (or ≤2 min before it) raises pressure to 2 with `warn_otp` before
anyone asks, makes any OTP request critical (even from a trusted contact) and leads the family summary
("A ₹49,999 payment OTP from HDFC Bank arrived on the phone during this call…"). A **low** one keeps an
OTP request calm (pressure 1) from any number, as long as nothing else in the call looks like a scam.

## §7 Console network feed (n8n → token server)

`GET https://n8n.premortem.tech/webhook/chaukanna-network` with header `X-Chaukanna-Key: <CONSOLE_FEED_KEY>`
(workflow "Chaukanna · Console network feed", `incident_responder/console_feed_workflow.json`; a wrong or missing
key gets 403). Read-only. The bridge's token server calls it (cached 30 s) for the console's network view and
status strip, so the console sees Supabase without holding a Supabase key:

```jsonc
{"ok": true, "at": "2026-10-17T15:10:27.911Z",
 "incidents": [{"id", "call_id", "victim_id", "caller_number", "scam_type", "max_pressure", "complaint_status",
                "family_response", "known_scammer", "asks_otp_or_pin", "demands_secrecy", "last_event", "has_draft",
                "created_at", "updated_at", "submitted_at"}],          // newest first, at most 300
 "scam_numbers": [{"phone_number", "scam_type", "report_count", "risk_level", "first_seen", "last_seen", "last_call_id"}],
 "trusted_contacts": [{"victim_id", "victim_name", "contact_name", "phone_number", "preferred_language",
                       "telegram_ready"}]}                              // true only for a real numeric chat id
```

Transcripts, complaint text and Telegram chat ids never leave n8n. The bridge also rewrites
`calls/_bridge.json` on every heartbeat (`room`, `in_call`, `victim_present`); its age tells the console whether
the bridge is in the LiveKit room.

## Shared data

- **Scam numbers** live in two places that must agree: Supabase `scam_numbers` (n8n reads and writes it)
  and the classifier's `data/scam_numbers.json` + runtime list. The seeds match (`+919988776655`,
  `+923001234567`, `+85512345678`). At runtime the bridge copies each incident's caller to the classifier;
  n8n writes it to Supabase. The dialer's default `+919876543210` is seeded in neither, so the first call
  from it is "new" and the redial is "known".
- **Supabase tables** (`incident_responder/supabase_schema.sql`): `scam_numbers`, `trusted_contacts`
  (who gets the Telegram alert; `telegram_chat_id` must be a real chat id), `incident_evidence`
  (one row per scam call, `call_id` unique). RLS is on with no policies: only n8n's service-role key can use them.
