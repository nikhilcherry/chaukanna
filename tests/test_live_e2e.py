"""End-to-end over real WebRTC: local `livekit-server --dev`, the bridge as a subprocess, a scripted
victim and a robot caller in-process, and the stub classifier + n8n (never the real ones).

Two calls back to back:
  call 1: scam audio from the caller while the victim also speaks -> call_started, verdicts (with a
          whisper), heartbeats, the n8n incident reply, call_ended; n8n gets incident + call_ended;
          the chunk cut after the caller hangs up is still processed (no lost tail).
  call 2: a fresh call_id, and its first verdict does not inherit call 1's pressure.

Skipped if livekit-server is not installed or port 7880 is busy. Takes ~45 s.
"""
import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import tokens  # noqa: E402
from pipeline import mock_verdict  # noqa: E402
from tools import stubs  # noqa: E402
from tools.fake_victim import Victim  # noqa: E402
from tools.robot_caller import robot_call  # noqa: E402

LK_BIN = shutil.which("livekit-server") or str(Path.home() / ".local/bin/livekit-server")
LK_URL, LK_KEY, LK_SECRET = "ws://127.0.0.1:7880", "devkey", "secret"


def port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def speechlike(bursts: list[float], gap: float = 0.7, seed: int = 0) -> bytes:
    """Amplitude-modulated noise bursts separated by silence: loud enough for the gate, with pauses."""
    rng = np.random.default_rng(seed)
    parts = []
    for b in bursts:
        n = int(16000 * b)
        t = np.arange(n) / 16000
        parts.append(rng.normal(0, 3000, n) * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t)))
        parts.append(np.zeros(int(16000 * gap)))
    return np.clip(np.concatenate(parts), -32768, 32767).astype(np.int16).tobytes()


@unittest.skipUnless(Path(LK_BIN).exists(), "livekit-server not installed")
class LiveE2E(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        if not port_free(7880):
            raise unittest.SkipTest("port 7880 busy (another livekit-server?)")
        cls.tmp = Path(tempfile.mkdtemp(prefix="chaukanna-e2e-"))
        cls.lk = subprocess.Popen([LK_BIN, "--dev", "--bind", "127.0.0.1"], stdout=open(cls.tmp / "livekit.log", "w"),
                                  stderr=subprocess.STDOUT)
        for _ in range(100):
            if not port_free(7880):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("livekit-server did not start")
        cls.stub_port = free_port()
        stubs.INCIDENT_DELAY = 0.8
        cls.stub = stubs.serve(cls.stub_port)
        cls.room = f"e2e-{uuid.uuid4().hex[:6]}"
        env = {**os.environ, "LIVEKIT_URL": LK_URL, "LIVEKIT_API_KEY": LK_KEY, "LIVEKIT_API_SECRET": LK_SECRET,
               "LIVEKIT_ROOM": cls.room, "CLASSIFIER_URL": f"http://127.0.0.1:{cls.stub_port}/classify",
               "N8N_WEBHOOK_URL": f"http://127.0.0.1:{cls.stub_port}/webhook/chaukanna-verdict",
               "HEARTBEAT_SECONDS": "2", "CALL_END_GRACE_SECONDS": "2", "PYTHONUNBUFFERED": "1"}
        cls.bridge_log = cls.tmp / "bridge.log"
        cls.bridge = subprocess.Popen([sys.executable, str(ROOT / "bridge.py"), "--mock-stt", *cls.bridge_args()],
                                      cwd=ROOT, env=env, stdout=open(cls.bridge_log, "w"), stderr=subprocess.STDOUT)
        for _ in range(150):
            if "joined room" in cls.bridge_log.read_text():
                break
            if cls.bridge.poll() is not None:
                raise RuntimeError("bridge exited:\n" + cls.bridge_log.read_text())
            time.sleep(0.1)
        else:
            raise RuntimeError("bridge never joined:\n" + cls.bridge_log.read_text())

    @classmethod
    def bridge_args(cls) -> list[str]:
        return []

    @classmethod
    def tearDownClass(cls):
        for p in (getattr(cls, "bridge", None), getattr(cls, "lk", None)):
            if p and p.poll() is None:
                p.terminate()
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    p.kill()
        if getattr(cls, "stub", None):
            cls.stub.shutdown()
        print(f"\n[e2e logs in {cls.tmp}]", file=sys.stderr)

    def token(self, role, **kw):
        return tokens.mint(role, self.room, key=LK_KEY, secret=LK_SECRET, **kw)

    def stub_log(self) -> dict:
        with stubs.LOCK:
            return json.loads(json.dumps({k: v for k, v in stubs.STATE.items() if k != "calls"}, default=list))

    async def wait_for(self, cond, timeout, what):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return
            await asyncio.sleep(0.2)
        self.fail(f"timed out waiting for {what}\n--- bridge log tail ---\n" + self.bridge_log.read_text()[-3000:])

    async def test_two_calls_over_webrtc(self):
        victim = Victim()
        await victim.join(LK_URL, self.token("victim"))
        try:
            # ---- call 1: scam caller + victim speaking
            scam = speechlike([2.6, 2.2, 2.8, 1.6], seed=1)          # ~12 s, ends on a short tail
            victim_task = asyncio.create_task(victim.speak(speechlike([1.8, 1.5], seed=2), lead_in=4.0))
            hangup_at = {}

            async def call1():
                await robot_call(LK_URL, self.token("caller", identity="robot1", phone="+91 98765 43210",
                                                    label="CBI Officer"), scam, lead_in=1.0, linger=0.0)
                hangup_at["t"] = time.time()

            await call1()
            await self.wait_for(lambda: len(victim.of("call_ended")) >= 1, 30, "call 1 call_ended")
            await victim_task
            await self.wait_for(lambda: len(victim.of("incident")) >= 1, 10, "incident reply")

            m1 = list(victim.messages)
            started = [m for m in m1 if m["type"] == "call_started"]
            self.assertEqual(len(started), 1)
            cid1 = started[0]["call_id"]
            self.assertRegex(cid1, rf"^{self.room}-[0-9a-f]{{8}}$")
            self.assertEqual(started[0]["caller_number"], "+919876543210")
            v1 = [m for m in m1 if m["type"] == "verdict"]
            self.assertGreaterEqual(len(v1), 3)
            self.assertTrue(all(m["call_id"] == cid1 for m in v1))
            self.assertIn("victim", {m["speaker"] for m in v1}, "victim leg was not transcribed")
            self.assertIn("caller", {m["speaker"] for m in v1})
            self.assertTrue(any(m["whisper"] for m in v1), "no whisper fired")
            clips = [m["whisper_clip"] for m in v1 if m["whisper"]]
            self.assertEqual(len(clips), len(set(clips)), f"a clip was whispered twice: {clips}")
            self.assertGreaterEqual(len(victim.of("heartbeat")), 2)
            self.assertEqual(victim.of("incident")[0]["call_id"], cid1)
            self.assertIn("complaint_draft", victim.of("incident")[0])
            ended = victim.of("call_ended")[0]
            self.assertEqual(ended["call_id"], cid1)
            self.assertTrue(ended["high_risk"])

            await self.wait_for(lambda: any(e["event"] == "call_ended" for e in self.stub_log()["n8n"]), 10,
                                "n8n call_ended")
            log = self.stub_log()
            events = [e["event"] for e in log["n8n"] if e["call_id"] == cid1]
            self.assertIn(events[0], ("telemetry", "incident"))
            self.assertEqual(events.count("incident"), 1)
            self.assertEqual(events[-1], "call_ended")
            final = [e for e in log["n8n"] if e["event"] == "call_ended"][0]
            self.assertEqual({t["speaker"] for t in final["transcript"]}, {"caller", "victim"})
            self.assertIn(cid1, log["reset"])
            # the chunk cut after the hang-up (the 1.6 s tail) still reached the classifier
            late = [c for c in log["classify"] if c["call_id"] == cid1 and c["speaker"] == "caller"]
            self.assertGreaterEqual(len(late), 3)

            # ---- call 2: back to back, fresh state
            n_before = len(victim.messages)
            await robot_call(LK_URL, self.token("caller", identity="robot2", phone="+91 91234 56789",
                                                label="Courier"), speechlike([2.4, 2.0], seed=3),
                             lead_in=1.0, linger=0.0)
            await self.wait_for(lambda: len(victim.of("call_ended")) >= 2, 30, "call 2 call_ended")
            m2 = victim.messages[n_before:]
            s2 = [m for m in m2 if m["type"] == "call_started"]
            self.assertEqual(len(s2), 1)
            cid2 = s2[0]["call_id"]
            self.assertNotEqual(cid1, cid2)
            v2 = [m for m in m2 if m["type"] == "verdict"]
            self.assertTrue(v2, "call 2 produced no verdicts")
            self.assertTrue(all(m["call_id"] == cid2 for m in v2))
            # its first verdict is what that first line alone scores: nothing carried over from call 1
            alone = mock_verdict(cid2, v2[0]["chunk_text"], "en")["pressure"]
            self.assertEqual(v2[0]["pressure"], alone, "call 2 inherited call 1's pressure")

            lat = [m["latency_ms"] for m in v1 + v2 if "latency_ms" in m]
            print(f"\n[e2e] {len(lat)} verdicts, bridge latency ms: min {min(lat)} median {sorted(lat)[len(lat)//2]} "
                  f"max {max(lat)}; victim rx - bridge ts ms: "
                  f"{sorted(int((m['_rx'] - m['ts']) * 1000) for m in v1 + v2)}", file=sys.stderr)
        finally:
            await victim.leave()


if __name__ == "__main__":
    unittest.main()
