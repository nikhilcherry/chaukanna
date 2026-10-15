#!/usr/bin/env python3
"""Pre-generate Chaukanna's scam-warning whispers with Sarvam AI TTS.

4 warnings x 3 languages (hi, kn, en) x 2 variants (short < 3 s, full) = 24 WAVs
in output_assets/, plus manifest.json (durations, text, script hashes).

    python3 generate.py                       # build what changed (hash-based)
    python3 generate.py --out ~/Projects/chaukanna_app/assets/audio
                                              # ...and ship into the Flutter app
                                              #    (+ lib/generated/whisper_clips.dart)
    python3 generate.py --verify [--out DIR]  # offline: files, hashes, durations
    python3 generate.py --check               # Sarvam STT round trip vs the scripts
    python3 generate.py --try "Chowkanna" --lang en   # audition one line

A clip is rebuilt only when its script or voice settings (script_hash), the
post-processing settings (post_hash) or the file on disk (sha256) no longer
match manifest.json. Raw TTS responses are cached in .cache/tts/ by
script_hash, so changing trim/loudness settings costs no API calls.

Zero dependencies (stdlib only, Python 3.9+). Reads SARVAM_API_KEY from .env
or the environment.
"""
from __future__ import annotations

import argparse
import base64
import difflib
import fnmatch
import hashlib
import io
import json
import math
import os
import shutil
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import uuid
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "output_assets"
CACHE_DIR = HERE / ".cache"
CHECK_FILE = HERE / "stt_check.json"
MANIFEST_NAME = "manifest.json"
MANIFEST_FORMAT = 2

TTS_URL = "https://api.sarvam.ai/text-to-speech"
STT_URL = "https://api.sarvam.ai/speech-to-text"
MODEL = "bulbul:v3"
STT_MODEL = "saarika:v2.5"
SPEAKER = "ritu"            # calm female bulbul:v3 voice; override with --speaker
SAMPLE_RATE = 24000
PACE = {"short": 1.0, "full": 0.95}   # full clips a touch slower for clarity
SHORT_MAX_MS = 3000         # short clips must be under this, measured after trimming

LANGS = {"hi": "hi-IN", "kn": "kn-IN", "en": "en-IN"}
VARIANTS = ("short", "full")

# Post-processing applied to every raw TTS clip. Changing any value changes
# post_hash, which reprocesses every clip from the raw cache.
POST = {
    "gate_dbfs": -55.0,        # a 5 ms frame louder than this counts as sound
    "lead_ms": 20,             # silence kept before the first sound
    "tail_ms": 60,             # silence kept after the last sound
    "fade_in_ms": 5,
    "fade_out_ms": 10,
    "target_rms_dbfs": -16.0,  # loudness of the speech (frames above -45 dBFS)
    "peak_ceiling_dbfs": -1.0,  # gain is capped so no sample goes above this
}
ACTIVE_GATE_DBFS = -45.0

# warning id -> variant -> language -> what the clip says (shown as a caption).
# Short clips are what a native speaker would blurt out urgently, not
# translations of the full clip.
SCRIPTS = {
    "warn_otp": {
        "short": {
            "hi": "ओटीपी मत बताइए! ये फ्रॉड है।",
            "kn": "ಓಟಿಪಿ ಹೇಳಬೇಡಿ! ಇದು ಮೋಸ.",
            "en": "Don't share your OTP! It's a scam.",
        },
        "full": {
            "hi": "सावधान! किसी को भी अपना ओटीपी या पिन न बताएं। बैंक और पुलिस कभी फ़ोन पर ओटीपी या पिन नहीं मांगते।",
            "kn": "ಎಚ್ಚರಿಕೆ! ನಿಮ್ಮ ಒಟಿಪಿ ಅಥವಾ ಪಿನ್ ಅನ್ನು ಯಾರಿಗೂ ಹೇಳಬೇಡಿ. ಬ್ಯಾಂಕ್ ಅಥವಾ ಪೊಲೀಸರು ಎಂದಿಗೂ ಫೋನ್‌ನಲ್ಲಿ ಒಟಿಪಿ ಅಥವಾ ಪಿನ್ ಕೇಳುವುದಿಲ್ಲ.",
            "en": "Warning! Do not share your OTP or PIN with anyone. Banks and the police never ask for it over a call.",
        },
    },
    "warn_digital_arrest": {
        "short": {
            "hi": "डिजिटल अरेस्ट फ्रॉड है! फ़ोन काटिए।",
            "kn": "ಡಿಜಿಟಲ್ ಅರೆಸ್ಟ್ ಮೋಸ! ಫೋನ್ ಕಟ್ ಮಾಡಿ.",
            "en": "Digital arrest is a scam. Hang up!",
        },
        "full": {
            "hi": "सावधान! पुलिस, सीबीआई और अदालतें कभी फ़ोन या वीडियो कॉल पर डिजिटल अरेस्ट या पूछताछ नहीं करतीं। यह धोखा है। कॉल काट दें।",
            "kn": "ಎಚ್ಚರಿಕೆ! ಪೊಲೀಸರು, ಸಿಬಿಐ ಮತ್ತು ನ್ಯಾಯಾಲಯಗಳು ಎಂದಿಗೂ ಫೋನ್ ಅಥವಾ ವಿಡಿಯೋ ಕರೆಯಲ್ಲಿ ಡಿಜಿಟಲ್ ಅರೆಸ್ಟ್ ಅಥವಾ ವಿಚಾರಣೆ ಮಾಡುವುದಿಲ್ಲ. ಇದು ವಂಚನೆ. ಕರೆಯನ್ನು ಕಟ್ ಮಾಡಿ.",
            "en": "Warning! The police, the CBI and the courts never conduct a digital arrest or interrogation over a phone or video call. This is a scam. Hang up.",
        },
    },
    "warn_secrecy": {
        "short": {
            "hi": "घरवालों से मत छुपाइए! हम उन्हें बता रहे हैं।",
            "kn": "ಮುಚ್ಚಿಡಬೇಡಿ! ಮನೆಯವರಿಗೆ ಹೇಳ್ತಿದ್ದೀವಿ.",
            "en": "Don't keep it secret! We're alerting your family.",
        },
        "full": {
            "hi": "सावधान! यह कॉलर आपको सबसे अलग करने की कोशिश कर रहा है। हम अभी आपके भरोसेमंद परिवार के सदस्य को सूचित कर रहे हैं।",
            "kn": "ಎಚ್ಚರಿಕೆ! ಈ ಕರೆ ಮಾಡಿದವರು ನಿಮ್ಮನ್ನು ಎಲ್ಲರಿಂದ ಪ್ರತ್ಯೇಕಿಸಲು ಪ್ರಯತ್ನಿಸುತ್ತಿದ್ದಾರೆ. ನಾವು ಈಗಲೇ ನಿಮ್ಮ ವಿಶ್ವಾಸಾರ್ಹ ಕುಟುಂಬ ಸದಸ್ಯರಿಗೆ ಮಾಹಿತಿ ನೀಡುತ್ತಿದ್ದೇವೆ.",
            "en": "Warning: this caller is trying to isolate you. We are alerting your trusted family contact right now.",
        },
    },
    "warn_known_scammer": {
        "short": {
            "hi": "सावधान! ये जाना-माना फ्रॉड नंबर है।",
            "kn": "ಎಚ್ಚರ! ಇದು ಮೋಸಗಾರರ ನಂಬರ್.",
            "en": "Careful! This number is a known scammer.",
        },
        "full": {
            "hi": "सावधान! इस फ़ोन नंबर की शिकायत पहले ही चौकन्ना नेटवर्क पर एक जाने-माने ठग के रूप में की जा चुकी है।",
            "kn": "ಎಚ್ಚರಿಕೆ! ಈ ಫೋನ್ ನಂಬರ್ ಅನ್ನು ಚೌಕನ್ನ ನೆಟ್‌ವರ್ಕ್‌ನಲ್ಲಿ ಈಗಾಗಲೇ ಕುಖ್ಯಾತ ವಂಚಕ ಎಂದು ವರದಿ ಮಾಡಲಾಗಿದೆ.",
            "en": "Warning! This phone number has already been reported as a known scammer on the Chaukanna network.",
        },
    },
}

# Spelling fed to TTS where it differs from the caption (pronunciation fixes).
# Keyed by language, then caption substring -> spoken spelling.
# "Chaukanna" alone is read as "Chokanna"; "Chau-kanna" gets the "au" right
# (STT hears "Chaukhanna", the same as for the Devanagari spelling).
PRONOUNCE: dict[str, dict[str, str]] = {
    "en": {"Chaukanna": "Chau-kanna"},
}

# Spellings STT may legitimately return for a word in a script (lowercase).
STT_ALIASES = {
    "chowkanna": "chaukanna",
    "chaukhanna": "chaukanna",   # STT's spelling even for a native चौकन्ना
    # STT sometimes writes acronyms in Latin script inside hi/kn transcripts
    "ओटीपी": "otp", "ಓಟಿಪಿ": "otp", "ಒಟಿಪಿ": "otp",
    "पिन": "pin", "ಪಿನ್": "pin",
}
MATCH_MIN = 0.90            # hi/kn: character similarity needed to pass --check
# STT writes English contractions out in full.
CONTRACTIONS = {
    "don't": "do not", "doesn't": "does not", "can't": "cannot", "won't": "will not",
    "it's": "it is", "we're": "we are", "you're": "you are", "they're": "they are",
    "that's": "that is", "i'm": "i am", "isn't": "is not", "aren't": "are not",
}


# ---------------------------------------------------------------- clip specs

@dataclass(frozen=True)
class Spec:
    clip: str
    variant: str
    lang: str
    text: str     # caption: what the clip says
    say: str      # what is sent to TTS (text + PRONOUNCE fixes)
    speaker: str
    pace: float

    @property
    def file(self) -> str:
        if self.variant == "short":
            return f"{self.clip}_short_{self.lang}.wav"
        return f"{self.clip}_{self.lang}.wav"

    def tts_request(self) -> dict:
        return {
            "text": self.say,
            "target_language_code": LANGS[self.lang],
            "model": MODEL,
            "speaker": self.speaker,
            "pace": self.pace,
            "speech_sample_rate": SAMPLE_RATE,
            "output_audio_codec": "wav",
        }

    @property
    def script_hash(self) -> str:
        return digest(self.tts_request())


def digest(obj) -> str:
    blob = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def post_hash(post: dict | None = None) -> str:
    return digest(post or POST)


def spoken(text: str, lang: str) -> str:
    for caption, say in PRONOUNCE.get(lang, {}).items():
        text = text.replace(caption, say)
    return text


def all_specs(speaker: str = SPEAKER, scripts: dict | None = None) -> list[Spec]:
    out = []
    for clip, variants in (scripts or SCRIPTS).items():
        for variant in VARIANTS:
            for lang in LANGS:
                text = variants[variant][lang]
                out.append(Spec(clip, variant, lang, text, spoken(text, lang),
                                speaker, PACE[variant]))
    return out


def decide(entry: dict | None, spec: Spec, file_sha: str | None,
           p_hash: str, force: bool = False) -> tuple[bool, str]:
    """(rebuild?, reason) for one clip given its manifest entry and file on disk."""
    if force:
        return True, "forced"
    if not entry or file_sha is None:
        return True, "new"
    if entry.get("script_hash") != spec.script_hash:
        return True, "script/voice changed"
    if entry.get("post_hash") != p_hash:
        return True, "post-processing changed"
    if entry.get("sha256") != file_sha:
        return True, "file changed on disk"
    return False, "up to date"


# ------------------------------------------------------------------- audio

def read_wav(data: bytes) -> tuple[array, int]:
    with wave.open(io.BytesIO(data), "rb") as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            raise ValueError(f"expected 16-bit mono, got {w.getsampwidth() * 8}-bit "
                             f"x{w.getnchannels()}")
        sr = w.getframerate()
        samples = array("h")
        samples.frombytes(w.readframes(w.getnframes()))
    if sys.byteorder == "big":
        samples.byteswap()
    return samples, sr


def write_wav(samples: array, sr: int) -> bytes:
    if sys.byteorder == "big":
        samples = array("h", samples)
        samples.byteswap()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(samples.tobytes())
    return buf.getvalue()


def frame_dbfs(samples: array, sr: int, frame_ms: int = 5) -> list[float]:
    n = max(1, sr * frame_ms // 1000)
    out = []
    for i in range(0, len(samples), n):
        chunk = samples[i:i + n]
        ms = sum(x * x for x in chunk) / len(chunk)
        out.append(10 * math.log10(ms / 1073741824.0 + 1e-12))
    return out


def trim(samples: array, sr: int, gate_dbfs: float, lead_ms: int, tail_ms: int) -> array:
    """Cut leading/trailing silence down to lead_ms / tail_ms around the sound."""
    frame = max(1, sr * 5 // 1000)
    loud = [i for i, d in enumerate(frame_dbfs(samples, sr, 5)) if d > gate_dbfs]
    if not loud:
        return array("h", samples)
    start = max(0, loud[0] * frame - sr * lead_ms // 1000)
    end = min(len(samples), (loud[-1] + 1) * frame + sr * tail_ms // 1000)
    return samples[start:end]


def fade(samples: array, sr: int, in_ms: int, out_ms: int) -> array:
    out = array("h", samples)
    n_in = min(len(out), sr * in_ms // 1000)
    n_out = min(len(out), sr * out_ms // 1000)
    for i in range(n_in):
        out[i] = int(out[i] * i / n_in)
    for i in range(n_out):
        j = len(out) - 1 - i
        out[j] = int(out[j] * i / n_out)
    return out


def loudness(samples: array, sr: int) -> tuple[float, float]:
    """(speech RMS in dBFS over frames above ACTIVE_GATE_DBFS, peak in dBFS)."""
    if not samples:
        return -120.0, -120.0
    frames = [d for d in frame_dbfs(samples, sr, 10) if d > ACTIVE_GATE_DBFS]
    if frames:
        rms = 10 * math.log10(sum(10 ** (d / 10) for d in frames) / len(frames))
    else:
        rms = -120.0
    peak = max(abs(max(samples)), abs(min(samples)))
    return rms, 20 * math.log10(max(peak, 1) / 32768.0)


def normalise(samples: array, sr: int, target_dbfs: float, ceiling_dbfs: float) -> array:
    rms, peak = loudness(samples, sr)
    if rms <= -119:
        return array("h", samples)
    gain_db = min(target_dbfs - rms, ceiling_dbfs - peak)
    g = 10 ** (gain_db / 20)
    return array("h", (max(-32768, min(32767, round(x * g))) for x in samples))


def process(raw: bytes, post: dict | None = None) -> tuple[bytes, dict]:
    """Raw TTS WAV -> trimmed, faded, loudness-normalised WAV + its stats."""
    p = post or POST
    samples, sr = read_wav(raw)
    samples = trim(samples, sr, p["gate_dbfs"], p["lead_ms"], p["tail_ms"])
    samples = fade(samples, sr, p["fade_in_ms"], p["fade_out_ms"])
    samples = normalise(samples, sr, p["target_rms_dbfs"], p["peak_ceiling_dbfs"])
    return write_wav(samples, sr), stats(samples, sr)


def stats(samples: array, sr: int) -> dict:
    rms, peak = loudness(samples, sr)
    return {"duration_ms": round(len(samples) * 1000 / sr),
            "rms_dbfs": round(rms, 1), "peak_dbfs": round(peak, 1)}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha(path: Path) -> str | None:
    return sha256(path.read_bytes()) if path.is_file() else None


# ------------------------------------------------------------------ Sarvam

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


def api_key() -> str:
    key = os.environ.get("SARVAM_API_KEY")
    if not key:
        sys.exit("SARVAM_API_KEY missing: put it in .env or the environment")
    return key


def _call(req: urllib.request.Request) -> dict:
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}"
            if e.code not in (429, 500, 502, 503, 504):
                break
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            last = str(e)
        time.sleep(2 ** attempt)
    raise RuntimeError(last)


def synthesize(request: dict, key: str) -> bytes:
    req = urllib.request.Request(
        TTS_URL, data=json.dumps(request).encode(), method="POST",
        headers={"api-subscription-key": key, "Content-Type": "application/json"})
    audios = _call(req).get("audios") or []
    if not audios:
        raise RuntimeError("no audio in TTS response")
    return base64.b64decode(audios[0])


def transcribe(wav: bytes, lang: str, key: str) -> str:
    boundary = uuid.uuid4().hex
    fields = {"model": STT_MODEL, "language_code": LANGS[lang]}
    body = b"".join(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        for k, v in fields.items())
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
             f'filename="clip.wav"\r\nContent-Type: audio/wav\r\n\r\n').encode()
    body += wav + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        STT_URL, data=body, method="POST",
        headers={"api-subscription-key": key,
                 "Content-Type": f"multipart/form-data; boundary={boundary}"})
    return _call(req).get("transcript", "")


def raw_audio(request: dict, key_fn, force: bool = False) -> tuple[bytes, bool]:
    """Raw TTS audio for a request, from .cache/tts/ when possible. (audio, was_api_call)"""
    path = CACHE_DIR / "tts" / f"{digest(request)}.wav"
    if path.is_file() and not force:
        return path.read_bytes(), False
    audio = synthesize(request, key_fn())
    read_wav(audio)  # fail now on a bad response rather than mid-processing
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(audio)
    return audio, True


# ---------------------------------------------------------------- manifest

def load_manifest(directory: Path) -> dict:
    path = directory / MANIFEST_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def manifest_entry(spec: Spec, wav: bytes, st: dict) -> dict:
    entry = {"clip": spec.clip, "variant": spec.variant, "lang": spec.lang,
             "text": spec.text}
    if spec.say != spec.text:
        entry["say"] = spec.say
    entry.update(st)
    entry.update({"pace": spec.pace, "script_hash": spec.script_hash,
                  "post_hash": post_hash(), "sha256": sha256(wav)})
    return entry


def build_manifest(specs: list[Spec], entries: dict, speaker: str) -> dict:
    files: dict = {}
    short: dict = {}
    for s in specs:
        (short if s.variant == "short" else files).setdefault(s.clip, {})[s.lang] = s.file
    return {
        "format": MANIFEST_FORMAT,
        "generator": "tts_asset_generator/generate.py",
        "model": MODEL, "speaker": speaker, "sample_rate": SAMPLE_RATE,
        "short_max_ms": SHORT_MAX_MS,
        "post": POST,
        "files": files,          # full clips: clip -> lang -> file (format 1 shape)
        "short_files": short,    # short clips: clip -> lang -> file
        "clips": {s.file: entries[s.file] for s in specs},
    }


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# -------------------------------------------------------------------- Dart

def dart_str(s: str) -> str:
    s = s.replace("\\", "\\\\").replace("$", "\\$").replace("\n", "\\n")
    if "'" in s and '"' not in s:
        return f'"{s}"'
    return "'" + s.replace("'", "\\'") + "'"


def render_dart(manifest: dict) -> str:
    clips = list(manifest["clips"].values())
    ids = list(dict.fromkeys(c["clip"] for c in clips))
    langs = list(dict.fromkeys(c["lang"] for c in clips))

    def arg(name: str, value: str) -> str:
        # what `dart format` does: a value that would overflow 80 columns
        # moves to its own line, indented 4 more
        line = f"    {name}: {value},\n"
        return line if len(line) - 1 <= 80 else f"    {name}:\n        {value},\n"

    items = "".join(
        "  WhisperClipInfo(\n"
        + arg("clip", dart_str(c["clip"]))
        + arg("lang", dart_str(c["lang"]))
        + arg("variant", dart_str(c["variant"]))
        + arg("asset", dart_str("assets/audio/" + name))
        + arg("text", dart_str(c["text"]))
        + arg("durationMs", str(int(c["duration_ms"])))
        + "  ),\n"
        for name, c in manifest["clips"].items())

    def str_list(xs):
        one = "[" + ", ".join(dart_str(x) for x in xs) + "]"
        return one if len(one) < 50 else "[\n" + "".join(f"  {dart_str(x)},\n" for x in xs) + "]"

    return f"""\
// GENERATED by tts_asset_generator/generate.py. Do not edit by hand.
// Voice: Sarvam {manifest['model']}, speaker {manifest['speaker']}.
// Regenerate: python3 generate.py --out <chaukanna_app>/assets/audio

/// One pre-generated whisper warning bundled under assets/audio/.
class WhisperClipInfo {{
  const WhisperClipInfo({{
    required this.clip,
    required this.lang,
    required this.variant,
    required this.asset,
    required this.text,
    required this.durationMs,
  }});

  /// Warning id, as in Verdict.recommended_whisper_clip (e.g. 'warn_otp').
  final String clip;

  /// 'hi', 'kn' or 'en'.
  final String lang;

  /// 'short' (under {manifest['short_max_ms'] / 1000:g} s, play first) or 'full'.
  final String variant;

  /// Flutter asset key, e.g. 'assets/audio/warn_otp_short_hi.wav'.
  final String asset;

  /// What the clip says (use it as an on-screen caption).
  final String text;

  /// Measured playback length in milliseconds.
  final int durationMs;

  Duration get duration => Duration(milliseconds: durationMs);
}}

/// Warning ids that have clips.
const List<String> kWhisperClipIds = {str_list(ids)};

/// Languages that have clips. Anything else falls back to 'en'.
const List<String> kWhisperLangs = {str_list(langs)};

const List<WhisperClipInfo> kWhisperClips = [
{items}];

/// The [variant] ('short' or 'full') of [clip] in [lang], falling back to
/// English when [lang] has no clip. Null for unknown clips, including 'none'.
WhisperClipInfo? whisperClip(
  String clip,
  String lang, {{
  String variant = 'short',
}}) {{
  WhisperClipInfo? find(String l) {{
    for (final c in kWhisperClips) {{
      if (c.clip == clip && c.lang == l && c.variant == variant) return c;
    }}
    return null;
  }}

  return find(lang) ?? find('en');
}}

/// Every clip for [lang] (English fallback), e.g. to preload at call start.
List<WhisperClipInfo> whisperClipsForLang(String lang) => [
  for (final id in kWhisperClipIds)
    for (final variant in const ['short', 'full'])
      ?whisperClip(id, lang, variant: variant),
];
"""


def dart_target(directory: Path, explicit: Path | None) -> Path | None:
    """Where the Dart file goes for a mirror dir: --dart, or <flutter root>/lib/generated."""
    if explicit:
        return explicit
    d = directory.resolve()
    if d.name == "audio" and d.parent.name == "assets" and (d.parent.parent / "pubspec.yaml").is_file():
        return d.parent.parent / "lib" / "generated" / "whisper_clips.dart"
    return None


# ------------------------------------------------------------------ build

def build(specs: list[Spec], speaker: str, force: bool, only: str | None) -> tuple[dict, int]:
    OUT_DIR.mkdir(exist_ok=True)
    old = load_manifest(OUT_DIR).get("clips", {})
    p_hash = post_hash()
    key: list[str] = []

    def key_fn():
        if not key:
            key.append(api_key())
        return key[0]

    entries, failed, calls = {}, 0, 0
    for spec in specs:
        path = OUT_DIR / spec.file
        entry = old.get(spec.file)
        selected = only is None or fnmatch.fnmatch(spec.file, only)
        rebuild, reason = decide(entry, spec, file_sha(path), p_hash, force and selected)
        if not rebuild:
            entries[spec.file] = {**entry, "text": spec.text}  # caption may differ
            continue
        if not selected:
            if entry and path.is_file():
                entries[spec.file] = entry  # keep as is; --verify reports it stale
            print(f"SKIP   {spec.file}: {reason} (outside --only)")
            continue
        try:
            raw, called = raw_audio(spec.tts_request(), key_fn, force=force)
            calls += called
            wav, st = process(raw)
            path.write_bytes(wav)
            entries[spec.file] = manifest_entry(spec, wav, st)
            flag = ""
            if spec.variant == "short" and st["duration_ms"] >= SHORT_MAX_MS:
                flag = f"  TOO LONG (>= {SHORT_MAX_MS} ms)"
            print(f"built  {spec.file:32s} {st['duration_ms']:5d} ms  "
                  f"{st['rms_dbfs']:6.1f} dB rms  {'api' if called else 'cache'}  "
                  f"({reason}){flag}")
        except Exception as e:  # keep going; report at the end
            failed += 1
            print(f"FAIL   {spec.file}: {e}", file=sys.stderr)
    present = [s for s in specs if s.file in entries]
    manifest = build_manifest(present, entries, speaker)
    write_json(OUT_DIR / MANIFEST_NAME, manifest)
    print(f"{len(present)}/{len(specs)} clips in {OUT_DIR.name}/  "
          f"({calls} TTS call{'s' * (calls != 1)})")
    return manifest, failed + len(specs) - len(present)


def mirror(manifest: dict, directory: Path, dart: Path | None) -> None:
    """Copy clips + manifest into directory; drop clips its old manifest listed
    that no longer exist; write the Dart file."""
    directory.mkdir(parents=True, exist_ok=True)
    if directory.resolve() != OUT_DIR.resolve():
        old = load_manifest(directory).get("clips", {})
        copied = 0
        for name, entry in manifest["clips"].items():
            if file_sha(directory / name) != entry["sha256"]:
                shutil.copyfile(OUT_DIR / name, directory / name)
                copied += 1
        removed = [n for n in old if n not in manifest["clips"] and (directory / n).is_file()]
        for name in removed:
            (directory / name).unlink()
        write_json(directory / MANIFEST_NAME, manifest)
        print(f"mirror {directory}: {copied} copied, {len(removed)} removed")
    if dart:
        dart.parent.mkdir(parents=True, exist_ok=True)
        text = render_dart(manifest)
        if not dart.is_file() or dart.read_text(encoding="utf-8") != text:
            dart.write_text(text, encoding="utf-8")
            print(f"dart   {dart}: written")
        else:
            print(f"dart   {dart}: up to date")


# ----------------------------------------------------------------- verify

def verify(specs: list[Spec], directory: Path, dart: Path | None) -> int:
    print(f"== {directory}")
    manifest = load_manifest(directory)
    entries = manifest.get("clips", {})
    if not manifest:
        print(f"MISSING  {MANIFEST_NAME}")
    p_hash = post_hash()
    bad = 0 if manifest else 1
    for spec in specs:
        path = directory / spec.file
        entry = entries.get(spec.file)
        problem = ""
        info = ""
        if not path.is_file() or path.stat().st_size == 0:
            problem = "MISSING" if not path.is_file() else "EMPTY"
        else:
            data = path.read_bytes()
            try:
                samples, sr = read_wav(data)
                ms = round(len(samples) * 1000 / sr)
                rms, peak = loudness(samples, sr)
                info = f"{ms:5d} ms  {rms:6.1f} dB rms  {peak:5.1f} dB peak"
                if sr != SAMPLE_RATE:
                    problem = f"RATE {sr}"
                elif spec.variant == "short" and ms >= SHORT_MAX_MS:
                    problem = "TOO LONG"
                elif not entry:
                    problem = "UNLISTED"
                elif entry.get("sha256") != sha256(data):
                    problem = "CHANGED"
                elif entry.get("script_hash") != spec.script_hash:
                    problem = "STALE"
                elif entry.get("post_hash") != p_hash:
                    problem = "STALE-POST"
                elif entry.get("duration_ms") != ms:
                    problem = "DURATION"
            except (wave.Error, ValueError, EOFError) as e:
                problem = f"CORRUPT ({e})"
        bad += bool(problem)
        print(f"{problem or 'OK':10s} {spec.file:32s} {info}")
    if dart:
        if not dart.is_file():
            print(f"MISSING    {dart}")
            bad += 1
        elif manifest and dart.read_text(encoding="utf-8") != render_dart(manifest):
            print(f"STALE      {dart} (does not match {MANIFEST_NAME})")
            bad += 1
        else:
            print(f"OK         {dart}")
    print(f"{len(specs) - bad}/{len(specs)} verified" if not bad else f"{bad} problem(s)")
    return bad


# ------------------------------------------------------------------ check

def norm_words(text: str) -> list[str]:
    """Lowercased words with punctuation, nukta, ZWJ/ZWNJ and chandrabindu
    differences removed, so spelling variants STT returns still match."""
    s = unicodedata.normalize("NFC", text).lower()
    s = unicodedata.normalize("NFD", s)  # split precomposed nukta letters
    s = s.replace("\u093c", "").replace("\u0901", "\u0902")
    s = s.replace("\u200c", "").replace("\u200d", "")
    s = unicodedata.normalize("NFC", s).replace("’", "'")
    for short, full in CONTRACTIONS.items():
        s = s.replace(short, full)
    s = "".join(" " if unicodedata.category(ch)[0] in "PS" else ch for ch in s)
    return [STT_ALIASES.get(w, w) for w in s.split()]


def score(expected: str, heard: str, lang: str) -> dict:
    e, h = norm_words(expected), norm_words(heard)
    ratio = difflib.SequenceMatcher(None, " ".join(e), " ".join(h)).ratio()
    diffs = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, e, h).get_opcodes():
        if op != "equal":
            diffs.append(f"{' '.join(e[i1:i2]) or '∅'} -> {' '.join(h[j1:j2]) or '∅'}")
    # English STT is reliable enough to demand every word; Indic STT varies
    # spelling, so hi/kn pass on overall similarity.
    ok = not diffs if lang == "en" else ratio >= MATCH_MIN
    return {"score": round(ratio, 3), "ok": ok, "diffs": diffs}


def check(specs: list[Spec], only: str | None, recheck: bool) -> int:
    try:
        cache = json.loads(CHECK_FILE.read_text(encoding="utf-8")).get("results", {})
    except (OSError, ValueError):
        cache = {}
    results, bad, calls, checked = {}, 0, 0, 0
    key = None
    for spec in specs:
        path = OUT_DIR / spec.file
        if only and not fnmatch.fnmatch(spec.file, only):
            if spec.file in cache:
                results[spec.file] = cache[spec.file]
            continue
        checked += 1
        if not path.is_file():
            print(f"MISSING   {spec.file}")
            bad += 1
            continue
        data = path.read_bytes()
        prev = cache.get(spec.file, {})
        if (not recheck and prev.get("sha256") == sha256(data)
                and prev.get("stt_model") == STT_MODEL and "heard" in prev):
            heard = prev["heard"]
        else:
            key = key or api_key()
            try:
                heard = transcribe(data, spec.lang, key)
            except RuntimeError as e:  # keep going; one bad call shouldn't lose the rest
                print(f"ERROR     {spec.file}: {e}", file=sys.stderr)
                bad += 1
                continue
            finally:
                calls += 1
        res = score(spec.text, heard, spec.lang)
        results[spec.file] = {"sha256": sha256(data), "stt_model": STT_MODEL,
                              "expected": spec.text, "heard": heard, **res}
        bad += not res["ok"]
        diff = ("  [" + "; ".join(res["diffs"]) + "]") if res["diffs"] else ""
        print(f"{'OK' if res['ok'] else 'MISMATCH':9s} {spec.file:32s} "
              f"{res['score']:.3f}{diff}")
    write_json(CHECK_FILE, {"stt_model": STT_MODEL, "results": results})
    print(f"{checked - bad}/{checked} match  ({calls} STT call"
          f"{'s' * (calls != 1)}; details in {CHECK_FILE.name})")
    return bad


def audition(text: str, lang: str, pace: float, speaker: str) -> int:
    """Synthesize one line, process it like a clip, print duration + what STT hears."""
    spec = Spec("try", "short", lang, text, text, speaker, pace)
    raw, called = raw_audio(spec.tts_request(), api_key)
    wav, st = process(raw)
    path = CACHE_DIR / "try" / f"{spec.script_hash}_{lang}.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(wav)
    heard = transcribe(wav, lang, api_key())
    res = score(text, heard, lang)
    print(f"{st['duration_ms']} ms  {st['rms_dbfs']} dB rms  score {res['score']:.3f}  "
          f"{'ok' if res['ok'] else 'MISMATCH'}  ({'api' if called else 'cache'})")
    print(f"heard: {heard}")
    if res["diffs"]:
        print("diffs: " + "; ".join(res["diffs"]))
    print(f"wav:   {path}")
    return 0 if res["ok"] else 1


# ------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", action="append", type=Path, default=[], metavar="DIR",
                    help="also mirror clips + manifest into DIR (repeatable); for "
                         "<flutter app>/assets/audio the Dart file is written too")
    ap.add_argument("--dart", type=Path, help="write the Dart clip table here")
    ap.add_argument("--verify", action="store_true",
                    help="offline check of files, hashes and durations (and --out dirs)")
    ap.add_argument("--check", action="store_true",
                    help="round-trip clips through Sarvam STT and score them against the scripts")
    ap.add_argument("--recheck", action="store_true", help="--check without the result cache")
    ap.add_argument("--force", action="store_true", help="re-synthesize, ignoring every cache")
    ap.add_argument("--only", metavar="GLOB", help="limit build/check to matching files, "
                                                   "e.g. 'warn_otp_short_*'")
    ap.add_argument("--speaker", default=SPEAKER, help=f"bulbul:v3 speaker (default {SPEAKER})")
    ap.add_argument("--try", dest="try_text", metavar="TEXT", help="audition one line")
    ap.add_argument("--lang", default="en", choices=sorted(LANGS), help="language for --try")
    ap.add_argument("--pace", type=float, default=PACE["short"], help="pace for --try")
    args = ap.parse_args(argv)
    load_env()
    specs = all_specs(args.speaker)

    if args.try_text:
        return audition(args.try_text, args.lang, args.pace, args.speaker)
    targets = [(d, dart_target(d, args.dart)) for d in args.out]
    if args.dart and not args.out:
        targets = [(OUT_DIR, args.dart)]
    if args.verify:
        bad = verify(specs, OUT_DIR, args.dart if not args.out else None)
        for d, dart in targets:
            if d.resolve() != OUT_DIR.resolve():
                bad += verify(specs, d, dart)
        return 1 if bad else 0
    if args.check:
        return 1 if check(specs, args.only, args.recheck) else 0

    manifest, failed = build(specs, args.speaker, args.force, args.only)
    if failed:
        print(f"{failed} clip(s) failed or missing; not mirroring", file=sys.stderr)
        return 1
    for d, dart in targets:
        mirror(manifest, d, dart)
    return 0


if __name__ == "__main__":
    sys.exit(main())
