"""Offline tests for generate.py (no Sarvam calls): hashing and the rebuild
decision, trimming/loudness, manifest + Dart generation, mirroring, scoring.

    python3 -m unittest discover -s tests -v
"""
import contextlib
import io
import json
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import generate as g  # noqa: E402

SR = g.SAMPLE_RATE


def tone(ms: int, dbfs: float, hz: float = 440.0) -> array:
    amp = 32768 * 10 ** (dbfs / 20) * math.sqrt(2)  # sine RMS = amp / sqrt(2)
    n = SR * ms // 1000
    return array("h", (round(amp * math.sin(2 * math.pi * hz * i / SR)) for i in range(n)))


def silence(ms: int) -> array:
    return array("h", bytes(2 * (SR * ms // 1000)))


def fake_raw(ms_lead=300, ms_speech=400, ms_tail=300, dbfs=-24.0) -> bytes:
    return g.write_wav(silence(ms_lead) + tone(ms_speech, dbfs) + silence(ms_tail), SR)


def run_verify(specs, directory, dart=None):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        bad = g.verify(specs, directory, dart)
    return bad, out.getvalue()


MINI_SCRIPTS = {
    "warn_otp": {
        "short": {"hi": "ओटीपी मत बताइए!", "kn": "ಓಟಿಪಿ ಹೇಳಬೇಡಿ!", "en": "Don't share your OTP!"},
        "full": {"hi": "सावधान!", "kn": "ಎಚ್ಚರಿಕೆ!", "en": "Warning! $5 isn't 'free'."},
    },
}


class Sandbox(unittest.TestCase):
    """Points OUT_DIR/CACHE_DIR/CHECK_FILE at a temp dir and replaces the TTS call."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = (g.OUT_DIR, g.CACHE_DIR, g.CHECK_FILE, g.synthesize, g.SCRIPTS)
        g.OUT_DIR = self.tmp / "out"
        g.CACHE_DIR = self.tmp / "cache"
        g.CHECK_FILE = self.tmp / "stt_check.json"
        g.SCRIPTS = MINI_SCRIPTS
        self.calls = []

        def fake_synth(request, key):
            self.calls.append(request["text"])
            return fake_raw()

        g.synthesize = fake_synth
        g.os.environ.setdefault("SARVAM_API_KEY", "test-key")

    def tearDown(self):
        g.OUT_DIR, g.CACHE_DIR, g.CHECK_FILE, g.synthesize, g.SCRIPTS = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build(self, scripts=None, force=False, only=None):
        specs = g.all_specs(scripts=scripts or MINI_SCRIPTS)
        with contextlib.redirect_stdout(io.StringIO()):
            manifest, failed = g.build(specs, g.SPEAKER, force, only)
        self.assertEqual(failed, 0)
        return specs, manifest

    def verify(self, specs, directory=None, dart=None):
        return run_verify(specs, directory or g.OUT_DIR, dart)


class HashTests(unittest.TestCase):
    def spec(self, **kw):
        base = dict(clip="warn_otp", variant="short", lang="en", text="Hi", say="Hi",
                    speaker="ritu", pace=1.0)
        base.update(kw)
        return g.Spec(**base)

    def test_hash_covers_script_and_voice(self):
        h = self.spec().script_hash
        for change in (dict(say="Hi!"), dict(speaker="anushka"), dict(pace=0.9),
                       dict(lang="hi")):
            self.assertNotEqual(h, self.spec(**change).script_hash, change)

    def test_caption_only_change_keeps_audio(self):
        # PRONOUNCE fixes mean caption and spoken text can differ; only the
        # spoken text (what TTS hears) decides the audio
        self.assertEqual(self.spec(text="Chaukanna", say="Chau-kanna").script_hash,
                         self.spec(text="CHAUKANNA", say="Chau-kanna").script_hash)

    def test_hash_is_stable(self):
        self.assertEqual(self.spec().script_hash, self.spec().script_hash)
        self.assertEqual(len(self.spec().script_hash), 16)

    def test_pronounce_applies_to_spoken_text_only(self):
        en = [s for s in g.all_specs() if "Chaukanna" in s.text and s.lang == "en"]
        self.assertTrue(en)
        for s in en:
            self.assertIn("Chau-kanna", s.say)
            self.assertNotIn("Chau-kanna", s.text)

    def test_decide(self):
        s = self.spec()
        good = {"script_hash": s.script_hash, "post_hash": "p", "sha256": "f"}
        cases = [
            (None, "f", "p", False, (True, "new")),
            (good, None, "p", False, (True, "new")),
            ({**good, "script_hash": "x"}, "f", "p", False, (True, "script/voice changed")),
            (good, "f", "other", False, (True, "post-processing changed")),
            (good, "edited", "p", False, (True, "file changed on disk")),
            (good, "f", "p", True, (True, "forced")),
            (good, "f", "p", False, (False, "up to date")),
        ]
        for entry, sha, p_hash, force, want in cases:
            self.assertEqual(g.decide(entry, s, sha, p_hash, force), want)


class AudioTests(unittest.TestCase):
    def test_wav_roundtrip(self):
        x = tone(50, -20)
        y, sr = g.read_wav(g.write_wav(x, SR))
        self.assertEqual((list(x), SR), (list(y), sr))

    def test_trim_keeps_short_lead_and_tail(self):
        x = silence(400) + tone(500, -20) + silence(300)
        y = g.trim(x, SR, gate_dbfs=-55, lead_ms=20, tail_ms=60)
        self.assertAlmostEqual(len(y) / SR * 1000, 500 + 20 + 60, delta=6)
        lead = next(i for i, v in enumerate(y) if abs(v) > 0)
        self.assertAlmostEqual(lead / SR * 1000, 20, delta=6)

    def test_trim_silent_and_empty_input(self):
        self.assertEqual(len(g.trim(silence(200), SR, -55, 20, 60)), SR * 200 // 1000)
        self.assertEqual(len(g.trim(array("h"), SR, -55, 20, 60)), 0)

    def test_normalise_hits_target(self):
        y = g.normalise(tone(500, -30), SR, target_dbfs=-16, ceiling_dbfs=-1)
        rms, peak = g.loudness(y, SR)
        self.assertAlmostEqual(rms, -16, delta=0.2)
        self.assertLess(peak, -1)

    def test_normalise_respects_peak_ceiling(self):
        x = tone(500, -30)
        x[1000] = 30000  # a single spike: gain must stop at the ceiling
        _, peak = g.loudness(g.normalise(x, SR, -10, -1), SR)
        self.assertLessEqual(peak, -1 + 0.01)

    def test_process_end_to_end(self):
        wav, st = g.process(fake_raw(ms_lead=350, ms_speech=400, ms_tail=500))
        self.assertAlmostEqual(st["duration_ms"], 400 + 20 + 60, delta=6)
        self.assertAlmostEqual(st["rms_dbfs"], g.POST["target_rms_dbfs"], delta=0.3)
        self.assertEqual(g.read_wav(wav)[1], SR)
        samples, _ = g.read_wav(wav)
        self.assertEqual(samples[0], 0)   # faded in
        self.assertEqual(samples[-1], 0)  # faded out


class BuildTests(Sandbox):
    def test_build_then_noop(self):
        specs, manifest = self.build()
        self.assertEqual(len(self.calls), 6)
        self.assertEqual(len(manifest["clips"]), 6)
        self.calls.clear()
        self.build()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.verify(specs)[0], 0)

    def test_edited_script_rebuilds_only_that_clip(self):
        self.build()
        edited = json.loads(json.dumps(MINI_SCRIPTS))
        edited["warn_otp"]["short"]["kn"] = "ಓಟಿಪಿ ಹೇಳಲೇಬೇಡಿ!"
        stale_specs = g.all_specs(scripts=edited)
        bad, out = self.verify(stale_specs)
        self.assertEqual(bad, 1)
        self.assertIn("STALE", out)
        self.calls.clear()
        self.build(scripts=edited)
        self.assertEqual(self.calls, ["ಓಟಿಪಿ ಹೇಳಲೇಬೇಡಿ!"])
        self.assertEqual(self.verify(stale_specs)[0], 0)

    def test_post_change_reprocesses_from_cache(self):
        self.build()
        self.calls.clear()
        saved = dict(g.POST)
        try:
            g.POST["tail_ms"] = 100
            specs, manifest = self.build()
        finally:
            g.POST.clear()
            g.POST.update(saved)
        self.assertEqual(self.calls, [])  # raw cache, no API calls
        self.assertTrue(all(e["post_hash"] != g.post_hash() for e in manifest["clips"].values()))

    def test_hand_edited_file_is_rebuilt(self):
        specs, _ = self.build()
        path = g.OUT_DIR / specs[0].file
        path.write_bytes(g.write_wav(silence(10), SR))
        bad, out = self.verify(specs)
        self.assertIn("CHANGED", out)
        self.build()
        self.assertEqual(self.verify(specs)[0], 0)

    def test_short_clip_too_long_is_flagged(self):
        specs, _ = self.build()
        short = next(s for s in specs if s.variant == "short")
        g.synthesize = lambda request, key: fake_raw(ms_speech=3500)
        with contextlib.redirect_stdout(io.StringIO()):
            g.build(specs, g.SPEAKER, force=True, only=short.file)
        bad, out = self.verify(specs)
        self.assertIn("TOO LONG", out)

    def test_manifest_shape(self):
        specs, m = self.build()
        self.assertEqual(m["format"], g.MANIFEST_FORMAT)
        self.assertEqual(m["files"]["warn_otp"]["kn"], "warn_otp_kn.wav")
        self.assertEqual(m["short_files"]["warn_otp"]["kn"], "warn_otp_short_kn.wav")
        e = m["clips"]["warn_otp_short_en.wav"]
        for k in ("clip", "variant", "lang", "text", "duration_ms", "script_hash",
                  "post_hash", "sha256", "rms_dbfs", "peak_dbfs"):
            self.assertIn(k, e)
        on_disk = json.loads((g.OUT_DIR / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk, m)

    def test_mirror_prunes_only_files_it_listed(self):
        specs, m = self.build()
        app = self.tmp / "app"
        audio = app / "assets" / "audio"
        audio.mkdir(parents=True)
        (app / "pubspec.yaml").write_text("name: x\n")
        (audio / "alarm.wav").write_bytes(b"not ours")
        (audio / "warn_old_en.wav").write_bytes(b"ours, retired")
        g.write_json(audio / "manifest.json", {"clips": {"warn_old_en.wav": {}}})
        dart = g.dart_target(audio, None)
        self.assertEqual(dart, (app / "lib" / "generated" / "whisper_clips.dart").resolve())
        with contextlib.redirect_stdout(io.StringIO()):
            g.mirror(m, audio, dart)
        self.assertTrue((audio / "alarm.wav").exists())
        self.assertFalse((audio / "warn_old_en.wav").exists())
        self.assertEqual(self.verify(specs, audio, dart)[0], 0)
        dart.write_text("// hand edited\n")
        bad, out = self.verify(specs, audio, dart)
        self.assertEqual(bad, 1)

    def test_dart_target_needs_flutter_layout(self):
        self.assertIsNone(g.dart_target(self.tmp, None))
        self.assertEqual(g.dart_target(self.tmp, Path("x.dart")), Path("x.dart"))


class DartTests(Sandbox):
    def test_render(self):
        _, m = self.build()
        src = g.render_dart(m)
        self.assertEqual(src.count("  WhisperClipInfo(\n"), 6)
        self.assertIn("WhisperClipInfo? whisperClip(", src)
        self.assertIn("String variant = 'short'", src)
        self.assertIn("find(lang) ?? find('en')", src)
        self.assertIn("assets/audio/warn_otp_short_kn.wav", src)
        # `$` escaped, apostrophes switch to double quotes
        self.assertIn('"Warning! \\$5 isn\'t \'free\'."', src)
        self.assertIn('"Don\'t share your OTP!"', src)
        self.assertNotIn("\t", src)

    def test_dart_str(self):
        self.assertEqual(g.dart_str("a'b"), '"a\'b"')
        self.assertEqual(g.dart_str("a'b\"c"), "'a\\'b\"c'")
        self.assertEqual(g.dart_str("$x\\"), "'\\$x\\\\'")

    @unittest.skipUnless(shutil.which("dart") or Path.home().joinpath("flutter/bin/dart").exists(),
                         "dart not installed")
    def test_dart_format_is_a_noop(self):
        _, m = self.build()
        long = dict(m)
        long["clips"] = {k: {**v, "text": v["text"] + " " + "x" * 70}
                         for k, v in m["clips"].items()}
        dart = shutil.which("dart") or str(Path.home() / "flutter/bin/dart")
        for manifest in (m, long):
            f = self.tmp / "whisper_clips.dart"
            f.write_text(g.render_dart(manifest), encoding="utf-8")
            r = subprocess.run([dart, "format", "--output=none", "--set-exit-if-changed", str(f)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class ScoreTests(unittest.TestCase):
    def test_english_needs_every_word(self):
        r = g.score("Warning! This caller is trying to isolate you.",
                    "Warming, this caller is trying to isolate you.", "en")
        self.assertFalse(r["ok"])
        self.assertEqual(r["diffs"], ["warning -> warming"])

    def test_english_contractions_and_punctuation(self):
        self.assertTrue(g.score("Don't keep it secret! We're alerting your family.",
                                "Do not keep it secret, we are alerting your family.", "en")["ok"])

    def test_brand_name(self):
        line = "a known scammer on the Chaukanna network."
        self.assertFalse(g.score(line, "a known scammer on the Chokanna network.", "en")["ok"])
        self.assertTrue(g.score(line, "a known scammer on the Chaukhanna network.", "en")["ok"])
        self.assertTrue(g.score(line, "a known scammer on the Chowkanna network.", "en")["ok"])

    def test_hindi_spelling_variants(self):
        r = g.score("बैंक कभी फ़ोन पर पिन नहीं मांगते।", "बैंक कभी फोन पर पिन नहीं माँगते", "hi")
        self.assertEqual(r["score"], 1.0)

    def test_acronyms_in_latin_script(self):
        self.assertEqual(g.score("ಓಟಿಪಿ ಹೇಳಬೇಡಿ! ಇದು ಮೋಸ.", "OTP ಹೇಳಬೇಡಿ, ಇದು ಮೋಸ.", "kn")["score"], 1.0)

    def test_indic_wrong_line_fails(self):
        self.assertFalse(g.score("ಓಟಿಪಿ ಹೇಳಬೇಡಿ! ಇದು ಮೋಸ.", "ನಮಸ್ಕಾರ, ಹೇಗಿದ್ದೀರಾ?", "kn")["ok"])


class ScriptTableTests(unittest.TestCase):
    def test_every_clip_has_every_variant_and_language(self):
        for clip, variants in g.SCRIPTS.items():
            for variant in g.VARIANTS:
                for lang in g.LANGS:
                    self.assertTrue(variants[variant][lang].strip(), (clip, variant, lang))

    def test_clip_ids_match_contract(self):
        self.assertEqual(set(g.SCRIPTS), {"warn_otp", "warn_digital_arrest", "warn_secrecy",
                                          "warn_known_scammer"})

    def test_shipped_manifest_is_current(self):
        """output_assets/ in the repo matches the scripts (run generate.py if this fails)."""
        bad, out = run_verify(g.all_specs(), g.OUT_DIR)
        self.assertEqual(bad, 0, out)

if __name__ == "__main__":
    unittest.main()
