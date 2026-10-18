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
#   demo/stage.sh live [hi|en]                  a live AI scammer (tools/ai_scammer.py): talk back to it
#
# Agent interception mode (tools/interceptor.py): keep this running in its own terminal. When a call reaches
# pressure 3 (or you press "Intercept now" in console/stage.html), the agent joins and talks to Kamala only;
# her app cuts the caller off both ways. Add your own agents from stage.html ("+ Add agent") or agents/*.json.
#   demo/stage.sh agents [agent-id] [--no-auto]
#
# On demand (a mentor walks up): one command starts everything in the background and returns at once.
#   demo/stage.sh show                          agent on standby + delivery, scam, son, redial (~4 min)
#   demo/stage.sh stop                          stop the calls and the agent now (bridge + server keep running)
#
# One click (the "Chaukanna stage" app launcher runs `up`): start whatever is down, open the three-pane view.
# Its "Start live call" button then has the AI scammer call Kamala; the agent stands by to intercept.
#   demo/stage.sh up [--no-open]                classifier, token server, bridge, agent standby, stage view
#   demo/stage.sh down                          stop all of it (n8n and cloudflared are left alone)
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
PY=.venv/bin/python
CLASSIFIER_DIR=${CLASSIFIER_DIR:-$HOME/Projects/chaukanna-classifier/classifier_service}
STAGE_URL=http://localhost:8787/console/stage.html
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

ai_call() {                          # live two-way call with the AI scammer: talk back to it
  new_number
  note "AI scammer calling from $(scam_number) in ${1:-hi}. Answer on Kamala's phone and talk; do NOT mute."
  $PY tools/ai_scammer.py --phone "$(scam_number)" --lang "${1:-hi}" 2>&1 | grep -vE "livekit|rtc_engine|signal_stream|VAAPI|Decoder" || true
  note "call ended. 'demo/stage.sh redial' now calls back from the same number."
}

agents() {                           # standby: an interception agent joins scam calls
  local id=${1:-chaukanna-safety}; shift || true
  [ -f "agents/$id.json" ] || die "no agents/$id.json (have: $(cd agents && ls *.json | sed 's/\.json$//' | tr '\n' ' '))"
  say "Interception standby: $id"; note "stage.html shows the agent bar; Ctrl-C to stop."
  exec $PY tools/interceptor.py --agent "$id" "$@" 2> >(grep -vE "livekit|rtc_engine|signal_stream|VAAPI|Decoder" >&2)
}

show() {
  stop_all quiet
  $PY -c "import json,sys; sys.exit(0 if json.load(open('calls/_bridge.json')).get('victim_present') else 1)" 2>/dev/null \
    || note "WARN Kamala's phone is not in the room: open the app (the calls start anyway)"
  setsid nohup $PY tools/interceptor.py --agent chaukanna-safety >> logs/interceptor.log 2>&1 < /dev/null &
  setsid nohup bash "$0" show-calls >> logs/show.log 2>&1 < /dev/null &
  say "Running: delivery → scam → son → redial (~4 min). Agent joins the scam at pressure 3."
  note "stop: demo/stage.sh stop    log: logs/show.log"
}
show_calls() {
  new_number
  for c in delivery scam son redial; do echo "$(date +%T) === $c"; robot_call "$c" || true; sleep 7; done
  echo "$(date +%T) done"; stop_all quiet
}
stop_all() {                        # exact matches only: never this shell
  local p pid c n=0
  for p in /proc/[0-9]*; do
    pid=${p#/proc/}; [ "$pid" = $$ ] && continue
    c=$(tr '\0' ' ' 2>/dev/null < "$p/cmdline") || continue
    case "$c" in
      "bash $0 show-calls "|"$PY tools/robot_caller.py "*|"$PY tools/ai_scammer.py "*|"$PY tools/interceptor.py "*)
        kill "$pid" 2>/dev/null && n=$((n + 1)) ;;
    esac
  done
  [ "${1:-}" = quiet ] || note "stopped $n process(es); bridge + token server still running"
}

# ------------------------------------------------------------------ one click: the whole system
port_up() { ss -Hltn "sport = :$1" 2>/dev/null | grep -q .; }
running() { $PY procs.py running "$1"; }
bridge_fresh() {                    # the bridge rewrites calls/_bridge.json every heartbeat (5 s)
  $PY -c "import json,sys,time; sys.exit(0 if time.time() - json.load(open('calls/_bridge.json'))['ts'] < 15 else 1)" 2>/dev/null
}
bg() {                              # bg <log> <cmd…>: detached, survives the launcher and the token server
  local log=$1; shift
  setsid nohup "$@" >> "$log" 2>&1 < /dev/null &
}
wait_for() {                        # wait_for <seconds> <what> <test…>
  local n=$1 what=$2; shift 2
  for _ in $(seq "$n"); do "$@" && { note "OK   $what"; return 0; }; sleep 1; done
  note "FAIL $what did not come up (see logs/)"; return 1
}

up() {
  mkdir -p logs calls
  say "Starting the Chaukanna stage system ($(date +%T))"
  if port_up 8787; then note "OK   token server already up"
  else bg logs/token_server.log $PY token_server.py; wait_for 15 "token server :8787" port_up 8787 || true; fi
  if [ "${1:-}" != --no-open ]; then             # open it now: its status strip turns green as the rest comes up
    bg /dev/null google-chrome-stable --ozone-platform=x11 --new-window "$STAGE_URL"
    note "stage view: $STAGE_URL (F11 for full screen)"
  fi
  if port_up 8010; then note "OK   classifier already up"
  else (cd "$CLASSIFIER_DIR" && bg "$ROOT/logs/classifier.log" python3 main.py); wait_for 25 "classifier :8010" port_up 8010 || true; fi
  if running bridge.py; then note "OK   bridge already up"
  else rm -f calls/_bridge.json; bg logs/bridge.log $PY bridge.py; wait_for 30 "bridge in the LiveKit room" bridge_fresh || true; fi
  if running tools/interceptor.py; then note "OK   agent already on standby"
  else bg logs/interceptor.log $PY tools/interceptor.py --agent chaukanna-safety; note "OK   agent on standby (joins at pressure 3)"; fi
  local s
  for s in $(adb devices 2>/dev/null | awk 'NR > 1 && $2 == "device" {print $1}'); do
    adb -s "$s" reverse tcp:8787 tcp:8787 >/dev/null 2>&1 && note "OK   phone $s reaches the laptop (adb reverse :8787)"
  done
  note "ready: press \"Start live call\" on the stage view"
}

down() {
  say "Stopping the Chaukanna stage system"
  stop_all quiet
  local s n
  for s in tools/ai_scammer.py tools/interceptor.py bridge.py token_server.py; do
    n=$($PY procs.py stop "$s"); note "stopped $s ($n)"
  done
  n=$(ss -Hltnp "sport = :8010" 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u)
  [ -n "$n" ] && kill $n && note "stopped the classifier ($n)"
  note "n8n and cloudflared keep running"
}

live_bg() {                          # the stage page's "Start live call" (token_server POST /console/api/live)
  up --no-open
  new_number
  echo "$(date +%T) === live AI scammer ($1) from $(scam_number)"
  exec $PY tools/ai_scammer.py --phone "$(scam_number)" --lang "$1"
}

case "${1:-}" in
  up) up "${2:-}" ;;
  app) mkdir -p logs; up >> logs/up.log 2>&1 ;;        # the app launcher (demo/chaukanna-stage.desktop)
  down) down ;;
  live-bg) live_bg "${2:-hi}" ;;
  show) show ;;
  show-calls) show_calls ;;
  stop) stop_all ;;
  check) check ;;
  agents) shift; agents "$@" ;;
  live) ai_call "${2:-hi}" ;;
  run) robot_run ;;
  new) new_number ;;
  delivery|scam|son|redial|chat|chat_en|scam_en) robot_call "$1" ;;
  phone-setup) phone_setup ;;
  phone-run) phone_run ;;
  phone) phone_call "${2:?which call: scam|redial|son|delivery}" ;;
  phone-reset) phone_reset ;;
  phone-cleanup) phone_cleanup ;;
  *) sed -n '2,29p' "$0"; exit 2 ;;
esac
