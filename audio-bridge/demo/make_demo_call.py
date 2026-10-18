"""Generate the judge-demo scam call: starts as an ordinary courier call, turns into digital arrest.
Sarvam TTS per line (tts_asset_generator.generate.synthesize), joined with pauses so the bridge cuts
one chunk per line. Usage: python demo/make_demo_call.py  ->  demo/scam_call_slow_burn.wav"""
import array, io, os, sys, wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
GEN = Path.home() / "Projects" / "tts_asset_generator"
sys.path.insert(0, str(GEN))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(GEN / ".env")
import generate  # noqa: E402

LINES = [
    "हेलो नमस्ते, मैं ब्लू डार्ट कूरियर से बोल रहा हूँ। आपके नाम से एक पार्सल आया है।",
    "क्या आप अभी घर पर हैं? पता कन्फर्म करना था।",
    "सर, पार्सल मुंबई कस्टम्स में रुका हुआ है, और यह आपके आधार कार्ड से लिंक है।",
    "इसमें ड्रग्स और फेक पासपोर्ट मिले हैं। आपके खिलाफ मनी लॉन्ड्रिंग का केस दर्ज हुआ है।",
    "मैं अभी आपकी कॉल सीबीआई ऑफिसर को ट्रांसफर कर रहा हूँ। यह बात किसी को मत बताइए, फ़ोन मत काटिए।",
    "वेरिफिकेशन के लिए आपके फ़ोन पर एक ओटीपी आया है, वो जल्दी बताइए।",
]
GAP_S = 3.0
SR = 24000


def tts(text: str) -> array.array:
    key = os.environ["SARVAM_API_KEY"]
    last = None
    for speaker in ("aditya", "rahul", "abhilash", "karun", "ritu"):   # a male voice if this model has one
        try:
            raw = generate.synthesize({"text": text, "target_language_code": "hi-IN", "model": generate.MODEL,
                                       "speaker": speaker, "pace": 1.0, "speech_sample_rate": SR}, key)
            with wave.open(io.BytesIO(raw)) as w:
                assert w.getframerate() == SR and w.getnchannels() == 1 and w.getsampwidth() == 2
                return array.array("h", w.readframes(w.getnframes())), speaker
        except Exception as e:      # unknown speaker name for this model: try the next one
            last = e
    raise RuntimeError(f"TTS failed: {last}")


def main() -> None:
    out = array.array("h", [0] * int(SR * 1.0))
    for i, line in enumerate(LINES, 1):
        samples, speaker = tts(line)
        out.extend(samples)
        out.extend([0] * int(SR * GAP_S))
        print(f"line {i}: {len(samples) / SR:.1f}s ({speaker})", flush=True)
    path = HERE / "scam_call_slow_burn.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(SR)
        w.writeframes(out.tobytes())
    print(f"wrote {path} ({len(out) / SR:.0f}s)")


if __name__ == "__main__":
    main()
