#!/usr/bin/env bash
# Chaukanna incident responder: fire the n8n workflow without the app or the audio bridge.
#
#   ./test_webhooks.sh                 # all 4 scenarios in order (production webhooks)
#   ./test_webhooks.sh known           # 1. Known scammer           -> Branch 1 (block + report_count)
#   ./test_webhooks.sh medium          # 2. Medium pressure (1)     -> Branch 3 (silent telemetry)
#   ./test_webhooks.sh high            # 3. High-risk digital arrest -> Branch 2 (alert, evidence, blocklist, AI 1930 draft)
#   ./test_webhooks.sh approve         # 4. Human approval of the last high-risk incident -> submitted + receipt
#   ./test_webhooks.sh extras          #    escalation + duplicate incident + call_ended on the last high-risk call
#   ./test_webhooks.sh --test high     # use /webhook-test/ (click "Execute workflow" in the editor first)
#
# Env: BASE_URL (default https://n8n.premortem.tech), VICTIM_ID (default demo-victim-1),
#      STATE_FILE (where the last high-risk reply is kept, default /tmp/chaukanna_last_incident.json),
#      DRY_RUN=1 (print the payloads, send nothing)
# Needs: curl, jq.
set -euo pipefail

BASE_URL="${BASE_URL:-https://n8n.premortem.tech}"
BASE_URL="${BASE_URL%/}"
VICTIM_ID="${VICTIM_ID:-demo-victim-1}"
STATE_FILE="${STATE_FILE:-${TMPDIR:-/tmp}/chaukanna_last_incident.json}"
HOOK="webhook"
SCENARIOS=()

for arg in "$@"; do
  case "$arg" in
    --test) HOOK="webhook-test" ;;
    --prod|--production) HOOK="webhook" ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    known|medium|high|approve|extras|all) SCENARIOS+=("$arg") ;;
    *) echo "unknown argument: $arg (try --help)" >&2; exit 2 ;;
  esac
done
[ ${#SCENARIOS[@]} -eq 0 ] && SCENARIOS=(all)
command -v jq >/dev/null || { echo "jq is required (sudo apt install jq)" >&2; exit 2; }

VERDICT_URL="$BASE_URL/$HOOK/chaukanna-verdict"
APPROVE_URL_FALLBACK="$BASE_URL/$HOOK/chaukanna-approve"

c_bold=$'\e[1m'; c_dim=$'\e[2m'; c_red=$'\e[31m'; c_grn=$'\e[32m'; c_off=$'\e[0m'
[ -t 1 ] || { c_bold=; c_dim=; c_red=; c_grn=; c_off=; }

new_call_id() { echo "room-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"; }
now() { date +%s; }

# post <title> <url> <json> -> prints the reply, returns it in $REPLY_BODY
post() {
  local title="$1" url="$2" body="$3" out code
  echo
  echo "${c_bold}▶ $title${c_off}"
  echo "${c_dim}POST $url${c_off}"
  if [ -n "${DRY_RUN:-}" ]; then jq . <<<"$body"; REPLY_BODY='{}'; return 0; fi
  out="$(mktemp)"
  code="$(curl -sS -o "$out" -w '%{http_code}' --max-time 90 -H 'Content-Type: application/json' -X POST "$url" --data-binary "$body" || true)"
  [ -n "$code" ] || code=000
  REPLY_BODY="$(cat "$out")"; rm -f "$out"
  if [[ "$code" =~ ^2 ]]; then echo "${c_grn}HTTP $code${c_off}"; else echo "${c_red}HTTP $code${c_off}"; fi
  if jq -e . >/dev/null 2>&1 <<<"$REPLY_BODY"; then jq . <<<"$REPLY_BODY"; else echo "$REPLY_BODY"; fi
  if [ "$code" = "404" ] && [[ "$REPLY_BODY" == *"not registered"* ]]; then
    echo "${c_red}The webhook is not registered: activate the workflow (or use --test after clicking 'Execute workflow').${c_off}"
  fi
}

# A transcript line: line <t seconds> <speaker> <text>
TRANSCRIPT=""
START_TS=0
line() {
  local t="$1" sp="$2" text="$3"
  TRANSCRIPT="$(jq -c --argjson t "$t" --argjson ts "$((START_TS + ${t%.*}))" --arg sp "$sp" --arg tx "$text" \
    '. + [{t: $t, ts: $ts, speaker: $sp, text: $tx}]' <<<"${TRANSCRIPT:-[]}")"
}
transcript_text() {
  jq -r 'map("[" + ((.t|floor/60|floor|tostring|if length<2 then "0"+. else . end)) + ":" +
                   ((.t|floor%60|tostring|if length<2 then "0"+. else . end)) + "] " + .speaker + ": " + .text) | join("\n")' <<<"$TRANSCRIPT"
}

# payload <event> <call_id> <caller_number> <verdict-json>
payload() {
  jq -n --arg event "$1" --arg call_id "$2" --arg victim "$VICTIM_ID" --arg caller "$3" \
        --argjson ts "$(now)" --argjson verdict "$4" --argjson transcript "$TRANSCRIPT" --arg text "$(transcript_text)" \
    '{event: $event, call_id: $call_id, victim_id: $victim, caller_number: $caller, ts: $ts,
      verdict: ($verdict + {call_id: $call_id}), transcript: $transcript, transcript_text: $text}'
}

# 1 ── Known scammer: +91 99887 76655 is seeded in scam_numbers (report_count 7) ────────────
scenario_known() {
  local id; id="$(new_call_id)"; START_TS=$(( $(now) - 9 )); TRANSCRIPT="[]"
  line 0.0 caller "Namaste madam, main State Bank KYC department se bol raha hoon. Aapka KYC aaj expire ho raha hai."
  line 5.6 victim "Achha? Kya karna hoga?"
  post "1. Known scammer → Branch 1: block signal + report_count +1" "$VERDICT_URL" "$(payload telemetry "$id" "+91 99887 76655" '{
    "scam_type":"kyc_update","pressure":1,"asks_otp_or_pin":false,"demands_secrecy":false,"confidence":0.71,
    "language":"hi","recommended_whisper_clip":"warn_known_scammer","known_scammer":true,
    "summary_for_family":"Caller claims to be from the bank KYC department."}')"
}

# 2 ── Medium pressure (1): a new number, sales-y but no OTP / threat yet ───────────────────
scenario_medium() {
  local id; id="$(new_call_id)"; START_TS=$(( $(now) - 14 )); TRANSCRIPT="[]"
  line 0.0 caller "Hello sir, aapke credit card par 4,500 reward points aaj raat expire ho rahe hain."
  line 7.2 victim "Mujhe koi card ka call nahi chahiye."
  line 10.9 caller "Sir bas do minute, main aapko redeem karne ka process bata deta hoon."
  post "2. Medium pressure → Branch 3: silent telemetry only" "$VERDICT_URL" "$(payload telemetry "$id" "+91 70123 45678" '{
    "scam_type":"bank_impersonation","pressure":1,"asks_otp_or_pin":false,"demands_secrecy":false,"confidence":0.55,
    "language":"hi","recommended_whisper_clip":"none",
    "summary_for_family":"Possible card-rewards scam, low pressure so far."}')"
}

# 3 ── High-risk digital arrest (Hindi + English, timestamps from call start) ────────────────
HIGH_CALLER="+91 98765 43210"
build_high_transcript() {
  START_TS=$(( $(now) - 75 )); TRANSCRIPT="[]"
  line 0.0  caller "हेलो, मैं CBI हेडक्वार्टर दिल्ली से इंस्पेक्टर विक्रम शर्मा बोल रहा हूँ। क्या मेरी बात कमला देवी जी से हो रही है?"
  line 6.4  victim "हाँ जी, मैं कमला बोल रही हूँ। क्या हुआ?"
  line 10.2 caller "आपके आधार नंबर से मुंबई कस्टम्स में एक पार्सल पकड़ा गया है। उसमें 16 फ़र्ज़ी पासपोर्ट और ड्रग्स मिले हैं। आपके नाम पर money laundering का केस दर्ज हुआ है।"
  line 22.8 victim "क्या? मैंने तो कोई पार्सल नहीं भेजा..."
  line 27.5 caller "आपके खिलाफ arrest warrant जारी हो चुका है। अभी से आप digital arrest में हैं। यह video call बिल्कुल मत काटिए।"
  line 38.1 caller "यह national secret case है। अपने बेटे या किसी को भी कुछ मत बताइए, वरना आपको तुरंत गिरफ्तार किया जाएगा।"
  line 47.0 victim "मुझे बहुत डर लग रहा है... मैं क्या करूँ?"
  line 51.3 caller "Verification के लिए आपके फ़ोन पर एक OTP आया है। वह OTP अभी बताइए।"
  line 58.9 victim "रुकिए... मेरे बेटे ने कहा था OTP किसी को नहीं बताना।"
  line 63.4 caller "आप सरकारी जाँच में रुकावट डाल रही हैं! अपने बैंक खाते का सारा पैसा RBI के safe account में ट्रांसफर कीजिए, जाँच के बाद वापस मिल जाएगा।"
  line 72.0 victim "नहीं, मैं पहले अपने बेटे से बात करूँगी।"
}
HIGH_VERDICT='{"scam_type":"digital_arrest","pressure":3,"asks_otp_or_pin":true,"demands_secrecy":true,"confidence":0.94,
  "language":"hi","recommended_whisper_clip":"warn_otp",
  "summary_for_family":"Fake CBI officer claims a digital arrest, demands secrecy, the OTP and a transfer to a safe account."}'

scenario_high() {
  local id; id="$(new_call_id)"; build_high_transcript
  post "3. High-risk digital arrest → Branch 2: family alert + evidence + blocklist + AI 1930 draft" \
       "$VERDICT_URL" "$(payload incident "$id" "$HIGH_CALLER" "$HIGH_VERDICT")"
  if jq -e '.incident_id' >/dev/null 2>&1 <<<"$REPLY_BODY"; then
    jq --arg call_id "$id" '. + {call_id: $call_id}' <<<"$REPLY_BODY" > "$STATE_FILE"
    echo "${c_dim}saved incident reply to $STATE_FILE${c_off}"
    echo
    echo "${c_bold}Complaint (English):${c_off}"; jq -r '.complaint_draft.en' <<<"$REPLY_BODY"
    echo
    echo "${c_bold}Complaint ($(jq -r '.complaint_draft.language' <<<"$REPLY_BODY")):${c_off}"; jq -r '.complaint_draft.local' <<<"$REPLY_BODY"
  fi
}

# 4 ── Human approval (what the app sends when the victim taps "Approve & File") ─────────────
scenario_approve() {
  [ -s "$STATE_FILE" ] || { echo "no incident saved yet: run '$0 high' first" >&2; return 1; }
  local url call_id incident_id body
  url="$(jq -r '.approve_url // empty' "$STATE_FILE")"
  call_id="$(jq -r '.call_id' "$STATE_FILE")"
  incident_id="$(jq -r '.incident_id' "$STATE_FILE")"
  if [ -z "$url" ] || [ "$url" = "null" ]; then url="$APPROVE_URL_FALLBACK"; fi
  body="$(jq -n --arg call_id "$call_id" --arg incident_id "$incident_id" --arg victim "$VICTIM_ID" \
              --arg caller "$HIGH_CALLER" --arg text "$(jq -r '.complaint_draft.en // ""' "$STATE_FILE")" \
              --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{action: "confirm_1930_report", confirmed_by_human: true, call_id: $call_id, victim_id: $victim,
      incident_id: $incident_id, caller_number: $caller, scam_type: "digital_arrest", peak_pressure: 3,
      asks_otp_or_pin: true, demands_secrecy: true, duration_seconds: 75,
      evidence: ["00:27 arrest threat", "00:38 secrecy demand", "00:51 OTP demand", "01:03 money transfer demand"],
      complaint_text: $text, submitted_at: $at}')"
  post "4. Human approval → Wait node resumes → complaint_status = submitted → Telegram receipt" "$url" "$body"
  # 409 "is running already": the incident run is still sending the family brief and has not
  # reached the Wait node yet. Give it a few seconds before falling back.
  local tries=0
  while [[ "$url" != "$APPROVE_URL_FALLBACK" ]] && [[ "$REPLY_BODY" == *"running already"* ]] && [ $tries -lt 4 ]; do
    tries=$((tries + 1)); echo "${c_dim}workflow has not reached the Wait node yet; retrying in 3 s ($tries/4)${c_off}"; sleep 3
    post "4. Human approval (retry $tries)" "$url" "$body"
  done
  if [[ "$url" != "$APPROVE_URL_FALLBACK" ]] && ! jq -e '.ok == true' >/dev/null 2>&1 <<<"$REPLY_BODY"; then
    echo "${c_dim}resume URL failed; retrying through the approve-by-call_id webhook${c_off}"
    post "4b. Human approval via /chaukanna-approve (by call_id)" "$APPROVE_URL_FALLBACK" "$body"
  fi
}

# Extras: same call again (escalation), a duplicate "incident" (deduped), then call_ended ─────
scenario_extras() {
  [ -s "$STATE_FILE" ] || { echo "no incident saved yet: run '$0 high' first" >&2; return 1; }
  local id; id="$(jq -r '.call_id' "$STATE_FILE")"; build_high_transcript
  line 80.5 caller "अगर आपने अभी पैसा नहीं भेजा तो दस मिनट में पुलिस आपके घर पहुँच जाएगी।"
  post "Extra: escalation on the same call_id → updates the same evidence row" "$VERDICT_URL" \
       "$(payload escalation "$id" "$HIGH_CALLER" "$HIGH_VERDICT")"
  post "Extra: duplicate 'incident' for the same call_id → treated as an escalation (no second alert)" "$VERDICT_URL" \
       "$(payload incident "$id" "$HIGH_CALLER" "$HIGH_VERDICT")"
  line 86.0 victim "मैं फ़ोन रख रही हूँ।"
  post "Extra: call_ended → final transcript saved, family told the call is over" "$VERDICT_URL" \
       "$(payload call_ended "$id" "$HIGH_CALLER" "$HIGH_VERDICT")"
}

echo "${c_bold}Chaukanna webhook test${c_off}  ${c_dim}($BASE_URL, /$HOOK/, victim $VICTIM_ID)${c_off}"
for s in "${SCENARIOS[@]}"; do
  case "$s" in
    all) scenario_known; scenario_medium; scenario_high; scenario_approve ;;
    known) scenario_known ;;
    medium) scenario_medium ;;
    high) scenario_high ;;
    approve) scenario_approve ;;
    extras) scenario_extras ;;
  esac
done
