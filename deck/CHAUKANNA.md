# Chaukanna (चौकन्ना): what we are going to cook

> *Chaukanna* = alert, watchful. **The call guardian that acts for you.**

- **Event:** Hack Sprint, MAHE / MIT Bengaluru, 24h in person
- **Dates:** PS drop 17 Oct 10:30 AM, submission 18 Oct 9:30 AM, final judging 18 Oct 10:30–13:00
- **Track:** PS22 · AI Automation with n8n (the track on the submitted deck)
- **Team:** Nikhil, Shreyas, Koustav, Deekshitha (all NMIT)
- **Sponsors on the site:** Paytm, Sarvam, n8n, GDG, TruGen, MLH. Sarvam and n8n are both core to our build.
- **Rule from the organisers:** demo > decks.

---

## 1. The problem

Digital-arrest and KYC scam calls run on **panic**. A fake police, CBI or bank caller keeps the victim on the line and demands secrecy, OTPs and transfers.

The right response is a checklist: call the bank, call 1930, file on cybercrime.gov.in, warn family, keep evidence. Under panic almost nobody does any of it in time. Scripts also change by language, so static block-lists miss them.

Victims are mostly elders and first-time digital users, who are the people least able to run that checklist alone.

## 2. The solution in one line

Calls run **through** Chaukanna. It hears both sides live, spots the scam from how the caller talks, whispers a warning only the victim hears, and then runs the whole response checklist automatically.

**Listen → Understand → Intervene → Respond**

| Step | What happens | Tech |
|---|---|---|
| 1. Listen | Call audio goes through the app, so caller and victim legs are captured **separately** | Flutter + LiveKit (WebRTC) + Python agent |
| 2. Understand | Streaming Indic STT, then a **typed verdict** per chunk: scam type, pressure 0–3, asks for OTP/PIN?, demands secrecy? | Sarvam STT → keyword fast path (<1 ms) + Jev typed judgments (~0.5 s), Gemini fallback |
| 3. Intervene | Alarm screen plus a whispered TTS warning in the victim's language. **Only the victim hears it.** | Flutter + Sarvam TTS |
| 4. Respond | n8n AI Agent alerts family, drafts the 1930 complaint, logs evidence, updates the shared scam-number list | n8n (self-hosted) + Supabase |

### Why the architecture is "through the app"

- Android blocks capturing the other side of a normal phone call, so a speakerphone-mic approach was **rejected**.
- Dual-SIM rerouting was **rejected** (KYC and caller-ID limits).
- The core demo is **app-to-app calling on LiveKit**. A Python agent sits in the middle and hears each leg separately.
- Real phone numbers are a **stretch goal**: call forwarding → Exotel / Plivo / Twilio → LiveKit SIP.

## 3. Architecture

```
 Caller (app/web)            Victim (Flutter app)
        \                         /
         \__ LiveKit room ______/
                  |
        Python agent (hears both legs separately)
                  |
          Sarvam STT (streaming chunks)
                  |
   classifier (keywords + Jev) ──► typed verdict
          {scam_type, pressure 0-3, asks_otp_pin, demands_secrecy}
                  |
              Risk gate  ── threshold crossed ──┐
                  |                              |
        LIVE PATH (victim only)          n8n webhook (verdict + transcript)
        alarm + Sarvam TTS whisper               |
                                          n8n AI Agent (tools, Switch/IF, retries)
                                                 |
        ┌──────────────┬──────────────────┬──────┴───────────┐
   Family alert   1930 complaint     Evidence log      Shared scam list
 (Telegram +     draft in victim's   (Supabase:        (Supabase; known
  summary)       language, HUMAN     transcript +      number = instant
                 CONFIRMS to file    timestamps)       high confidence)
```

Both paths fire **in parallel** when the risk gate trips, so the whisper is never waiting on n8n.

### Verdict schema (the contract between every component)

```json
{
  "scam_type": "digital_arrest | kyc_update | bank_impersonation | prize_lottery | other | none",
  "pressure": 0,
  "asks_otp_or_pin": false,
  "demands_secrecy": false,
  "confidence": 0.0,
  "language": "hi | kn | en"
}
```

## 4. Decision rules (the "Beyond Task Automation" slide)

| When the agent sees… | …it decides and acts |
|---|---|
| Pressure ≥ 2 **and** asks for OTP / PIN | Whisper "Do not share that code", ring alarm, ping trusted contacts now |
| Poses as police / CBI **and** demands secrecy | Highest severity: send family the call summary and next steps |
| Number already in shared scam list | Raise confidence, block, skip the guessing |
| Call ends, victim confirms what happened | Draft the 1930 / cybercrime.gov.in complaint in their language with transcript timestamps |
| Money already moved | Switch to the time-critical checklist: bank freeze steps and helpline, in order |

**A human confirms only the one irreversible step: submitting the complaint.** Everything else runs autonomously.

## 5. Stack

| Layer | Choice |
|---|---|
| App | Flutter (Android), LiveKit client |
| Real-time audio | LiveKit (WebRTC); Python agent using the LiveKit agents SDK |
| Speech | Sarvam STT and TTS. Built and tested for Hindi, Kannada and English (incl. Hinglish / Kanglish); other Indic languages are roadmap |
| Classifier | FastAPI on :8010. Keyword fast path answers every chunk in milliseconds; **Jev** (TypeSafe System One) adds typed, calibrated judgments in ~0.5 s; Gemini 2.5 Flash if Jev is slow. Eval: 28/28 scams caught on time, 0/19 false alarms |
| LLM fallback | Sarvam LLM or Gemini for classification and for complaint drafting |
| Automation | n8n (self-hosted at n8n.premortem.tech): webhook, AI Agent node with tools, Switch/IF, retries, Wait-for-approval |
| Data | Supabase: evidence log, shared scam-number list |
| Notify | Telegram bot alerts to trusted contacts, with "I'm calling them now" / "False alarm" buttons |

Pitch line: *open, cheap and auditable*. The classifier answers in milliseconds, and n8n (self-hosted) keeps call data under our control.

## 6. The n8n response workflow

1. **Webhook** receives `{verdict, transcript, call_id, victim_id}`
2. **AI Agent** (tools: look up trusted contacts, check scam list, draft complaint, write evidence)
3. **Switch** on severity:
   - *High*: family alert immediately
   - *Medium*: soft in-app nudge, keep listening
   - *Known number*: block and log
4. **Family alert**: summary, caller claim, what to do next
5. **Evidence**: transcript with timestamps into Supabase
6. **Shared list**: add the number (feedback loop)
7. **Post-call**: complaint draft in the victim's language, then a **Wait node for human confirmation**, then file/submit
8. **Retries and error branch** so a failure never silently drops an alert

Keep this workflow **visual and tidy**. The n8n canvas is a judging asset ("auditable response flow judges and families can follow").

## 7. The demo (this is what wins)

**The demo is a live scam call to a judge.**

1. Judge (or a teammate) installs/opens the app as the "victim".
2. A teammate calls in as a fake "CBI officer" and runs a digital-arrest script in Hindi/Kannada: *"Your Aadhaar is linked to a money laundering case… do not tell anyone… share the OTP to verify."*
3. On screen: live transcript, **pressure meter climbing**, verdict chips (scam type, OTP ask, secrecy).
4. Pressure crosses the threshold: **alarm screen** and the whisper ("Do not share that code") plays **only in the victim's earbud/phone**.
5. Flip to the **n8n canvas**: the execution runs live, branch lights up.
6. Show the results: family phone buzzes with the alert, the 1930 complaint draft appears, the evidence row lands in Supabase, the number is added to the shared list.
7. Redial from the same number: **instantly flagged** from the shared list.

Target length: 3 minutes, rehearsed at least 3 times.

## 8. 24-hour plan

> Roles below are a **proposal**. Adjust to who is strongest at what.

| Workstream | Owner (proposed) | Output |
|---|---|---|
| Flutter app: call UI, alarm screen, after-call report, contacts | Deekshitha + Shreyas | Working app with all three screens |
| LiveKit room + Python agent, Sarvam STT/TTS wiring | Nikhil | Both legs transcribed live, whisper to victim only |
| Classifier (keywords + Jev, Gemini fallback) | Nikhil | `/classify` endpoint returning the verdict schema (built) |
| n8n workflow + Supabase tables + notifications | Koustav | Full response flow triggered by webhook |
| Demo script, scam scripts in 3+ languages, rehearsal | Everyone | Rehearsed 3-minute demo |

| Hours | Goal |
|---|---|
| 0–2 | Read the PS, confirm PS22 and scoring, set up repo, accounts, API keys, LiveKit project, shared `.env` |
| 2–8 | Core loop: LiveKit call → STT → classify → verdict printed. n8n webhook skeleton. Flutter call screen. |
| 8–14 | Whisper/alarm path end-to-end. n8n agent with tools. Supabase tables. Family alert working. |
| 14–18 | Complaint drafting + human-approval step. Shared scam list lookup. After-call report screen. |
| 18–21 | Harden: failure paths, latency, language tests, record a **backup demo video**. |
| 21–23 | Rehearse demo, tidy n8n canvas, finish README, prepare the submission. |
| 23–24 | Freeze. No new features. Sleep a little if possible. Submit **before 9:30 AM**. |

### Priorities if time runs short (cut from the bottom)

1. **Must have:** live call, transcription, verdict, alarm plus whisper, n8n family alert
2. **Should have:** 1930 complaint draft with approval, evidence log, shared scam list
3. **Nice:** multi-language beyond Hindi/English, after-call report polish
4. **Stretch:** real phone numbers via SIP

## 9. Risks and fallbacks

| Risk | Fallback |
|---|---|
| LiveKit / WebRTC breaks on venue Wi-Fi | **Recorded-call demo mode**: replay a scripted call through the same pipeline. Use phone hotspot. |
| Jev slow or down | Gemini answers instead after 1.5 s; keywords answer every chunk regardless (the contract doesn't change) |
| Classifier on the laptop unreachable | The bridge falls back to its own keyword verdict, so the whisper still fires |
| n8n tunnel down (laptop-hosted at n8n.premortem.tech) | Keep laptop plugged in and on stable internet. Export the workflow JSON as backup. |
| Sarvam rate limits / latency | Cache the TTS whisper phrases for the common warnings (pre-generate in each language) |
| STT mishears Indic accents on a noisy hall | Rehearse in the hall, use headset mics, keep scam scripts clean and clear |
| Supabase / notification fails during demo | Pre-seeded rows plus the backup video |
| Wi-Fi dies completely | Backup demo video, then walk through the n8n canvas statically |

## 10. Things to do **before** the event starts

- [ ] Sarvam API key working (check `aura/keys.env`; Sarvam key status unknown)
- [ ] LiveKit Cloud project (or self-hosted) and keys
- [ ] n8n instance reachable from the internet, Supabase project ready
- [ ] Flutter SDK at `~/flutter/bin`, an Android phone with USB debugging
- [x] Labelled eval set: 28 scam + 19 legit conversations (Hindi, Kannada, English, mixed) in `chaukanna-classifier/classifier_service/evalset/`
- [ ] Pre-written scam scripts: digital arrest, KYC update, bank impersonation, plus one **innocent** call (to prove it doesn't cry wolf)
- [ ] Pre-generated TTS whisper clips per language
- [ ] Power strips, chargers, headsets, a hotspot
- [ ] Confirm with organisers: are sponsor prizes open to all tracks, is the podium overall or per track

## 11. Pitch cheat sheet

- **30 seconds:** "Scam callers win by keeping you panicked and alone. Chaukanna sits on the call, hears the scam in your language, whispers a warning only you hear, and while you hang up it alerts your family, drafts your 1930 complaint, and protects the next person."
- **Why n8n:** a visual, auditable response flow with an AI Agent node, tools, branching, retries and a human-approval step. It isn't just triggers.
- **Why Sarvam:** Indic speech in and out, which is the point for first-time users.
- **Why keywords + Jev:** milliseconds per chunk, typed and calibrated answers instead of parsed LLM text, and it caught every scam in the eval on time (Gemini alone was late on 4 of 28).
- **Impact:** protects elders and first-time digital users, turns minutes of panic into steps that run on their own, and every report grows a shared scam-number list.
- **Roadmap:** hackathon (app-to-app guardian plus full n8n response), next (real numbers via SIP), then (more Indic languages, sharing signals with banks and telecoms).

## 12. Open questions

- Exact scoring rubric for PS22, and whether the second round changed anything.
- Whether judges will accept an app-to-app demo, or expect real phone numbers.
- (Resolved 2026-10-15: Laya was never built; Jev replaced it, with Gemini as the fallback.)
- Who plays the scammer and who plays the victim in the demo.
