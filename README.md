# Chaukanna incident responder

The n8n half of Chaukanna. When the audio bridge decides a call is a scam, this workflow runs the
whole response checklist on its own: alert the family on Telegram, log the evidence, add the
number to the shared scam list, and have an AI agent draft the 1930 / cybercrime.gov.in complaint
in English and the victim's language. The one irreversible step, submitting the complaint, waits
for the victim to tap Approve in the app.

![n8n canvas](docs/screenshots/n8n-canvas.png)

| File | What it is |
|---|---|
| `incident_responder/workflow.json` | The n8n workflow "Chaukanna · Scam-Call Incident Responder" (85 nodes). Import it in n8n. |
| `incident_responder/supabase_schema.sql` | Tables, integrity trigger, RLS and demo seeds. Idempotent. |
| `incident_responder/test_webhooks.sh` | Fires the workflow without the app or the bridge: known scammer, medium, high-risk, approval. |
| `supabase/` | Local Supabase project `chaukanna` (ports 554xx) with the schema as its migration. |
| `CONTRACTS.md` | Message formats between all five repos. §2 is this workflow's input and reply, §3 the approval. |

## Branches

`Webhook: chaukanna-verdict` → normalize → three Supabase lookups (scam list, trusted contacts,
open incident for this call) → **Severity Router**:

| Route | When | What happens |
|---|---|---|
| Known scammer | number on the shared list, pressure < 2 | block signal, `report_count` +1 |
| Critical | first event of a call with pressure ≥ 2 | Telegram alert now, evidence row, blocklist upsert, AI Agent drafts the complaint (Gemini 2.5 Flash, Flash-Lite fallback, template fallback), every `[mm:ss]` it cites is checked against the transcript, reply to the bridge, then **Wait for human approval** (24 h) |
| Escalation / call ended | same `call_id` again | update the same evidence row, tell the family only what is new |
| Medium | pressure 1 | one row in the n8n Data Table `chaukanna_telemetry` |

`Webhook: chaukanna-approve` approves by `incident_id` / `call_id` when the app has no resume URL.
The Telegram Trigger logs the family's "I'm calling them now" / "False alarm" taps. The workflow is
its own error workflow.

## Run it

```bash
# 1. Database (local; needs Docker and the Supabase CLI)
supabase start                       # applies supabase/migrations/*: the schema + demo seeds
supabase status -o env | grep SERVICE_ROLE_KEY

# 2. n8n credential "Chaukanna Supabase": Host http://172.21.0.1:55421 (the Docker gateway the n8n
#    container sees; use http://127.0.0.1:55421 if n8n runs on the host), Service Role Secret = that key.
# 3. n8n credential "Chaukanna Telegram Bot": a BotFather token. Then put the family's chat id on the
#    demo contact and re-enable the "Telegram Trigger: family taps a button" node:
psql postgresql://postgres:postgres@127.0.0.1:55422/postgres -c \
  "update trusted_contacts set telegram_chat_id = '<chat id>' where victim_id = 'demo-victim-1'"

# 4. Fire it
incident_responder/test_webhooks.sh            # known, medium, high, approve
incident_responder/test_webhooks.sh extras     # escalation, duplicate incident, call_ended
```

A cloud Supabase project works the same way: run `supabase_schema.sql` in its SQL editor and point
the credential at it.

Reset between rehearsals:

```sql
delete from incident_evidence;
delete from scam_numbers where phone_number = '+919876543210';
```

and on the classifier: `curl -X DELETE localhost:8010/scam_numbers/+919876543210`.

## State on 2026-10-16

- Active on `n8n.premortem.tech`; `test_webhooks.sh high` returns the AI complaint in English and Hindi
  with 5/5 citations verified and a public `approve_url`.
- `Chaukanna Supabase` and `Chaukanna Telegram Bot` credentials still need real values (steps 2 and 3).
  Until Supabase is connected, `evidence_saved`, `blocklisted` and `draft_saved` come back `false`, and
  n8n can't dedupe by `call_id`, so every escalation re-runs the full incident branch.
- The Telegram Trigger node is disabled: n8n can't activate a workflow whose Telegram trigger has no
  valid bot token.
