# Chaukanna stage demo: run sheet

Two ways to run the same show. Both play the same scripted recordings (`demo/stage/*.wav`, Sarvam TTS), so
the presenter's lines and timings are identical.

- **Plan A, real phone calls** (chaukanna_app PR #1, phone layer). The scammer phone really dials Kamala's
  SIM, she answers in the normal dialer, the app puts the call on loudspeaker and its call tap feeds the
  guardian. The laptop plays the recording into the scammer phone's microphone. Everything after that is
  live: Sarvam STT, the classifier, the warnings over the dialer, n8n, the console.
- **Plan B, robot caller.** `tools/robot_caller.py` joins the LiveKit room as the caller and plays the same
  recording. Rehearsed end to end on 17 Oct 21:25 with a scripted victim, and again at 21:56 on Kamala's real
  phone (installed build of 16:22): all four calls behaved as below; warnings at 29.8 / 40.9 / 49.0 s, n8n reply at
  49 s, redial warning at 6.9 s.

**Go / no-go:** Plan A has not been run on a real call yet (the PR says so too). Use it only if it works in two
rehearsals in a row at the venue, with the hall's network. Otherwise Plan B; nothing else changes.

## Roles

| Role | Does |
|---|---|
| **Operator** (laptop) | runs `demo/stage.sh phone-run` (A) or `demo/stage.sh run` (B), presses Enter for each call, switches console tabs |
| **Presenter** | talks over the calls (lines below) |
| **Kamala** (Nothing phone) | **B:** keeps the app open and taps **Mute** as each call connects (it resets every call). **A:** answers in the normal dialer and does **not** mute (in A the same microphone hears the caller). Stays silent either way |
| **Scammer station** (A only) | the OPPO on USB next to the laptop; nobody touches it, `stage.sh` dials and hangs up |
| **Ravi** (A, optional) | a teammate's phone for the son's call: dials when the operator says so, held at the scammer station |

## 30 minutes before (both plans)

1. Laptop on power, lid open, sleep off. **If Wi-Fi changed:** `docker --context default restart n8n` and
   `sudo systemctl restart cloudflared`.
2. Close every old n8n editor tab (a stale tab can overwrite the workflow; never press Publish in one).
3. Projector: **`http://localhost:8787/console/stage.html`** (full screen, F11). Three panes follow the same call:
   the call graph and pressure gauge (left), the scam network zoomed onto the live caller (top right), and n8n's
   incident workflow step by step (bottom right). The single console (`/console/`) is still there for Q&A.
4. `demo/stage.sh check`: OK for livekit, bridge, classifier, n8n, supabase. telegram WARN is fine unless a
   real chat id was set. (After force-closing the app, LiveKit needs ~30 s to notice it left.)
5. Kamala's phone ≥ 2 m from the PA speakers. Its microphone hears the room: in the 21:56 run on the real phone,
   people talking nearby were transcribed as "YOU: Okay, cool", "हाँ watchman को दे दो" and moved the needle early.
   Plan B: tap **Mute** on every call (tested 21:58: no room speech at all). Plan A cannot mute, so the area around
   the phone must be quiet while a call runs.

### Plan A extras

6. **Kamala's phone runs the PR #1 build** (merged with the OTP-SMS work), built with
   `--dart-define=CALLER_TOKEN_URL=http://localhost:8787/token` plus the usual LiveKit defines. Keep it on USB
   with `adb reverse tcp:8787 tcp:8787` so that URL reaches the laptop.
7. In the app: phone protection **on** (microphone, phone, call log, answer calls, notifications), "Display over
   other apps" allowed, Chaukanna chosen as the **Caller ID & spam app**. Save a contact **Ravi (son)** with
   the son's number.
8. `cp demo/phones.env.example demo/stage/phones.env`, fill in the real numbers (gitignored), then
   `demo/stage.sh phone-setup`. It checks the OPPO is on USB, puts Ravi's number on the trusted list, and
   checks the scammer SIM is not already listed.
9. **Scammer station:** OPPO on USB (`adb devices` shows `bc9ce721`). Best: wired earbuds in the laptop with one
   earbud taped next to the OPPO's bottom microphone, and `export STAGE_SINK=<that output>` (`pactl list short
   sinks`). Then the audience hears the scammer only through Kamala's loudspeaker, like a real call. Without
   earbuds: the OPPO lies against the laptop speaker, laptop volume low, away from the stage mic.
10. **Between rehearsals:** `demo/stage.sh phone-reset`. Each scam call puts the scammer SIM on the scam list, and
    the next first call must start "new" (Plan B avoids this by using a fresh fake number every run).

## The run

Plan A: `demo/stage.sh phone-run`. Plan B: `demo/stage.sh run`. Enter before each call.
Seconds count from the start of the recording (Plan A: about 1 s after Kamala answers). The recordings run at
pace 0.9 with 5 s between lines, so the audience can follow the graph, the warnings and n8n (timings from the
17 Oct 23:08 run on Kamala's phone).

### 1. Delivery call · 34 s · stays silent  (Plan A: only with a third phone in `phones.env`; else skipped)

| s | Audience hears | Console shows |
|---|---|---|
| 0–32 | "Namaste aunty, Amazon delivery… parcel at the gate… watchman" | transcript ~1 s after each sentence, pressure **0 calm** |
| 34 | hang-up | stamp **SAFE CALL · left alone** |

> **Presenter:** "Kamala Devi is 68. A delivery boy calls. Chaukanna is listening, and it stays quiet. Most tools
> would have flagged the word 'parcel'. This one does not cry wolf."

### 2. Scam call · 73 s · the hero

Plan A: the OPPO rings Kamala's phone; the normal dialer shows the number; she answers; the app turns on the
loudspeaker and the warnings come up **over the dialer**.

| s | Audience hears | Console / phone |
|---|---|---|
| 0–25 | "Blue Dart courier… parcel in your name… are you home?" | pressure 0, graph grows from the caller; n8n pane empty |
| 27 | "stuck at Mumbai customs, linked to your Aadhaar" | pressure **1 caution**: the phone says only *"Listening closely. No scam so far"*; n8n pane: **Caution noted** (a quiet log, no alert) |
| **39** | "drugs and fake passports… money laundering" | **WARNING 1**: *"Digital arrest is a scam. Hang up!"* · pressure **2** · banner **n8n incident** · n8n pane: **Incident running…**, steps appear: lookups, family alert text, evidence saved, caller blocklisted, **Gemini** drafting the 1930 complaint |
| 52–54 | "transferring you to the CBI officer… don't tell anyone" | pressure **3** · **WARNING 2**: *"Don't keep it secret! We're alerting your family."* · network: the number now sits on both scam lists |
| 57 | (n8n answers, ~18 s after the incident) | banner: **evidence saved · caller blocklisted · 1930 draft ready**; n8n pane: incident **waiting for her approval** |
| **67** | "an OTP has come on your phone, tell me quickly" | **WARNING 3**: *"Don't share your OTP! It's a scam."* |
| 73 | hang-up | stamp **SCAM CALL · peak p3**. If Kamala approves the complaint in the app, the n8n pane shows "Mark complaint submitted… Compose 1930 receipt" |

> **Presenter (first 20 s):** "Now a courier. Sounds normal. Watch the needle."
> **At the first warning, Plan A:** "That is an ordinary phone call. Chaukanna heard it on the loudspeaker and
> warned her on top of the dialer. And n8n is already working: evidence saved, number blocklisted, a 1930
> complaint drafted in Hindi for her to approve."
> **Plan B:** "There. Only Kamala hears that: her microphone pauses while it plays, so the scammer can't." (Then
> the same n8n line.)
> **After the OTP warning:** "Three warnings, each one landing within a couple of seconds of his sentence."
> **When the n8n pane says "waiting for her approval" (≈57 s), point bottom right:** "That is n8n working live: it
> looked up the number, saved the evidence, blocked the caller, and Gemini wrote the 1930 complaint in Hindi. Nothing
> is filed until Kamala approves it." **Top right:** "And the number is now on the shared scam list, so its next call
> is caught at once."

### 3. Her son asks for an OTP · 30 s · stays calm  (Plan A: needs Ravi's phone)

Plan A: the operator says "Ravi, call now"; Ravi dials Kamala and holds his phone at the scammer station; the
dialer shows **Ravi (son)**.

| s | Audience hears | Console |
|---|---|---|
| 0–25 | "Maa, it's Ravi… the gas cylinder man is here… tell me the OTP" | pressure **1 watch** at the OTP request, **no warning** |

> **Presenter:** "Same word, OTP. But it is her son, a saved contact, and a gas-delivery code. Chaukanna stays calm.
> A guardian that panics at every OTP gets switched off in a week."

### 4. The scammer calls back · 18 s · caught instantly

| s | Audience hears | Console / phone |
|---|---|---|
| 0 | (call starts) | the number is already **on the scam list**: red caller, before anyone speaks |
| **7** | "Hello madam, the call got cut…" | **WARNING**: *"Careful! This number is a known scammer."* |
| 18 | hang-up | stamp **SCAM CALL** · network: the number now has **two calls** |

> **Presenter:** "He calls back. This time she is warned before he finishes his first sentence."

**Operator, right after:** **Network** tab, then the scam number in the left list (Plan A: the OPPO's SIM).
Its calls light up; everything else dims.

> **Presenter:** "Every call, every number, every incident, joined in one graph, the same idea as fraud-ring
> detection. One number calling many grandparents shows up as a ring, not as one call."

## Optional finale: a judge talks to the scammer (`demo/stage.sh live hi` or `live en`)

**One click, no terminal:** the **Chaukanna Stage** app launcher (`demo/chaukanna-stage.desktop`, installed in
`~/.local/share/applications`) runs `demo/stage.sh up`: it starts whatever is down (classifier, token server, bridge,
agent on standby), sets `adb reverse` for a phone on USB and opens the three-pane stage view; log in `logs/up.log`.
On the stage view, pick Hindi or English and press **▶ Start live call**: the AI scammer calls Kamala from a fresh
number, the button turns into **■ End call** (a clean hang-up), and the agent steps in at pressure 3. The scammer's
lines go to `logs/live.log`. Kamala's phone has the same button ("Get a live scam call" on its home screen, in builds
with `--dart-define=STAGE_URL=http://localhost:8787`; needs USB + `adb reverse tcp:8787 tcp:8787`, which `up` sets).
If she presses hang-up in the app, the AI scammer hangs up too (topic `chaukanna.hangup`). `demo/stage.sh down` stops all of it. Tested 18 Oct 07:07: up in 6.5 s from cold,
Start → on the line in ~7 s, End → the bridge saw the caller leave at once.

`tools/ai_scammer.py` is a live, two-way scammer: it listens to Kamala's phone, Gemini 2.5 Flash writes its next line
from the digital-arrest playbook while answering what was actually said, and Sarvam speaks it. Chaukanna judges both
sides, so the judge's answers count too. Tested 17 Oct 23:49 on Kamala's phone: caution at 18 s, warnings at 28, 58
and 67 s, n8n incident at 44 s; it threatened an FIR when refused, then hung up at 115 s.

- Hand the phone to a judge: "He will call you. Talk to him however you like." **Do not mute**: it has to hear you.
- It replies about 3 s after you stop talking; it ends when it hangs up, after 14 lines, or after 4 minutes.
- Follow with `demo/stage.sh redial`: the same number calls back and is flagged at once.
- If Gemini is slow or down, it falls back to the scripted lines, so it never goes silent.

## Lines to keep ready

- **"Is this a real phone call?"**
  - Plan A: "Yes, a normal call to her SIM. The scammer's voice is a recording, so the demo is the same every
    time. Android does not let apps hear calls, so Chaukanna listens on the loudspeaker; the next step is call
    forwarding through a licensed telephony partner, which puts the scammer into this exact pipeline."
  - Plan B: "It is a live call through Chaukanna's own calling, played by a robot caller so the demo is the same
    every time. Everything you saw after that is real and live. Regular SIM calls are next: call forwarding
    through a licensed Indian telephony partner puts the scammer into this exact pipeline."
- **Numbers:** 28/28 scam conversations caught, 0/19 false alarms on ordinary calls (keywords + Jev eval);
  Hindi, Kannada, English; in the rehearsal a warning reached the phone 0.8–2.8 s after the scammer's sentence
  ended (under a second once the call was underway).
- **Privacy:** no call audio is stored; victim OTP digits are masked before anything is saved or sent onward.
- **Honest limit (Plan A):** on an ordinary call the warning plays out loud, so the caller can hear it too.

## If something is red

| Problem | Fix |
|---|---|
| bridge / livekit FAIL | `cd ~/Projects/chaukanna-audio-bridge && .venv/bin/python bridge.py` (check nothing else is running it) |
| classifier FAIL | `cd ~/Projects/chaukanna-classifier/classifier_service && python3 main.py` |
| n8n or supabase FAIL | `docker --context default restart n8n`; `sudo systemctl restart cloudflared` |
| victim_phone WARN | reopen the app; check the phone has internet |
| A: "No answered call reached the guardian" | phone protection off, `CALLER_TOKEN_URL` unreachable (redo `adb reverse tcp:8787 tcp:8787`), or a permission missing. Second time: **switch to Plan B** |
| A: transcript garbled or nothing transcribed | the OPPO is not hearing the recording clearly: move the earbud onto its mic or raise the volume; some phones mute the microphone during calls (a PR limit). Then Plan B |
| A: first scam call already says "known scam number" | you skipped `demo/stage.sh phone-reset` after a rehearsal |
| No family alert | expected unless a real Telegram chat id is on the `trusted_contacts` row |
| One transcript line garbled | speech-to-text slipped on one chunk; the verdict is unaffected, keep going |
| No internet at all | console **Samples** tab + "Tell me the story": the same calls, replayed, no network needed |

## After the event

`demo/stage.sh phone-cleanup`: takes the team's real numbers back out of the classifier's lists. The classifier
writes those lists into its repo (`classifier_service/data/*.json`) and the repo is public, so run this before
committing it. The script confirms when no team number is left.

## Files

- `demo/stage.sh`: Plan A `phone-setup`, `phone-run`, `phone <call>`, `phone-reset`, `phone-cleanup`; Plan B
  `check`, `run`, one call, `new`
- `demo/phones.env.example` → `demo/stage/phones.env`: the real numbers and adb serials (gitignored)
- `demo/stage_lines.py`: every line, number, voice and what each call should do
- `demo/stage_phone.py`: spots the answered call in the bridge's call log
- `demo/make_stage_calls.py`: regenerates the WAVs (`--force` to remake one)
- `demo/stage/*.transcripts.json`: cached transcripts, so `bridge.py --replay-file demo/stage/scam.wav` works offline
