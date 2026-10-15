#!/usr/bin/env python3
"""Batch-generate Chaukanna scam-warning whispers with Sarvam AI TTS.

    python generate.py              # generate all 12 clips + manifest.json
    python generate.py --force      # regenerate even if the file already exists
    python generate.py --verify     # check the 12 files exist, are non-empty, print durations

Zero dependencies (stdlib only). Reads SARVAM_API_KEY from .env or the environment.
"""
import argparse
import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "output_assets"
MANIFEST = OUT_DIR / "manifest.json"

API_URL = "https://api.sarvam.ai/text-to-speech"
MODEL = "bulbul:v3"
SPEAKER = "ritu"          # calm female bulbul:v3 voice; override with --speaker
PACE = 0.95               # slightly slower = clearer when whispered into a live call
SAMPLE_RATE = 24000

# language short code -> Sarvam language code
LANGS = {"hi": "hi-IN", "kn": "kn-IN", "en": "en-IN"}

# warning_type -> language -> script
WARNINGS = {
    "warn_otp": {
        "hi": "सावधान! किसी को भी अपना ओटीपी या पिन न बताएं। बैंक और पुलिस कभी फ़ोन पर ओटीपी या पिन नहीं मांगते।",
        "kn": "ಎಚ್ಚರಿಕೆ! ನಿಮ್ಮ ಒಟಿಪಿ ಅಥವಾ ಪಿನ್ ಅನ್ನು ಯಾರಿಗೂ ಹೇಳಬೇಡಿ. ಬ್ಯಾಂಕ್ ಅಥವಾ ಪೊಲೀಸರು ಎಂದಿಗೂ ಫೋನ್‌ನಲ್ಲಿ ಒಟಿಪಿ ಅಥವಾ ಪಿನ್ ಕೇಳುವುದಿಲ್ಲ.",
        "en": "Warning! Do not share your OTP or PIN with anyone. Banks and the police never ask for it over a call.",
    },
    "warn_digital_arrest": {
        "hi": "सावधान! पुलिस, सीबीआई और अदालतें कभी फ़ोन या वीडियो कॉल पर डिजिटल अरेस्ट या पूछताछ नहीं करतीं। यह धोखा है। कॉल काट दें।",
        "kn": "ಎಚ್ಚರಿಕೆ! ಪೊಲೀಸರು, ಸಿಬಿಐ ಮತ್ತು ನ್ಯಾಯಾಲಯಗಳು ಎಂದಿಗೂ ಫೋನ್ ಅಥವಾ ವಿಡಿಯೋ ಕರೆಯಲ್ಲಿ ಡಿಜಿಟಲ್ ಅರೆಸ್ಟ್ ಅಥವಾ ವಿಚಾರಣೆ ಮಾಡುವುದಿಲ್ಲ. ಇದು ವಂಚನೆ. ಕರೆಯನ್ನು ಕಟ್ ಮಾಡಿ.",
        "en": "Warning! The police, the CBI and the courts never conduct a digital arrest or interrogation over a phone or video call. This is a scam. Hang up.",
    },
    "warn_secrecy": {
        "hi": "सावधान! यह कॉलर आपको सबसे अलग करने की कोशिश कर रहा है। हम अभी आपके भरोसेमंद परिवार के सदस्य को सूचित कर रहे हैं।",
        "kn": "ಎಚ್ಚರಿಕೆ! ಈ ಕರೆ ಮಾಡಿದವರು ನಿಮ್ಮನ್ನು ಎಲ್ಲರಿಂದ ಪ್ರತ್ಯೇಕಿಸಲು ಪ್ರಯತ್ನಿಸುತ್ತಿದ್ದಾರೆ. ನಾವು ಈಗಲೇ ನಿಮ್ಮ ವಿಶ್ವಾಸಾರ್ಹ ಕುಟುಂಬ ಸದಸ್ಯರಿಗೆ ಮಾಹಿತಿ ನೀಡುತ್ತಿದ್ದೇವೆ.",
        "en": "Warning! This caller is trying to isolate you. We are alerting your trusted family contact right now.",
    },
    "warn_known_scammer": {
        "hi": "सावधान! इस फ़ोन नंबर की शिकायत पहले ही चौकन्ना नेटवर्क पर एक जाने-माने ठग के रूप में की जा चुकी है।",
        "kn": "ಎಚ್ಚರಿಕೆ! ಈ ಫೋನ್ ನಂಬರ್ ಅನ್ನು ಚೌಕನ್ನ ನೆಟ್‌ವರ್ಕ್‌ನಲ್ಲಿ ಈಗಾಗಲೇ ಕುಖ್ಯಾತ ವಂಚಕ ಎಂದು ವರದಿ ಮಾಡಲಾಗಿದೆ.",
        "en": "Warning! This phone number has already been reported as a known scammer on the Chaukanna network.",
    },
}


def load_env() -> None:
    env = HERE / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def filename(warning: str, lang: str) -> str:
    return f"{warning}_{lang}.wav"


def synthesize(text: str, lang_code: str, key: str, speaker: str) -> bytes:
    body = json.dumps({
        "text": text,
        "target_language_code": lang_code,
        "model": MODEL,
        "speaker": speaker,
        "pace": PACE,
        "speech_sample_rate": SAMPLE_RATE,
        "output_audio_codec": "wav",
    }).encode()
    req = urllib.request.Request(
        API_URL, data=body, method="POST",
        headers={"api-subscription-key": key, "Content-Type": "application/json"},
    )
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.load(r)
            audios = data.get("audios") or []
            if not audios:
                raise RuntimeError(f"no audio in response: {str(data)[:200]}")
            return base64.b64decode(audios[0])
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            last = f"HTTP {e.code}: {detail}"
            if e.code not in (429, 500, 502, 503, 504):
                break
        except (urllib.error.URLError, TimeoutError, RuntimeError) as e:
            last = str(e)
        time.sleep(2 ** attempt)
    raise RuntimeError(last)


def duration(path: Path) -> float:
    with wave.open(io.BytesIO(path.read_bytes()), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def generate(force: bool, speaker: str) -> int:
    key = os.environ.get("SARVAM_API_KEY")
    if not key:
        sys.exit("SARVAM_API_KEY missing: put it in .env or the environment")
    OUT_DIR.mkdir(exist_ok=True)
    manifest = {"model": MODEL, "speaker": speaker, "sample_rate": SAMPLE_RATE,
                "files": {}}
    failed = 0
    for warning, scripts in WARNINGS.items():
        manifest["files"][warning] = {}
        for lang, text in scripts.items():
            name = filename(warning, lang)
            path = OUT_DIR / name
            manifest["files"][warning][lang] = name
            if path.exists() and path.stat().st_size > 0 and not force:
                print(f"skip  {name} (exists)")
                continue
            try:
                path.write_bytes(synthesize(text, LANGS[lang], key, speaker))
                print(f"ok    {name}  {duration(path):.2f}s")
            except Exception as e:  # keep going; report at the end
                failed += 1
                print(f"FAIL  {name}: {e}", file=sys.stderr)
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"manifest -> {MANIFEST.relative_to(HERE)}")
    return failed


def verify() -> int:
    bad = 0
    for warning in WARNINGS:
        for lang in LANGS:
            name = filename(warning, lang)
            path = OUT_DIR / name
            if not path.exists():
                print(f"MISSING  {name}"); bad += 1
            elif path.stat().st_size == 0:
                print(f"EMPTY    {name}"); bad += 1
            else:
                try:
                    print(f"OK       {name}  {duration(path):.2f}s  {path.stat().st_size} bytes")
                except Exception as e:
                    print(f"CORRUPT  {name}: {e}"); bad += 1
    if not MANIFEST.exists():
        print("MISSING  manifest.json"); bad += 1
    total = len(WARNINGS) * len(LANGS)
    print(f"{total - bad}/{total} verified" if not bad else f"{bad} problem(s)")
    return bad


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify", action="store_true", help="check all 12 files exist, are non-empty, print durations")
    ap.add_argument("--force", action="store_true", help="regenerate files that already exist")
    ap.add_argument("--speaker", default=SPEAKER, help=f"bulbul:v3 speaker (default {SPEAKER})")
    args = ap.parse_args()
    load_env()
    sys.exit(1 if (verify() if args.verify else generate(args.force, args.speaker)) else 0)


if __name__ == "__main__":
    main()
