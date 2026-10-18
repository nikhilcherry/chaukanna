"""Make a SYNTHETIC Hinglish digital-arrest scam call with Sarvam TTS (bulbul:v3).

    python tools/make_sample_call.py            # -> samples/synthetic_scam_call_hinglish.wav (+ .json)
    python tools/make_sample_call.py --innocent # -> samples/synthetic_innocent_call_hinglish.wav

Stereo 16 kHz, caller on the left, victim on the right (the --record-dir layout), so replay
hears two separate speakers. This is TTS speech, not a real call: use it for wiring, STT-mode
comparisons and as a last-resort demo track, and say so if it is ever shown.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import wave
from pathlib import Path

import httpx
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from audio import load_wav_channels  # noqa: E402

TTS_URL = "https://api.sarvam.ai/text-to-speech"
SR = 16000

SCAM = [
    ("caller", "नमस्ते, मैं CBI Mumbai से Inspector Sharma बोल रहा हूँ।"),
    ("victim", "जी? कौन बोल रहे हैं?"),
    ("caller", "आपके Aadhaar card से एक parcel भेजा गया है, उसमें drugs और fake passports मिले हैं। यह money laundering case है।"),
    ("victim", "लेकिन मैंने तो कोई parcel नहीं भेजा।"),
    ("caller", "आप अभी digital arrest में हैं। यह बात किसी को मत बताइए, family को भी नहीं, और call मत काटिए।"),
    ("victim", "ठीक है sir, मैं किसी को नहीं बताऊँगी।"),
    ("caller", "Verification के लिए आपके phone पर एक OTP आया है, वो मुझे अभी बताइए।"),
    ("victim", "OTP है चार पाँच छह सात आठ नौ।"),
]
INNOCENT = [
    ("caller", "नमस्ते aunty, मैं Amazon delivery से Ravi बोल रहा हूँ।"),
    ("victim", "हाँ बेटा, बोलो।"),
    ("caller", "आपका parcel आ गया है, मैं gate पर हूँ। आप नीचे आ सकती हैं क्या?"),
    ("victim", "हाँ, दो मिनट में आती हूँ।"),
]
VOICES = {"caller": "ashutosh", "victim": "roopa"}


def tts(text: str, speaker: str, key: str) -> np.ndarray:
    r = httpx.post(TTS_URL, headers={"api-subscription-key": key}, timeout=60, json={
        "text": text, "target_language_code": "hi-IN", "model": "bulbul:v3", "speaker": speaker,
        "pace": 1.0, "speech_sample_rate": SR})
    r.raise_for_status()
    wav = base64.b64decode(r.json()["audios"][0])
    tmp = Path("/dev/shm" if Path("/dev/shm").exists() else ".") / f"_tts_{os.getpid()}.wav"
    tmp.write_bytes(wav)
    try:
        pcm = load_wav_channels(str(tmp))[0]
    finally:
        tmp.unlink()
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float64)


def build(script, key: str, gap: float = 0.6) -> tuple[np.ndarray, list[dict]]:
    tracks = {"caller": [], "victim": []}
    t, timeline = 0.4, []
    for speaker, text in script:
        a = tts(text, VOICES[speaker], key)
        timeline.append({"speaker": speaker, "start": round(t, 2), "end": round(t + len(a) / SR, 2), "text": text})
        tracks[speaker].append((t, a))
        t += len(a) / SR + gap
    n = int((t + 0.5) * SR)
    out = np.zeros((n, 2))
    for ch, speaker in enumerate(("caller", "victim")):
        for start, a in tracks[speaker]:
            i = int(start * SR)
            out[i:i + len(a), ch] += a
    return np.clip(out, -32768, 32767).astype(np.int16), timeline


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("--innocent", action="store_true")
    ap.add_argument("--out-dir", default=str(Path(__file__).resolve().parent.parent / "samples"))
    a = ap.parse_args()
    key = os.getenv("SARVAM_API_KEY") or sys.exit("SARVAM_API_KEY is not set")
    name = "synthetic_innocent_call_hinglish" if a.innocent else "synthetic_scam_call_hinglish"
    stereo, timeline = build(INNOCENT if a.innocent else SCAM, key)
    out = Path(a.out_dir)
    out.mkdir(exist_ok=True)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(stereo.tobytes())
    (out / f"{name}.wav").write_bytes(buf.getvalue())
    (out / f"{name}.json").write_text(json.dumps({
        "synthetic": True, "made_with": "Sarvam TTS bulbul:v3 (caller ashutosh, victim roopa)",
        "layout": "stereo: left = caller, right = victim", "timeline": timeline}, ensure_ascii=False, indent=1))
    print(f"wrote {out / name}.wav ({len(stereo) / SR:.1f}s, SYNTHETIC)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
