#!/usr/bin/env bash
# Stage demo driver. Run sheet: demo/RUNSHEET.md. Calls and lines: demo/stage_lines.py.
#
# Plan A, real phone calls (chaukanna_app PR #1 phone layer): the scammer phone really dials Kamala's SIM,
# she answers in the normal dialer, the app puts the call on loudspeaker and its call tap feeds the guardian.
# The laptop plays the scripted recording next to the scammer phone's microphone, so every run matches.
#   demo/stage.sh phone-setup                   check phones + config, trust the son's number
#   demo/stage.sh phone-run                     the whole demo, one call per Enter
#   demo/stage.sh phone scam|redial|son|delivery
#   demo/stage.sh phone-reset                   between rehearsals: un-list the scammer SIM, restart the bridge
#   demo/stage.sh phone-cleanup                 after the event: remove the team's real numbers everywhere
#
# Plan B, robot caller (no SIM): tools/robot_caller.py joins the LiveKit room as the caller.
#   demo/stage.sh check | run | delivery|scam|son|redial | new
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
DIR=demo/stage
NUM_FILE=$DIR/.scam_number
COUNTER=$DIR/.counter
PHONES=$DIR/phones.env              # real numbers: gitignored, see demo/phones.env.example
CLASSIFIER=${CLASSIFIER_BASE:-http://127.0.0.1:8010}

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
note() { printf '  %s\n' "$*"; }
die()  { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

# ------------------------------------------------------------------ shared
check() {
  curl -s --max-time 15 http://127.0.0.1:8787/console/api/health | $PY -c '
import json, sys
d = json.load(sys.stdin)
must = ["livekit", "bridge", "classifier", "n8n", "supabase"]
want = ["victim_phone", "telegram"]
bad = 0
for k in must + want:
    v = d.get(k, {}); ok = v.get("ok"); detail = v.get("detail", "")
    mark = "OK  " if ok else ("FAIL" if k in must else "WARN")
    bad += (not ok) and k in must
    print(f"  {mark} {k:13} {detail}")
sys.exit(1 if bad else 0)
' || { say "Fix the FAIL lines first (see RUNSHEET.md, 'If something is red')."; return 1; }
}

wav_of() { [ -f "$DIR/$1.wav" ] || die "missing $DIR/$1.wav: run $PY demo/make_stage_calls.py"; echo "$DIR/$1.wav"; }

# ------------------------------------------------------------------ Plan B: robot caller
new_number() {                      # a never-used number, so the first scam call is "new" and the redial "known"
  local n; n=$(( $(cat "$COUNTER" 2>/dev/null || echo 100) + 1 ))
  echo "$n" > "$COUNTER"
  printf '+91 90000 3%04d\n' "$n" > "$NUM_FILE"
  note "scam number for this run: $(cat "$NUM_FILE")"
}
scam_number() { [ -f "$NUM_FILE" ] || new_number >/dev/null; cat "$NUM_FILE"; }

robot_call() {                      # robot_call <name>
  local name=$1 phone label="" wav; wav=$(wav_of "$name")
  case $name in
    delivery) phone="+91 90000 20001" ;;
    son)      phone="+91 98450 12345"; label="Ravi (son)" ;;
    chat)     phone="+91 90000 20002"; label="Sunita (neighbour)" ;;
    chat_en)  phone="+91 90000 20003"; label="Priya (neighbour)" ;;
    scam|redial|scam_en) phone=$(scam_number) ;;
    *) die "unknown call: $name" ;;
  esac
  note "calling from $phone${label:+ ($label)} … (waits up to 60 s for the victim app)"
  $PY tools/robot_caller.py "$wav" --phone "$phone" --label "$label" 2>&1 \
    | grep -vE "livekit|rtc_engine|signal_stream|VAAPI|Decoder" || true
  note "call ended"
}

robot_run() {
  check || exit 1
  note "next scam number: $(scam_number)"
  new_number
  say "Console: http://localhost:8787/console/  (Live tab; 'Jump to a new call' is ticked)"
  local beats=(
    "delivery|1/4  An ordinary delivery call|Stays silent: pressure 0, no whisper. 'It does not cry wolf.'"
    "scam|2/4  The scam call (≈53 s)|Calm ~20 s, then whispers at 'drugs' (digital arrest), 'don't tell anyone' (secrecy), 'OTP'; n8n incident at pressure 2."
    "son|3/4  Her son asks for an OTP|OTP request, yet calm: trusted caller + gas-delivery code. Pressure 1, no whisper."
    "redial|4/4  The scammer calls back|Flagged in the first sentence: known scam number, whisper at once. Then open Network."
  )
  for b in "${beats[@]}"; do
    IFS='|' read -r name title what <<<"$b"
    say "$title"; note "$what"
    read -r -p "  Enter to call … " _
    robot_call "$name"
  done
  say "Done. Network tab → click $(scam_number) → its two calls."
}

# ------------------------------------------------------------------ Plan A: real phone calls
load_phones() {
  [ -f "$PHONES" ] || die "no $PHONES: cp demo/phones.env.example $PHONES and fill in the numbers"
  # shellcheck disable=SC1090
  source "$PHONES"
  : "${VICTIM_SIM:?set VICTIM_SIM in $PHONES}" "${SCAMMER_SIM:?set SCAMMER_SIM in $PHONES}"
  SCAMMER_SERIAL=${SCAMMER_SERIAL:-}; SON_SIM=${SON_SIM:-}; SON_SERIAL=${SON_SERIAL:-}
  DELIVERY_SIM=${DELIVERY_SIM:-}; DELIVERY_SERIAL=${DELIVERY_SERIAL:-}
}
digits() { tr -cd '0-9+' <<<"$1"; }

adb_ok() { [ -n "$1" ] && adb -s "$1" get-state >/dev/null 2>&1; }

listed_in_classifier() {            # is this number on the classifier's scam list?
  curl -s --max-time 3 "$CLASSIFIER/scam_numbers" | $PY -c '
import json, re, sys
want = re.sub(r"\D", "", sys.argv[1])[-10:]
rows = json.load(sys.stdin).get("numbers", [])
sys.exit(0 if any(re.sub(r"\D", "", r.get("number", ""))[-10:] == want for r in rows) else 1)' "$1"
}

restart_bridge() {                  # the bridge keeps incident callers in memory: restart it to forget one
  local pid
  for pid in $(pgrep -f "bridge.py" || true); do
    if tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -qE "python bridge\.py\s*$"; then kill "$pid"; fi
  done
  sleep 2; mkdir -p logs
  setsid nohup $PY bridge.py >> logs/bridge.log 2>&1 < /dev/null &
  for _ in $(seq 1 30); do grep -q "joined room" <(tail -5 logs/bridge.log) && break; sleep 0.5; done
  note "bridge restarted (log: logs/bridge.log)"
}

phone_setup() {
  load_phones
  say "Phones"
  adb_ok "$SCAMMER_SERIAL" && note "OK   scammer phone on USB ($SCAMMER_SERIAL): dials automatically" \
                           || note "WARN scammer phone not on USB: you will dial $VICTIM_SIM by hand"
  if [ -n "$SON_SIM" ]; then
    curl -s --max-time 3 -X POST "$CLASSIFIER/trusted_numbers" -H 'Content-Type: application/json' \
      -d "{\"number\": \"$(digits "$SON_SIM")\", \"name\": \"Ravi (son)\", \"note\": \"stage demo: a teammate's phone\"}" >/dev/null \
      && note "OK   $SON_SIM is on the trusted list as Ravi (son)"
  else
    note "WARN no SON_SIM: the son call is skipped"
  fi
  if listed_in_classifier "$SCAMMER_SIM"; then
    note "WARN the scammer SIM is already on the scam list (an earlier rehearsal): run demo/stage.sh phone-reset"
  else
    note "OK   the scammer SIM is not on the scam list yet, so the first call starts 'new'"
  fi
  say "On Kamala's phone (chaukanna_app with PR #1, built with CALLER_TOKEN_URL)"
  note "1. Home → phone protection ON: microphone, phone, call log, answer calls, notifications"
  note "2. 'Display over other apps' allowed, Chaukanna chosen as the Caller ID & spam app"
  note "3. A contact 'Ravi (son)' saved with $SON_SIM, so the dialer shows his name"
  note "4. Loudspeaker volume up; the phone lies screen-up next to the presenter's mic"
  say "System"; check || true
}

phone_call() {                      # phone_call <name>: dial (or ask), wait for the answer, play, hang up
  load_phones
  local name=$1 wav serial sim who since cid
  wav=$(wav_of "$name")
  case $name in
    scam|redial) serial=$SCAMMER_SERIAL; sim=$SCAMMER_SIM; who="the scammer phone" ;;
    son)      serial=$SON_SERIAL; sim=$SON_SIM; who="Ravi's phone" ;;
    delivery) serial=$DELIVERY_SERIAL; sim=$DELIVERY_SIM; who="the delivery phone" ;;
    *) die "unknown call: $name" ;;
  esac
  [ -n "$sim" ] || die "no number for the $name call in $PHONES"
  since=$(date +%s)
  if adb_ok "$serial"; then
    adb -s "$serial" shell am start -a android.intent.action.CALL -d "tel:$(digits "$VICTIM_SIM")" >/dev/null
    note "$who is dialling $VICTIM_SIM …"
  else
    note "Dial $VICTIM_SIM from $who ($sim) now, and put it next to the laptop speaker."
  fi
  note "Kamala: answer in the normal dialer (the app switches to loudspeaker)."
  if ! cid=$($PY demo/stage_phone.py wait-call --since "$since" --number "$sim" --timeout 60); then
    if [ "$name" = redial ]; then
      say "No call reached the guardian: Chaukanna blocked $sim before it rang (or nobody answered)."
    else
      note "No answered call reached the guardian within 60 s: is phone protection on, and the token URL reachable?"
    fi
    adb_ok "$serial" && adb -s "$serial" shell input keyevent KEYCODE_ENDCALL || true
    return 0
  fi
  note "answered: $cid (console follows it). Playing the recording next to $who …"
  sleep 1
  paplay ${STAGE_SINK:+-d "$STAGE_SINK"} "$wav"     # STAGE_SINK: another output, e.g. a Bluetooth speaker
  sleep 1.5
  if adb_ok "$serial"; then adb -s "$serial" shell input keyevent KEYCODE_ENDCALL; note "hung up"
  else read -r -p "  Hang up on $who, then Enter … " _; fi
  $PY demo/stage_phone.py wait-end --call-id "$cid" --timeout 15 && note "call ended" || note "call still open in the bridge"
}

phone_run() {
  load_phones
  check || exit 1
  if listed_in_classifier "$SCAMMER_SIM"; then die "The scammer SIM is already listed: run demo/stage.sh phone-reset first."; fi
  say "Console: http://localhost:8787/console/  (Live tab; 'Jump to a new call' is ticked)"
  local beats=()
  [ -n "$DELIVERY_SIM" ] && beats+=("delivery|An ordinary delivery call|Stays silent: pressure 0, no whisper.")
  beats+=("scam|The scam call (≈53 s)|A real call: the dialer shows the number. Whispers at 'drugs', 'don't tell anyone', 'OTP'; n8n incident.")
  [ -n "$SON_SIM" ] && beats+=("son|Her son asks for an OTP|His saved number, a gas-delivery code: pressure 1, no whisper.")
  beats+=("redial|The scammer calls back|Known number: flagged the moment she answers (or never rings, with number blocking learning it).")
  local i=0
  for b in "${beats[@]}"; do
    i=$((i + 1)); IFS='|' read -r name title what <<<"$b"
    say "$i/${#beats[@]}  $title"; note "$what"
    read -r -p "  Enter to call … " _
    phone_call "$name"
  done
  say "Done. Network tab → click $SCAMMER_SIM → its calls."
}

phone_reset() {                     # between rehearsals: the scammer SIM must start "new" again
  load_phones
  curl -s --max-time 3 -X DELETE "$CLASSIFIER/scam_numbers/$(digits "$SCAMMER_SIM" | sed 's/+/%2B/')" >/dev/null || true
  listed_in_classifier "$SCAMMER_SIM" && note "WARN still listed in the classifier" || note "OK   scammer SIM removed from the classifier's list"
  restart_bridge
  note "Supabase scam_numbers still has it (n8n will say 'reported N times'); that does not change the first-call flag."
}

phone_cleanup() {                   # the classifier writes both lists into its repo files: get real numbers out
  load_phones
  phone_reset
  [ -n "$SON_SIM" ] && curl -s --max-time 3 -X DELETE "$CLASSIFIER/trusted_numbers/$(digits "$SON_SIM" | sed 's/+/%2B/')" >/dev/null \
    && note "OK   Ravi's real number removed from the trusted list"
  local f found=0
  for f in ~/Projects/chaukanna-classifier/classifier_service/data/*.json; do
    for n in "$SCAMMER_SIM" "$SON_SIM" "$DELIVERY_SIM"; do
      [ -n "$n" ] && grep -q "$(digits "$n" | tail -c 10)" "$f" && { note "WARN $n still in $f"; found=1; }
    done
  done
  [ $found = 0 ] && note "OK   no team numbers left in the classifier's data files (safe to commit)"
}

case "${1:-}" in
  check) check ;;
  run) robot_run ;;
  new) new_number ;;
  delivery|scam|son|redial|chat|chat_en|scam_en) robot_call "$1" ;;
  phone-setup) phone_setup ;;
  phone-run) phone_run ;;
  phone) phone_call "${2:?which call: scam|redial|son|delivery}" ;;
  phone-reset) phone_reset ;;
  phone-cleanup) phone_cleanup ;;
  *) sed -n '2,16p' "$0"; exit 2 ;;
esac
