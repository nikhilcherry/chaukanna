import asyncio
import io
import json
import sys
import unittest
import wave
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))
import bridge  # noqa: E402


class Audio(unittest.TestCase):
    def test_chunker_exact_4s(self):
        c = bridge.Chunker()
        self.assertEqual(bridge.CHUNK_BYTES, 128_000)
        self.assertEqual(c.push(b"\x01\x00" * 40_000), [])
        out = c.push(b"\x01\x00" * 40_000)
        self.assertEqual([len(x) for x in out], [128_000])
        self.assertEqual(len(c.buf), 32_000)
        self.assertEqual(len(c.tail()), 32_000)   # a 1 s tail is flushed
        self.assertIsNone(c.tail())

    def test_wav_header(self):
        wav = bridge.pcm_to_wav(b"\x00\x00" * 16000)
        with wave.open(io.BytesIO(wav)) as w:
            self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()), (1, 2, 16000, 16000))

    def test_resample_stereo_44k(self):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(44100); w.writeframes(b"\x10\x00" * 2 * 44100)
        p = Path(__file__).parent / "_s.wav"
        p.write_bytes(buf.getvalue())
        try:
            pcm = bridge.load_wav_16k_mono(str(p))
        finally:
            p.unlink()
        self.assertAlmostEqual(len(pcm) / 2, 16000, delta=2)


class Flow(unittest.IsolatedAsyncioTestCase):
    async def test_pipeline_fast_and_slow_path(self):
        calls = {"n8n": [], "classify": 0}

        def handler(req: httpx.Request):
            if req.url.path == "/n8n":
                calls["n8n"].append(json.loads(req.content))
                return httpx.Response(200)
            calls["classify"] += 1
            return httpx.Response(200, json={"call_id": "c", "scam_type": "digital_arrest", "pressure": 3,
                                             "asks_otp_or_pin": True, "demands_secrecy": True, "confidence": .9,
                                             "language": "en", "recommended_whisper_clip": "warn_otp", "summary_for_family": "x"})

        cfg = bridge.Config(n8n_url="http://x/n8n", classifier_url="http://x/classify", mock_stt=True, silence_rms=0)
        sent = []

        async def publish(b): sent.append(json.loads(b))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            p = bridge.Pipeline(cfg, http, publish)
            st = p.call("c"); st.caller_number = "+91 98"; st.victim_id = "victim"
            for _ in range(3):
                await p.process_chunk("c", "caller", b"\x05\x00" * 64000)
            await p.drain()
        self.assertEqual(len(sent), 3)
        self.assertTrue(sent[0]["whisper"])
        self.assertEqual(sent[0]["pressure"], 3)
        self.assertEqual(len(calls["n8n"]), 1)                  # 30 s cooldown suppresses repeats
        self.assertEqual(calls["n8n"][0]["caller_number"], "+91 98")
        self.assertEqual(len(calls["n8n"][0]["transcript"]), 1)

    async def test_classifier_down_uses_mock(self):
        def handler(req): raise httpx.ConnectError("down")
        cfg = bridge.Config(classifier_url="http://x/classify", mock_stt=True, silence_rms=0)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            async def pub(b): pass
            p = bridge.Pipeline(cfg, http, pub)
            r = await p.process_chunk("c", "caller", b"\x05\x00" * 64000)
        self.assertIn("scam_type", r["verdict"])

    async def test_silence_skipped(self):
        async with httpx.AsyncClient() as http:
            async def pub(b): raise AssertionError
            p = bridge.Pipeline(bridge.Config(mock_stt=True), http, pub)
            self.assertIsNone(await p.process_chunk("c", "caller", b"\x00\x00" * 64000))


if __name__ == "__main__":
    unittest.main()
