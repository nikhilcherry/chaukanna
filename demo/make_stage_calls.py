"""Generate the stage demo's robot calls (stage_lines.py) with Sarvam TTS, one line at a time, joined with
GAP_S of silence so the bridge cuts one chunk per line. Writes demo/stage/<call>.wav and <call>.json (line
start times, used by the run sheet). The scam call has the same lines as
scam_call_slow_burn.wav (make_demo_call.py), in the voice the redial uses.

    python demo/make_stage_calls.py            # all calls that have no WAV yet
    python demo/make_stage_calls.py son --force
"""
import array, io, json, os, sys, wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
GEN = Path.home() / "Projects" / "tts_asset_generator"
sys.path.insert(0, str(GEN))
sys.path.insert(0, str(HERE))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(GEN / ".env")
import generate  # noqa: E402
from stage_lines import CALLS, GAP_S  # noqa: E402

SR = 24000
OUT = HERE / "stage"


def tts(text: str, voices: list[str], lang: str = "hi-IN") -> tuple[array.array, str]:
    key = os.environ["SARVAM_API_KEY"]
    last = None
    for speaker in voices:                     # first voice this model knows wins
        try:
            raw = generate.synthesize({"text": text, "target_language_code": lang, "model": generate.MODEL,
                                       "speaker": speaker, "pace": 1.0, "speech_sample_rate": SR}, key)
            with wave.open(io.BytesIO(raw)) as w:
                assert w.getframerate() == SR and w.getnchannels() == 1 and w.getsampwidth() == 2
                return array.array("h", w.readframes(w.getnframes())), speaker
        except Exception as e:
            last = e
    raise RuntimeError(f"TTS failed for every voice in {voices}: {last}")


def make(name: str, call: dict) -> None:
    out = array.array("h", [0] * int(SR * 0.5))
    timeline, used = [], None
    for line in call["lines"]:
        samples, used = tts(line, [used] if used else call["voice"], call.get("lang", "hi-IN"))   # one voice per call
        timeline.append({"start": round(len(out) / SR, 2), "end": round((len(out) + len(samples)) / SR, 2), "text": line})
        out.extend(samples)
        out.extend([0] * int(SR * GAP_S))
    OUT.mkdir(exist_ok=True)
    with wave.open(str(OUT / f"{name}.wav"), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(SR)
        w.writeframes(out.tobytes())
    (OUT / f"{name}.json").write_text(json.dumps({"call": name, "voice": used, "seconds": round(len(out) / SR, 1),
                                                  "timeline": timeline}, ensure_ascii=False, indent=1))
    print(f"{name}: {len(out) / SR:.1f}s, voice {used}", flush=True)


def main() -> None:
    names = [a for a in sys.argv[1:] if not a.startswith("-")] or [n for n, c in CALLS.items() if "wav" not in c]
    for name in names:
        if (OUT / f"{name}.wav").exists() and "--force" not in sys.argv:
            print(f"{name}: exists (use --force to remake)")
            continue
        make(name, CALLS[name])


if __name__ == "__main__":
    main()
