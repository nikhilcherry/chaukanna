import asyncio
import io
import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace

import httpx
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
import audio  # noqa: E402
import replay  # noqa: E402
import stt  # noqa: E402
import bridge  # noqa: E402
import pipeline  # noqa: E402
from config import Config, new_call_id  # noqa: E402

LOUD = b"\x05\x10" * 64000          # 4 s of non-silent PCM


def speech_np(seconds, seed=0):
    rng = np.random.default_rng(seed)
    n = int(16000 * seconds)
    t = np.arange(n) / 16000
    return rng.normal(0, 3000, n) * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t))


def speechlike(bursts, gap=0.7, seed=0):
    parts = []
    for i, b in enumerate(bursts):
        parts += [speech_np(b, seed + i), np.zeros(int(16000 * gap))]
    return np.clip(np.concatenate(parts), -32768, 32767).astype(np.int16).tobytes()


def verdict(p=0, clip="none", otp=False, secrecy=False, scam="digital_arrest", **kw):
    return {"call_id": "x", "scam_type": scam if p else "none", "pressure": p, "asks_otp_or_pin": otp,
            "demands_secrecy": secrecy, "confidence": .9, "language": "en",
            "recommended_whisper_clip": clip, "summary_for_family": "s", **kw}


class FakeServices:
    """httpx MockTransport standing in for the classifier and n8n."""

    def __init__(self, verdicts=(), n8n_reply=None, n8n_delay=0.0):
        self.verdicts = list(verdicts)
        self.n8n, self.resets, self.classify_bodies, self.reported = [], [], [], []
        self.scam_list = []
        self.n8n_reply = n8n_reply if n8n_reply is not None else {"ok": True}
        self.n8n_delay = n8n_delay

    async def handler(self, req: httpx.Request):
        if req.url.path == "/n8n":
            body = json.loads(req.content)
            self.n8n.append(body)
            if body["event"] == "incident" and self.n8n_delay:
                await asyncio.sleep(self.n8n_delay)
            return httpx.Response(200, json=self.n8n_reply if body["event"] == "incident" else {"ok": True})
        if req.url.path == "/scam_numbers":
            if req.method == "GET":
                return httpx.Response(200, json={"numbers": self.scam_list, "risky_country_codes": {}})
            self.reported.append(json.loads(req.content))
            return httpx.Response(200, json={"added": self.reported[-1]["number"]})
        if req.url.path.startswith("/reset/"):
            self.resets.append(req.url.path.rsplit("/", 1)[1])
            return httpx.Response(200, json={"cleared": True})
        self.classify_bodies.append(json.loads(req.content))
        v = self.verdicts.pop(0) if self.verdicts else verdict()
        return httpx.Response(200, json=v)

    def client(self):
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


def cfg(**kw):
    base = dict(n8n_url="http://x/n8n", classifier_url="http://x/classify", mock_stt=True, silence_rms=0,
                whisper_cooldown=20)
    base.update(kw)
    return Config(**base)


class Audio(unittest.TestCase):
    def test_pause_chunker_cuts_at_pauses(self):
        pcm = speechlike([2.0, 1.0, 2.5], gap=0.6)                    # 2.0 | 1.0 (+0.6) 2.5
        cs = audio.chunk_stream(pcm)
        spans = [(round(c.start / 16000, 1), round(c.end / 16000, 1)) for c in cs]
        self.assertEqual(len(cs), 3, spans)
        self.assertAlmostEqual(cs[0].speech_end / 16000, 2.0, delta=0.05)
        self.assertLess(cs[0].end / 16000, 2.4)                        # cut ~300 ms into the pause
        self.assertAlmostEqual(cs[1].speech_end / 16000, 3.6, delta=0.05)  # pre-roll + 1.0 s + pause >= 1.5 s
        self.assertLess(cs[1].end / 16000 - cs[1].speech_end / 16000, 0.35)

    def test_pause_chunker_never_exceeds_max(self):
        cs = audio.chunk_stream(speechlike([9.0], gap=0.5))
        self.assertTrue(all(c.seconds <= 4.0 + 1e-6 for c in cs), [c.seconds for c in cs])
        self.assertGreaterEqual(len(cs), 3)

    def test_pause_chunker_skips_silence_and_short_tails(self):
        ch = audio.PauseChunker()
        self.assertEqual(ch.push(b"\x00\x00" * 16000 * 5), [])
        self.assertLessEqual(len(ch.frames), 10)                      # only the pre-roll is kept
        self.assertIsNone(ch.tail())
        ch.push(speechlike([0.3], gap=0.0))
        self.assertIsNone(ch.tail())                                  # < 0.5 s of audio: not worth STT

    def test_pause_chunker_noisy_room_raises_threshold(self):
        rng = np.random.default_rng(5)
        noise = rng.normal(0, 300, 16000 * 4)
        sig = np.concatenate([noise, noise[:16000 * 2] + speech_np(2.0), noise])
        cs = audio.chunk_stream(np.clip(sig, -32768, 32767).astype(np.int16).tobytes())
        self.assertEqual(len(cs), 1, [(c.start / 16000, c.end / 16000) for c in cs])

    def test_wav_header(self):
        wav = audio.pcm_to_wav(b"\x00\x00" * 16000)
        with wave.open(io.BytesIO(wav)) as w:
            self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()), (1, 2, 16000, 16000))

    def test_resample_stereo_44k(self):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(44100); w.writeframes(b"\x10\x00" * 2 * 44100)
        p = Path(__file__).parent / "_s.wav"
        p.write_bytes(buf.getvalue())
        try:
            pcm = audio.load_wav_16k_mono(str(p))
            chans = audio.load_wav_channels(str(p))
        finally:
            p.unlink()
        self.assertAlmostEqual(len(pcm) / 2, 16000, delta=2)
        self.assertEqual(len(chans), 2)


class Helpers(unittest.TestCase):
    def test_new_call_id_unique(self):
        a, b = new_call_id("chaukanna"), new_call_id("chaukanna")
        self.assertNotEqual(a, b)
        self.assertRegex(a, r"^chaukanna-[0-9a-f]{8}$")

    def test_normalize_number(self):
        pipeline._learned_numbers.clear()
        self.assertEqual(pipeline.normalize_number("+91 98765-43210 - CBI Officer"), "+919876543210")
        self.assertEqual(pipeline.normalize_number("9876543210"), "+919876543210")
        self.assertEqual(pipeline.normalize_number("Unknown"), "Unknown")
        self.assertTrue(pipeline.locally_known_scammer("+923001234567"))
        self.assertFalse(pipeline.locally_known_scammer("+919876543210"))

    def test_reset_url(self):
        self.assertEqual(Config(classifier_url="http://h:8010/classify").reset_url_base, "http://h:8010/reset")


class Flow(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        pipeline._learned_numbers.clear()     # incidents teach the process-wide scam list

    async def run_chunks(self, svc, verdicts_count, c=None, end=True):
        sent = []

        async def publish(m):
            sent.append(m)
            return True

        async with svc.client() as http:
            p = pipeline.Pipeline(c or cfg(), http, publish)
            st = p.new_call("call-1", "+91 98765 43210")
            for _ in range(verdicts_count):
                await p.process_chunk(st, "caller", LOUD)
            if end:
                await p.end_call(st)
            await p.drain()
        return sent, st

    async def test_whisper_once_per_clip(self):
        svc = FakeServices([verdict(2, "warn_digital_arrest")] * 3 + [verdict(3, "warn_otp", otp=True)] * 2)
        sent, _ = await self.run_chunks(svc, 5)
        verdicts = [m for m in sent if m["type"] == "verdict"]
        self.assertEqual([m["whisper_clip"] for m in verdicts],
                         ["warn_digital_arrest", "none", "none", "warn_otp", "none"])
        self.assertEqual([m["whisper"] for m in verdicts], [True, False, False, True, False])

    async def test_whisper_repeats_only_on_escalation_after_cooldown(self):
        svc = FakeServices([verdict(2, "warn_otp", otp=True), verdict(3, "warn_otp", otp=True)])
        sent, _ = await self.run_chunks(svc, 2, cfg(whisper_cooldown=20))
        self.assertEqual([m["whisper"] for m in sent if m["type"] == "verdict"], [True, False])  # within cooldown
        svc = FakeServices([verdict(2, "warn_otp", otp=True), verdict(3, "warn_otp", otp=True)])
        sent, _ = await self.run_chunks(svc, 2, cfg(whisper_cooldown=0))
        self.assertEqual([m["whisper"] for m in sent if m["type"] == "verdict"], [True, True])   # escalated

    async def test_n8n_event_sequence(self):
        reply = {"ok": True, "incident_id": "inc-1", "complaint_draft": {"en": "draft"}, "approve_url": "http://a"}
        svc = FakeServices([verdict(1), verdict(1), verdict(2, "warn_digital_arrest"), verdict(2, "warn_digital_arrest"),
                            verdict(2, "warn_secrecy", secrecy=True), verdict(3, "warn_otp", otp=True, secrecy=True)],
                           n8n_reply=reply)
        sent, st = await self.run_chunks(svc, 6)
        events = [b["event"] for b in svc.n8n]
        self.assertEqual(events[:3], ["telemetry", "incident", "escalation"])    # later ones may coalesce
        self.assertEqual(set(events[2:-1]), {"escalation"})
        self.assertEqual(events[-1], "call_ended")
        self.assertEqual(svc.n8n[-2]["verdict"]["pressure"], 3)
        inc = svc.n8n[1]
        self.assertEqual(inc["call_id"], "call-1")
        self.assertEqual(inc["caller_number"], "+919876543210")
        self.assertEqual(inc["victim_id"], "demo-victim-1")
        self.assertGreaterEqual(len(inc["transcript"]), 3)          # built at send time: latest lines
        self.assertEqual(set(inc["transcript"][0]), {"t", "ts", "speaker", "text"})
        self.assertIn("[00:", inc["transcript_text"])
        self.assertEqual(len(svc.n8n[-1]["transcript"]), 6)
        incident_msgs = [m for m in sent if m["type"] == "incident"]
        self.assertEqual(len(incident_msgs), 1)
        self.assertEqual(incident_msgs[0]["incident_id"], "inc-1")
        self.assertEqual(incident_msgs[0]["call_id"], "call-1")
        self.assertEqual(svc.resets, ["call-1"])

    async def test_incident_caller_joins_shared_scam_list(self):
        svc = FakeServices([verdict(1), verdict(2, "warn_digital_arrest"), verdict(3, "warn_otp", otp=True)])
        await self.run_chunks(svc, 3)
        self.assertEqual(svc.reported, [{"number": "+919876543210", "scam_type": "digital_arrest",
                                         "note": "Chaukanna incident call-1"}])     # once, at the incident
        async with svc.client() as http:
            async def pub(m): return True
            redial = pipeline.Pipeline(cfg(), http, pub).new_call("call-2", "+91 98765 43210")
        self.assertTrue(redial.known_scammer)                         # flagged in call_started

    async def test_report_scammers_off_and_unknown_number(self):
        svc = FakeServices([verdict(2, "warn_digital_arrest")])
        await self.run_chunks(svc, 1, cfg(report_scammers=False))
        self.assertEqual(svc.reported, [])
        async with svc.client() as http:
            async def pub(m): return True
            p = pipeline.Pipeline(cfg(), http, pub)
            self.assertFalse(await p.report_scammer(p.new_call("c", "CBI Officer"), verdict(2)))
        self.assertEqual(svc.reported, [])

    async def test_sync_known_numbers_from_classifier(self):
        svc = FakeServices()
        svc.scam_list = [{"number": "+919988776655", "scam_type": "kyc_update", "note": ""}]
        async with svc.client() as http:
            async def pub(m): return True
            p = pipeline.Pipeline(cfg(), http, pub)
            self.assertEqual(await p.sync_known_numbers(), 1)
            self.assertTrue(p.new_call("c", "+91 99887 76655").known_scammer)

    async def test_escalations_coalesce_behind_slow_incident(self):
        svc = FakeServices([verdict(2, "warn_digital_arrest"), verdict(2, "warn_secrecy", secrecy=True),
                            verdict(3, "warn_otp", otp=True, secrecy=True)], n8n_delay=0.3)
        sent, _ = await self.run_chunks(svc, 3)
        self.assertEqual([b["event"] for b in svc.n8n], ["incident", "escalation", "call_ended"])
        self.assertEqual(svc.n8n[1]["verdict"]["pressure"], 3)       # the coalesced one is the latest

    async def test_no_call_ended_event_without_incident(self):
        svc = FakeServices([verdict(1), verdict(0)])
        await self.run_chunks(svc, 2)
        self.assertEqual([b["event"] for b in svc.n8n], ["telemetry"])

    async def test_pressure_ratchets_across_out_of_order_replies(self):
        svc = FakeServices([verdict(3, "warn_otp", otp=True), verdict(1)])
        sent, st = await self.run_chunks(svc, 2)
        v = [m for m in sent if m["type"] == "verdict"]
        self.assertEqual([m["pressure"] for m in v], [3, 3])
        self.assertTrue(v[1]["verdict"]["asks_otp_or_pin"])

    async def test_classifier_down_uses_keyword_verdict(self):
        def handler(req): raise httpx.ConnectError("down")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            async def pub(m): return True
            p = pipeline.Pipeline(cfg(n8n_url=""), http, pub)
            st = p.new_call("c")
            r = None
            for _ in range(4):
                r = await p.process_chunk(st, "caller", LOUD) or r
        self.assertEqual(r["verdict"]["scam_type"], "digital_arrest")
        self.assertGreaterEqual(r["pressure"], 2)
        self.assertTrue(r["verdict"]["degraded"])

    async def test_silence_skipped(self):
        async with httpx.AsyncClient() as http:
            async def pub(m): raise AssertionError
            p = pipeline.Pipeline(Config(mock_stt=True), http, pub)
            self.assertIsNone(await p.process_chunk(p.new_call("c"), "caller", b"\x00\x00" * 64000))


class OtpSms(unittest.IsolatedAsyncioTestCase):
    def test_clean_keeps_only_contract_fields(self):
        self.assertIsNone(pipeline.clean_otp_sms({"purpose": "lottery"}))
        self.assertIsNone(pipeline.clean_otp_sms("payment"))
        self.assertEqual(pipeline.clean_otp_sms({"purpose": "upi", "service": "OTP 482913", "amount": "abc",
                                                 "seconds_before_call": -5, "code": "482913"}),
                         {"purpose": "upi", "service": "", "amount": None, "seconds_before_call": 0.0})

    async def test_payment_sms_warns_at_once_and_never_carries_the_code(self):
        svc = FakeServices([verdict(2, "warn_otp", scam="other")])
        sent = []

        async def publish(m):
            sent.append(m)
            return True

        async with svc.client() as http:
            p = pipeline.Pipeline(cfg(), http, publish)
            st = p.new_call("call-1", "+91 98765 43210")
            msg = await p.note_otp_sms(st, {"purpose": "payment", "service": "HDFC Bank", "amount": "49999",
                                            "code": "482913", "body": "Your OTP is 482913"})
            await p.drain()
        self.assertEqual(svc.classify_bodies[-1], {"call_id": "call-1", "purpose": "payment", "service": "HDFC Bank",
                                                   "amount": 49999.0, "seconds_before_call": 0.0})
        self.assertEqual((msg["speaker"], msg["whisper_clip"]), ("sms", "warn_otp"))
        self.assertEqual(msg["chunk_text"], "OTP SMS: payment, ₹49,999, from HDFC Bank")
        self.assertNotIn("482913", json.dumps(sent + svc.n8n + svc.classify_bodies))
        self.assertIn("incident", [b["event"] for b in svc.n8n])

    async def test_only_the_victim_sends_and_an_early_sms_waits_for_the_call(self):
        svc = FakeServices()
        async with svc.client() as http:
            s = bridge.LiveSession(cfg(), http)
            s.victim = "victim"
            noted = []

            async def fake_note(st, sms):
                noted.append((st.call_id, sms))
            s.pipe.note_otp_sms = fake_note

            def pkt(who, topic="chaukanna.otp_sms", data=b'{"purpose": "everyday", "service": "Swiggy"}'):
                return SimpleNamespace(participant=SimpleNamespace(identity=who) if who else None, topic=topic, data=data)

            for bad in (pkt("caller-x"), pkt(None), pkt("victim", topic="chaukanna.verdict"), pkt("victim", data=b"{oops")):
                s.on_data(bad)
            self.assertIsNone(s.pending_otp_sms)
            s.on_data(pkt("victim"))                           # no call yet: held for the next one
            self.assertIsNotNone(s.pending_otp_sms)
            s.callers["caller-1"] = {"phone": "+911234567890"}
            s.start_call()
            s.on_data(pkt("victim", data=b'{"purpose": "payment"}'))   # during the call: straight through
            await asyncio.gather(*list(s._tasks))
            self.assertIsNone(s.pending_otp_sms)
            self.assertEqual([n[1]["purpose"] for n in noted], ["everyday", "payment"])
            self.assertTrue(all(cid == s.call.call_id for cid, _ in noted))
            self.assertIn("seconds_before_call", noted[0][1])


class Masking(unittest.TestCase):
    def test_otp_masked_in_all_forms(self):
        m = pipeline.mask_otp
        self.assertEqual(m("ओटीपी है 4 5 6 7 8 नौ।"), "ओटीपी है ******।")
        self.assertEqual(m("OTP 456789."), "OTP ******.")
        self.assertEqual(m("it is four five six seven, ok"), "it is ******, ok")
        self.assertEqual(m("ek do teen char paanch chhe"), "******")
        self.assertEqual(m("ಒಂದು ಎರಡು ಮೂರು ನಾಲ್ಕು."), "******.")
        self.assertEqual(m("call me at 2 pm, I have 2 kids"), "call me at 2 pm, I have 2 kids")


class VictimMasking(unittest.IsolatedAsyncioTestCase):
    async def test_victim_digits_never_leave_the_bridge(self):
        svc = FakeServices([verdict(3, "warn_otp", otp=True)])
        sent = []

        async def pub(m):
            sent.append(m)
            return True

        async with svc.client() as http:
            p = pipeline.Pipeline(cfg(), http, pub, stt=stt.MockSTT(["OTP is 4 5 6 7 8 9"]))
            st = p.new_call("c")
            await p.process_chunk(st, "victim", LOUD)
            await p.end_call(st)
            await p.drain()
        self.assertEqual(svc.classify_bodies[0]["chunk_text"], "OTP is ******")
        self.assertEqual(sent[0]["chunk_text"], "OTP is ******")
        self.assertNotIn("4 5 6", json.dumps(svc.n8n, ensure_ascii=False))
        self.assertEqual(st.segments[0]["text"], "OTP is ******")


class FailingSTT:
    name = "sarvam"

    def __init__(self, status):
        self.status, self.calls = status, 0

    async def transcribe(self, wav, pcm):
        self.calls += 1
        raise stt.SttError("boom", self.status)


class Router(unittest.IsolatedAsyncioTestCase):
    async def test_429_opens_breaker_and_uses_fallback(self):
        primary, fallback = FailingSTT(429), stt.MockSTT(["local"])
        r = stt.SttRouter(primary, fallback)
        self.assertEqual((await r.transcribe(b"", b""))[2], "mock")
        self.assertEqual((await r.transcribe(b"", b""))[2], "mock")
        self.assertEqual(primary.calls, 1)                       # breaker open: Sarvam not retried yet

    async def test_single_timeout_falls_back_without_breaker(self):
        primary = FailingSTT(None)
        r = stt.SttRouter(primary, stt.MockSTT(["local"]))
        await r.transcribe(b"", b"")
        await r.transcribe(b"", b"")                             # second failure opens it
        await r.transcribe(b"", b"")
        self.assertEqual(primary.calls, 2)

    async def test_no_fallback_raises(self):
        with self.assertRaises(stt.SttError):
            await stt.SttRouter(FailingSTT(500), None).transcribe(b"", b"")


class ReplayInputs(unittest.TestCase):
    def test_stereo_is_two_speakers_and_cache_roundtrip(self):
        left = np.frombuffer(speechlike([2.0], seed=1), dtype=np.int16)
        right = np.frombuffer(b"\x00\x00" * 16000 * 1 + speechlike([1.6], seed=2), dtype=np.int16)
        n = max(len(left), len(right))
        st_ = np.zeros((n, 2), dtype=np.int16)
        st_[:len(left), 0], st_[:len(right), 1] = left, right
        d = Path(tempfile.mkdtemp())
        wav = d / "call.wav"
        wav.write_bytes(audio.pcm_to_wav(st_.tobytes(), channels=2))
        c = Config()
        segs, cached = replay.build_segments(c, wav)
        self.assertFalse(cached)
        self.assertEqual([x.speaker for x in segs], ["caller", "victim"])
        for x in segs:
            x.text, x.language, x.source = f"{x.speaker} words", "hi", "sarvam"
        self.assertIsNotNone(replay.write_cache(wav, segs, c))
        segs2, cached2 = replay.build_segments(c, wav)
        self.assertTrue(cached2)
        self.assertEqual([(x.speaker, x.text, x.source) for x in segs2],
                         [("caller", "caller words", "cache"), ("victim", "victim words", "cache")])
        self.assertEqual(len(segs2[1].pcm), len(segs[1].pcm))
        wav.write_bytes(wav.read_bytes() + b"\x00\x00")           # re-recorded: cache no longer matches
        self.assertFalse(replay.build_segments(c, wav)[1])

    def test_mock_transcripts_are_never_cached(self):
        d = Path(tempfile.mkdtemp())
        wav = d / "m.wav"
        wav.write_bytes(audio.pcm_to_wav(speechlike([2.0])))
        segs, _ = replay.build_segments(Config(), wav)
        for x in segs:
            x.text, x.source = "canned", "mock"
        self.assertIsNone(replay.write_cache(wav, segs, Config()))


# --------------------------------------------------------------------------- session lifecycle
def person(identity, phone="", reason=0):
    return SimpleNamespace(identity=identity, name=phone or identity, disconnect_reason=reason,
                           metadata=json.dumps({"phone": phone}) if phone else "")


class RecordingSession(bridge.LiveSession):
    def __init__(self, *a, **kw):
        self.sent = []
        super().__init__(*a, **kw)

    async def publish(self, msg):
        if self.victim is None:
            return False
        self.sent.append(msg)
        return True


class Lifecycle(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.svc = FakeServices([verdict(2, "warn_digital_arrest")] * 20)
        self.http = self.svc.client()
        self.s = RecordingSession(cfg(call_end_grace=0.2), self.http)

    async def asyncTearDown(self):
        await self.s.pipe.drain(2)
        await self.http.aclose()

    async def settle(self, t=0.05):
        await asyncio.sleep(t)

    def types(self):
        return [m["type"] for m in self.s.sent]

    async def test_back_to_back_calls_get_new_ids_and_reset(self):
        from livekit import rtc
        hang = rtc.DisconnectReason.CLIENT_INITIATED
        s = self.s
        s.on_join(person("victim"))
        s.on_join(person("caller-a", "+91 90000 00001"))
        await self.settle()
        first = s.call.call_id
        s.on_leave(person("caller-a", reason=hang))
        await self.settle()
        self.assertIsNone(s.call)
        s.on_join(person("caller-b", "+91 90000 00002"))
        await self.settle()
        second = s.call.call_id
        self.assertNotEqual(first, second)
        self.assertEqual(self.types(), ["call_started", "call_ended", "call_started"])
        self.assertEqual(self.s.sent[2]["caller_number"], "+919000000002")
        await self.s.pipe.drain(2)
        self.assertIn(first, self.svc.resets)

    async def test_late_victim_gets_snapshot_with_unheard_whisper(self):
        s = self.s
        s.cfg.n8n_url = ""
        s.on_join(person("caller-a", "+919000000001"))
        await self.settle()
        st = s.call
        await s.pipe.process_chunk(st, "caller", LOUD)        # victim not here yet: whisper not delivered
        self.assertEqual(s.sent, [])
        s.on_join(person("victim"))
        await self.settle()
        self.assertEqual(self.types(), ["call_started", "verdict"])
        snap = s.sent[1]
        self.assertTrue(snap["snapshot"])
        self.assertTrue(snap["whisper"])
        self.assertEqual(snap["whisper_clip"], "warn_digital_arrest")
        self.assertEqual(snap["call_id"], st.call_id)

    async def test_network_drop_within_grace_keeps_call(self):
        s = self.s
        s.on_join(person("victim"))
        s.on_join(person("caller-a", "+919000000001"))
        await self.settle()
        cid = s.call.call_id
        s.on_leave(person("caller-a", reason=0))              # not client initiated -> grace
        await self.settle(0.05)
        s.on_join(person("caller-a", "+919000000001"))
        await self.settle(0.3)
        self.assertIsNotNone(s.call)
        self.assertEqual(s.call.call_id, cid)
        self.assertNotIn("call_ended", self.types())

    async def test_drop_beyond_grace_ends_call(self):
        s = self.s
        s.on_join(person("victim"))
        s.on_join(person("caller-a", "+919000000001"))
        await self.settle()
        s.on_leave(person("caller-a", reason=0))
        await self.settle(0.4)
        self.assertIsNone(s.call)
        self.assertEqual(self.types(), ["call_started", "call_ended"])

    async def test_victim_hangup_ends_call_and_rejoin_starts_new_one(self):
        from livekit import rtc
        s = self.s
        s.on_join(person("victim"))
        s.on_join(person("caller-a", "+919000000001"))
        await self.settle()
        first = s.call.call_id
        s.on_leave(person("victim", reason=rtc.DisconnectReason.CLIENT_INITIATED))
        await self.settle()
        self.assertIsNone(s.call)
        s.on_join(person("victim"))
        await self.settle()
        self.assertIsNotNone(s.call)
        self.assertNotEqual(s.call.call_id, first)


class Consumer(unittest.IsolatedAsyncioTestCase):
    async def test_flush_waits_for_last_chunk(self):
        svc = FakeServices([verdict(1)] * 5)
        async with svc.client() as http:
            s = RecordingSession(cfg(), http)
            s.on_join(person("victim"))
            s.on_join(person("caller-a", "+919000000001"))
            c = bridge.TrackConsumer(s, None, person("caller-a"), "caller", "TR_1")
            w = asyncio.create_task(c._worker())
            c.chunker.push(speech_np(1.2).astype(np.int16).tobytes())   # mid-utterance: no pause yet
            await c.flush()
            w.cancel()
        self.assertEqual([m["type"] for m in s.sent].count("verdict"), 1)


if __name__ == "__main__":
    unittest.main()


class VictimTokenEndpoint(unittest.TestCase):
    def test_victim_token_needs_the_key(self):
        import os
        import threading
        import urllib.error
        import urllib.request
        from unittest import mock
        import token_server
        env = {"LIVEKIT_API_KEY": "k", "LIVEKIT_API_SECRET": "s" * 32, "LIVEKIT_URL": "wss://lk", "VICTIM_TOKEN_KEY": "sesame"}
        with mock.patch.dict(os.environ, env):
            srv = token_server.ThreadingHTTPServer(("127.0.0.1", 0), token_server.H)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            base = f"http://127.0.0.1:{srv.server_address[1]}/victim-token"
            try:
                for bad in ("", "?key=wrong"):
                    with self.assertRaises(urllib.error.HTTPError) as e:
                        urllib.request.urlopen(base + bad)
                    self.assertEqual(e.exception.code, 404)
                body = json.loads(urllib.request.urlopen(base + "?key=sesame").read())
                self.assertEqual((body["identity"], body["url"]), ("victim", "wss://lk"))
                self.assertEqual(body["token"].count("."), 2)
                with mock.patch.dict(os.environ, {"VICTIM_TOKEN_KEY": ""}):
                    with self.assertRaises(urllib.error.HTTPError):
                        urllib.request.urlopen(base + "?key=")      # off when no key is configured
            finally:
                srv.shutdown()


class ConsoleCallLog(unittest.IsolatedAsyncioTestCase):
    """What the console (console/index.html) replays: calllog.py files written by the bridge."""

    def tearDown(self):
        pipeline._learned_numbers.clear()

    async def test_every_call_message_and_n8n_outcome_is_logged(self):
        import calllog
        reply = {"ok": True, "incident_id": "inc-1", "complaint_draft": {"en": "draft"}, "family_alerted": True}
        svc = FakeServices([verdict(1), verdict(2, "warn_digital_arrest"), verdict(3, "warn_otp", otp=True)], n8n_reply=reply)
        with tempfile.TemporaryDirectory() as d:
            async with svc.client() as http:
                s = bridge.LiveSession(cfg(call_log_dir=d), http)        # no room, no victim: logged anyway
                st = s.pipe.new_call("call-1", "+91 98765 43210", caller_label="CBI")
                s.call = st
                await s.publish(s.pipe.call_started_msg(st))
                for _ in range(3):
                    await s.pipe.process_chunk(st, "caller", LOUD)
                await s.publish({"type": "heartbeat", "call_id": "call-1", "in_call": True, "ts": 1.0})
                await s.publish({**st.last_message, "snapshot": True})
                await s.pipe.end_call(st)
                await s.pipe.drain()
            recs = calllog.read_call(d, "call-1")
            kinds = [(r["type"], r.get("event")) for r in recs]
            self.assertEqual(kinds[0], ("call_started", None))
            self.assertEqual([k for k in kinds if k[0] == "verdict"], [("verdict", None)] * 3)   # no snapshot copy
            self.assertNotIn(("heartbeat", None), kinds)
            for k in [("n8n_event", "telemetry"), ("n8n_event", "incident"), ("n8n_reply", "incident"),
                      ("incident", None), ("scam_list", None), ("call_ended", None), ("n8n_event", "call_ended")]:
                self.assertIn(k, kinds)
            self.assertTrue(all(r["call_id"] == "call-1" and "logged" in r for r in recs))
            self.assertTrue(next(r for r in recs if r["type"] == "n8n_reply")["ok"])
            row = calllog.summarize(d)[0]
            self.assertEqual((row["call_id"], row["caller_label"], row["peak_pressure"], row["chunks"]), ("call-1", "CBI", 3, 3))
            self.assertTrue(row["incident"] and row["ended"])

    async def test_n8n_event_logged_as_not_sent_when_n8n_is_off(self):
        import calllog
        svc = FakeServices([verdict(2, "warn_digital_arrest")])
        with tempfile.TemporaryDirectory() as d:
            async with svc.client() as http:
                p = pipeline.Pipeline(cfg(n8n_url="", call_log_dir=d), http, lambda m: asyncio.sleep(0, True))
                st = p.new_call("call-2", "+91 90000 12345")
                await p.process_chunk(st, "caller", LOUD)
                await p.drain()
            ev = [r for r in calllog.read_call(d, "call-2") if r["type"] == "n8n_event"]
            self.assertEqual([(r["event"], r["sent"]) for r in ev], [("incident", False)])
            self.assertEqual(svc.n8n, [])

    def test_read_call_skips_half_written_lines_and_bad_ids(self):
        import calllog
        with tempfile.TemporaryDirectory() as d:
            Path(d, "c1.jsonl").write_text('{"type": "call_started", "call_id": "c1"}\n{"type": "verdict"}\n{"type": "ver')
            self.assertEqual(len(calllog.read_call(d, "c1")), 2)
            self.assertEqual(calllog.read_call(d, "c1", start=1), [{"type": "verdict"}])
            self.assertIsNone(calllog.read_call(d, "../c1"))
            self.assertIsNone(calllog.read_call(d, "nope"))
            calllog.CallLog(d).write({"type": "verdict", "call_id": "../../etc/x"})        # unsafe id: not written
            calllog.CallLog(None).write({"type": "verdict", "call_id": "c2"})               # logging off
            self.assertEqual(sorted(p.name for p in Path(d).iterdir()), ["c1.jsonl"])
        self.assertEqual(Config().call_log_dir, "")                                         # tests never write logs


class ConsoleEndpoint(unittest.TestCase):
    def test_console_page_and_call_api(self):
        import os
        import threading
        import urllib.error
        import urllib.request
        from unittest import mock
        import token_server
        with tempfile.TemporaryDirectory() as d:
            Path(d, "chaukanna-abc12345.jsonl").write_text(
                '{"type": "call_started", "call_id": "chaukanna-abc12345", "caller_number": "+911", "ts": 1}\n'
                '{"type": "verdict", "call_id": "chaukanna-abc12345", "pressure": 2, "scam_type": "digital_arrest", "ts": 2}\n')
            with mock.patch.dict(os.environ, {"CALL_LOG_DIR": d, "CONSOLE_KEY": ""}):
                srv = token_server.ThreadingHTTPServer(("127.0.0.1", 0), token_server.H)
                threading.Thread(target=srv.serve_forever, daemon=True).start()
                base = f"http://127.0.0.1:{srv.server_address[1]}"
                try:
                    page = urllib.request.urlopen(base + "/console/").read().decode()
                    self.assertIn("<title>Chaukanna console</title>", page)
                    r = urllib.request.urlopen(base + "/console/api/calls")
                    self.assertIsNone(r.headers.get("Access-Control-Allow-Origin"))      # other sites can't read transcripts
                    calls = json.loads(r.read())["calls"]
                    self.assertEqual((calls[0]["call_id"], calls[0]["peak_pressure"], calls[0]["ended"]),
                                     ("chaukanna-abc12345", 2, False))
                    recs = json.loads(urllib.request.urlopen(base + "/console/api/calls/chaukanna-abc12345?from=1").read())
                    self.assertEqual([x["type"] for x in recs["records"]], ["verdict"])
                    self.assertIn("sample-courier-to-cbi", urllib.request.urlopen(base + "/console/samples/index.json").read().decode())
                    for bad in ("/console/api/calls/nope", "/console/../token_server.py", "/console/..%2f.env", "/console/samples/x.py"):
                        with self.assertRaises(urllib.error.HTTPError) as e:
                            urllib.request.urlopen(base + bad)
                        self.assertEqual(e.exception.code, 404, bad)
                finally:
                    srv.shutdown()

    def test_call_api_is_loopback_only_unless_keyed(self):
        import os
        from unittest import mock
        import token_server
        remote, local = SimpleNamespace(client_address=("10.0.0.5", 4000)), SimpleNamespace(client_address=("127.0.0.1", 4000))
        with mock.patch.dict(os.environ, {"CONSOLE_KEY": ""}):
            self.assertFalse(token_server.H._console_allowed(remote, {}))
            self.assertTrue(token_server.H._console_allowed(local, {}))
        with mock.patch.dict(os.environ, {"CONSOLE_KEY": "sesame"}):
            self.assertFalse(token_server.H._console_allowed(remote, {"key": "wrong"}))
            self.assertTrue(token_server.H._console_allowed(remote, {"key": "sesame"}))


class ConsoleNetwork(unittest.TestCase):
    """/console/api/health and /console/api/network: every part of the system, joined."""

    def serve(self, routes):
        """A fake classifier + n8n on one port: path -> (status, json)."""
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        seen = []

        class Fake(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append((self.path, self.headers.get("X-Chaukanna-Key"), self.headers.get("User-Agent")))
                code, body = routes.get(self.path.split("?")[0], (404, {}))
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(body).encode())

            def log_message(self, *a):
                pass

        srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_address[1]}", seen

    def test_health_and_network_join_every_source(self):
        import os
        import time as _t
        from unittest import mock
        import calllog
        import token_server
        feed = {"ok": True, "incidents": [{"call_id": "c-old", "caller_number": "+911", "max_pressure": 3}],
                "scam_numbers": [{"phone_number": "+911", "report_count": 2}],
                "trusted_contacts": [{"victim_id": "v1", "contact_name": "Ravi", "telegram_ready": False}]}
        base, seen = self.serve({"/health": (200, {"ok": True, "backend": "jev", "known_numbers": 3, "circuit_open": False}),
                                 "/healthz": (200, {"status": "ok"}),
                                 "/scam_numbers": (200, {"numbers": [{"number": "+922"}]}),
                                 "/trusted_numbers": (200, {"numbers": [{"number": "+913", "name": "Ravi"}]}),
                                 "/webhook/chaukanna-network": (200, feed)})
        with tempfile.TemporaryDirectory() as d:
            calllog.CallLog(d).status({"room": "chaukanna", "in_call": False, "victim_present": True, "every_s": 5})
            Path(d, "c-new.jsonl").write_text('{"type": "call_started", "call_id": "c-new", "caller_number": "+911", "ts": 1}\n')
            env = {"CALL_LOG_DIR": d, "CLASSIFIER_URL": base + "/classify", "N8N_WEBHOOK_URL": base + "/webhook/chaukanna-verdict",
                   "CONSOLE_FEED_KEY": "k1", "CONSOLE_FEED_URL": "", "VICTIM_ID": "v1"}
            with mock.patch.dict(os.environ, env):
                token_server._cache.clear()
                h = token_server.system_health()
                for part in ("livekit", "bridge", "victim_phone", "classifier", "n8n", "supabase"):
                    self.assertTrue(h[part]["ok"], (part, h[part]))
                self.assertFalse(h["telegram"]["ok"])                       # placeholder chat id: shown, not hidden
                self.assertIn(("/webhook/chaukanna-network", "k1", token_server.UA), seen)   # keyed, not urllib's UA
                net = token_server.network()
                self.assertEqual([c["call_id"] for c in net["calls"]], ["c-new"])
                self.assertEqual(net["supabase"]["incidents"][0]["call_id"], "c-old")
                self.assertEqual(net["classifier"]["scam_numbers"], [{"number": "+922"}])
                self.assertEqual(net["classifier"]["trusted"][0]["name"], "Ravi")
                # a stale heartbeat means the bridge left the room
                Path(d, calllog.STATUS_FILE).write_text(json.dumps({"ts": _t.time() - 60, "every_s": 5}))
                token_server._cache.clear()
                self.assertFalse(token_server.system_health()["bridge"]["ok"])

    def test_feed_down_or_unconfigured_is_reported_not_raised(self):
        import os
        from unittest import mock
        import token_server
        base, _ = self.serve({"/webhook/chaukanna-network": (403, {"message": "Authorization data is wrong!"})})
        with mock.patch.dict(os.environ, {"N8N_WEBHOOK_URL": base + "/webhook/x", "CONSOLE_FEED_KEY": "bad",
                                          "CONSOLE_FEED_URL": "", "CLASSIFIER_URL": base + "/classify"}):
            token_server._cache.clear()
            self.assertEqual(token_server.supabase_feed()["error"], "HTTP 403")
            net = token_server.network()
            self.assertFalse(net["supabase"]["ok"] or net["classifier"]["ok"])
        with mock.patch.dict(os.environ, {"N8N_WEBHOOK_URL": "", "CONSOLE_FEED_KEY": "", "CONSOLE_FEED_URL": ""}):
            token_server._cache.clear()
            self.assertIn("not set", token_server.supabase_feed()["error"])
