"""Chaukanna audio bridge.

Joins a LiveKit room as a hidden observer, cuts every participant's audio into 16 kHz mono
WAV chunks in memory, transcribes them with Sarvam STT, asks the classifier for a verdict, then:

  fast path: LiveKit data message to the victim only (transcript + verdict + whisper decision)
  slow path: n8n events (telemetry / incident / escalation / call_ended), see CONTRACTS §2

A "call" starts when a caller is in the room and ends when the caller (or the victim) leaves;
each call gets its own call_id. `--replay-file call.wav` feeds a recording through the same pipeline.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time

import httpx
from dotenv import load_dotenv

import tokens
from audio import Chunk, PauseChunker, chunk_stream, load_wav_16k_mono
from config import DATA_TOPIC, GUARDIAN_IDENTITY, SAMPLE_RATE, Config, new_call_id
from pipeline import CallState, Pipeline

log = logging.getLogger("chaukanna.bridge")


def guardian_token(cfg: Config, identity: str = GUARDIAN_IDENTITY) -> str:
    return tokens.mint("guardian", cfg.room, identity, key=cfg.api_key, secret=cfg.api_secret)


def participant_info(p) -> dict:
    try:
        meta = json.loads(p.metadata) if p.metadata else {}
    except ValueError:
        meta = {}
    return meta if isinstance(meta, dict) else {}


# --------------------------------------------------------------------------- per-track consumer
class TrackConsumer:
    """One subscribed audio track: AudioStream -> chunker -> queue -> worker -> pipeline.
    Chunks are bound to the call that is active when they are cut, so a track that outlives a
    call (the victim's) feeds whichever call is current."""

    def __init__(self, session: "LiveSession", track, participant, speaker: str, sid: str) -> None:
        self.session, self.track, self.participant, self.speaker, self.sid = session, track, participant, speaker, sid
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=3)
        self.chunker = PauseChunker(**session.cfg.chunker_kw())
        self.task: asyncio.Task | None = None
        self.last_frame = time.monotonic()

    def enqueue(self, chunk: Chunk) -> None:
        st = self.session.call
        if st is None or st.ended:
            return                                            # no call in progress: nothing to judge
        now = time.monotonic()
        speech_end = now - self.chunker.lag_seconds(chunk.speech_end)
        t_start = st.rel(now - self.chunker.lag_seconds(chunk.start))
        if self.queue.full():                                 # STT is behind: drop oldest, stay live
            self.queue.get_nowait()
            self.queue.task_done()
            log.warning("%s: STT behind, dropped a queued chunk", self.speaker)
        self.queue.put_nowait((st, chunk.pcm, t_start, speech_end, now))

    async def flush(self, timeout: float = 15.0) -> None:
        """Send the buffered tail and wait until every queued chunk has been processed."""
        tail = self.chunker.tail()
        if tail:
            self.enqueue(tail)
        try:
            await asyncio.wait_for(self.queue.join(), timeout)
        except asyncio.TimeoutError:
            log.warning("%s: chunks still processing after %.0fs", self.speaker, timeout)

    async def _worker(self) -> None:
        pipe = self.session.pipe
        while True:
            st, pcm, t_start, speech_end, cut_at = await self.queue.get()
            try:
                await pipe.process_chunk(st, self.speaker, pcm, t_start, speech_end, cut_at)
            except Exception:
                log.exception("chunk processing failed")
            finally:
                self.queue.task_done()

    def stop(self, why: str) -> None:
        if self.task and not self.task.done():
            log.info("stopping %s track (%s)", self.participant.identity, why)
            self.session.stopping.add(self)                   # end_call waits for its last chunk
            self.task.cancel()
        if self.session.consumers.get(self.sid) is self:
            self.session.consumers.pop(self.sid, None)

    async def _idle_flush(self) -> None:
        """A muted or stalled track stops sending frames: cut whatever speech is buffered."""
        while True:
            await asyncio.sleep(0.25)
            if time.monotonic() - self.last_frame > 0.6 and self.chunker.frames:
                tail = self.chunker.tail()
                if tail:
                    self.enqueue(tail)

    async def run(self) -> None:
        from livekit import rtc
        worker = asyncio.create_task(self._worker())
        idle = asyncio.create_task(self._idle_flush())
        stream = rtc.AudioStream(self.track, sample_rate=SAMPLE_RATE, num_channels=1)
        log.info("subscribed to %s (%s)", self.participant.identity, self.speaker)
        try:
            async for ev in stream:
                self.last_frame = time.monotonic()
                pcm = ev.frame.data.tobytes()
                self.session.on_audio(self.speaker, pcm)
                for chunk in self.chunker.push(pcm):
                    self.enqueue(chunk)
        finally:
            idle.cancel()
            try:
                await self.flush()                            # never lose the last words of a track
            finally:
                worker.cancel()
                try:
                    await asyncio.wait_for(stream.aclose(), 2)
                except Exception:
                    pass
                if self.session.consumers.get(self.sid) is self:
                    self.session.consumers.pop(self.sid, None)
                self.session.stopping.discard(self)
                log.info("track from %s ended", self.participant.identity)


# --------------------------------------------------------------------------- room session
class LiveSession:
    """Room connection + call lifecycle. Survives reconnects: the active call, its call_id and its
    state carry over if the participants are still there when the guardian comes back."""

    def __init__(self, cfg: Config, http: httpx.AsyncClient, identity: str = GUARDIAN_IDENTITY,
                 manage_calls: bool = True, **pipe_kw) -> None:
        self.cfg, self.http, self.identity, self.manage_calls = cfg, http, identity, manage_calls
        self.room = None
        self.victim: str | None = None                        # identity of the victim in the room
        self.callers: dict[str, dict] = {}                    # identity -> {"phone", "label"}
        self.call: CallState | None = None
        self.consumers: dict[str, TrackConsumer] = {}
        self.stopping: set[TrackConsumer] = set()             # cancelled, still flushing their tail
        self.pipe = Pipeline(cfg, http, self.publish, **pipe_kw)
        self.stop = asyncio.Event()
        self.stdout = False                                   # replay --no-livekit: print messages
        self._tasks: set[asyncio.Task] = set()
        self._end_task: asyncio.Task | None = None
        self._start_after_end = False

    def on_audio(self, speaker: str, pcm: bytes) -> None:
        """Every received frame, per leg (the recorder hooks in here)."""

    def spawn(self, coro) -> asyncio.Task:
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)
        return t

    # ---- fast path ------------------------------------------------------------------------
    async def publish(self, msg: dict) -> bool:
        """Send one message to the victim only. Returns True if it went out."""
        if self.stdout:
            print(json.dumps(msg, ensure_ascii=False), flush=True)
            return True
        room, victim = self.room, self.victim
        if room is None or victim is None or not room.isconnected():
            log.debug("no victim in room, %s not delivered", msg.get("type"))
            return False
        try:
            await room.local_participant.publish_data(
                json.dumps(msg, ensure_ascii=False).encode(), reliable=True,
                destination_identities=[victim], topic=DATA_TOPIC)
            return True
        except Exception as e:                                # never let a send kill the pipeline
            log.warning("publish_data failed: %s", e)
            return False

    async def heartbeat(self) -> None:
        while True:
            st = self.call
            await self.publish({"type": "heartbeat", "call_id": st.call_id if st else "",
                                "in_call": st is not None, "ts": time.time()})
            await asyncio.sleep(self.cfg.heartbeat_seconds)

    async def send_snapshot(self, st: CallState) -> None:
        """A victim who joins (or rejoins) mid-call gets the call so far: call_started, the latest
        verdict (with the most serious warning they have not heard yet), and the incident reply."""
        await self.publish(self.pipe.call_started_msg(st))
        if st.last_message:
            clip = self.pipe.strongest_whisper(st, exclude=st.delivered_whispers)
            msg = {**st.last_message, "whisper": clip != "none", "whisper_clip": clip,
                   "recommended_whisper_clip": clip, "snapshot": True, "ts": time.time()}
            if await self.publish(msg) and clip != "none":
                st.delivered_whispers.add(clip)
        if st.incident_reply:
            await self.publish(st.incident_reply)

    # ---- roles ----------------------------------------------------------------------------
    def role_of(self, p) -> str:
        ident = p.identity or ""
        if ident.startswith(GUARDIAN_IDENTITY):
            return "guardian"
        v = self.cfg.victim_identity
        if ident == v or ident.startswith(v + "-") or participant_info(p).get("role") == "victim":
            return "victim"
        return "caller"

    def _grace(self, p) -> float:
        from livekit import rtc
        return 0.0 if getattr(p, "disconnect_reason", None) == rtc.DisconnectReason.CLIENT_INITIATED \
            else self.cfg.call_end_grace

    # ---- call lifecycle -------------------------------------------------------------------
    def start_call(self) -> None:
        if self.call is not None:
            return
        caller = next(iter(self.callers.values()), {})
        self.call = st = self.pipe.new_call(new_call_id(self.cfg.room), caller.get("phone", ""),
                                            caller_label=caller.get("label", ""))
        st.victim_seen = self.victim is not None
        self.spawn(self.publish(self.pipe.call_started_msg(st)))

    def should_end(self, st: CallState) -> bool:
        return not self.callers or (st.victim_seen and self.victim is None)

    def schedule_end(self, reason: str, grace: float) -> None:
        st = self.call
        if st is None or st.ending:
            return
        if self._end_task and not self._end_task.done():
            if grace > 0:
                return                                        # an end is already pending
            self._end_task.cancel()
        if grace:
            log.info("[%s] %s; ending in %.0fs unless they come back", st.call_id, reason, grace)
        self._end_task = self.spawn(self._end_after(st, reason, grace))

    async def _end_after(self, st: CallState, reason: str, grace: float) -> None:
        if grace:
            await asyncio.sleep(grace)
        if self.call is st and self.should_end(st):
            await self.end_call(st, reason)

    def _cancel_pending_end(self) -> None:
        st = self.call
        if self._end_task and not self._end_task.done() and st and not st.ending and not self.should_end(st):
            self._end_task.cancel()
            log.info("[%s] participant back within grace, call continues", st.call_id)

    async def end_call(self, st: CallState, reason: str = "") -> None:
        if st.ending:
            return
        st.ending = True
        log.info("[%s] ending call: %s", st.call_id, reason or "done")
        stopping = [c.task for c in self.stopping if c.task]
        await asyncio.gather(*(c.flush() for c in list(self.consumers.values())), return_exceptions=True)
        if stopping:                                          # tracks that just ended: their tail first
            await asyncio.wait(stopping, timeout=15)
        if self.call is st:
            self.call = None
        await self.pipe.end_call(st)
        if self._start_after_end and self.callers and self.manage_calls:
            self._start_after_end = False
            self.start_call()

    # ---- room events ----------------------------------------------------------------------
    def on_join(self, p) -> None:
        role = self.role_of(p)
        if role == "guardian":
            return
        st = self.call
        if role == "victim":
            if self.victim == p.identity:
                return
            self.victim = p.identity
            log.info("victim %s joined", p.identity)
            if st and not st.ending:
                st.victim_seen = True
                self._cancel_pending_end()
                self.spawn(self.send_snapshot(st))
            elif st and st.ending:
                self._start_after_end = True
            elif self.manage_calls and self.callers:
                self.start_call()
            return
        if p.identity in self.callers:
            return
        info = participant_info(p)
        self.callers[p.identity] = {"phone": info.get("phone") or p.name or p.identity,
                                    "label": info.get("label") or p.name or ""}
        log.info("caller %s joined (%s)", p.identity, self.callers[p.identity]["phone"])
        if not self.manage_calls:
            return
        if st is None:
            self.start_call()
        elif st.ending:
            self._start_after_end = True
        else:
            self._cancel_pending_end()

    def on_leave(self, p) -> None:
        self._stop_tracks_of(p.identity)
        role = self.role_of(p)
        if role == "victim" and p.identity == self.victim:
            self.victim = None
            log.info("victim %s left", p.identity)
            if self.call and self.manage_calls:
                self.schedule_end("victim left", self._grace(p))
        elif role == "caller" and self.callers.pop(p.identity, None) is not None:
            log.info("caller %s left", p.identity)
            if self.call and not self.callers and self.manage_calls:
                self.schedule_end("caller hung up", self._grace(p))

    def on_track(self, track, publication, participant) -> None:
        from livekit import rtc
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        role = self.role_of(participant)
        if role == "guardian":
            return
        self.on_join(participant)
        c = TrackConsumer(self, track, participant, role, publication.sid)
        old = self.consumers.pop(publication.sid, None)
        if old and old.task:
            old.task.cancel()
        self.consumers[publication.sid] = c
        c.task = self.spawn(c.run())

    def on_untrack(self, track, publication, participant) -> None:
        """Stop reading a track the moment it is unsubscribed. The SDK does not always end the
        AudioStream, and WebRTC can recycle the dead receiver for the next participant's track,
        so a stale reader would hear the new caller and label them with the old speaker."""
        c = self.consumers.get(publication.sid)
        if c:
            c.stop("unsubscribed")

    def _stop_tracks_of(self, identity: str) -> None:
        for c in list(self.consumers.values()):
            if c.participant.identity == identity:
                c.stop("participant left")

    def sync_presence(self, room) -> None:
        """After (re)connecting: adopt who is in the room now, forget who left while we were away."""
        present = {p.identity: p for p in room.remote_participants.values()}
        for ident in [i for i in self.callers if i not in present]:
            self.callers.pop(ident)
        if self.victim and self.victim not in present:
            self.victim = None
        for p in present.values():
            self.on_join(p)
        if self.call and self.manage_calls and self.should_end(self.call):
            self.schedule_end("participants left while the guardian was offline", 0)

    # ---- connection -----------------------------------------------------------------------
    async def connect(self, subscribe: bool = True):
        from livekit import rtc
        room = rtc.Room()
        self._disconnected = asyncio.Event()
        self._disc_reason = None

        def _disc(reason=None):
            self._disc_reason = reason
            self._disconnected.set()

        room.on("participant_connected", self.on_join)
        room.on("participant_disconnected", self.on_leave)
        room.on("disconnected", _disc)
        room.on("reconnecting", lambda: log.warning("LiveKit connection lost, reconnecting..."))
        room.on("reconnected", lambda: log.info("LiveKit reconnected"))
        if subscribe:
            room.on("track_subscribed", self.on_track)
            room.on("track_unsubscribed", self.on_untrack)
        token = os.getenv("LIVEKIT_TOKEN") or guardian_token(self.cfg, self.identity)
        await asyncio.wait_for(room.connect(self.cfg.livekit_url, token,
                                            options=rtc.RoomOptions(auto_subscribe=subscribe)), 20)
        self.room = room
        log.info("joined room %s as %s (hidden)", room.name, self.identity)
        self.sync_presence(room)
        return room

    async def close_room(self) -> None:
        room, self.room = self.room, None
        if room is not None:
            try:
                await asyncio.wait_for(room.disconnect(), 5)
            except Exception:
                pass

    async def run_once(self) -> None:
        from livekit import rtc
        await self.connect(subscribe=True)
        hb = self.spawn(self.heartbeat())
        try:
            await self._disconnected.wait()
        finally:
            hb.cancel()
            for c in list(self.consumers.values()):
                if c.task:
                    c.task.cancel()
            await self.close_room()
        if self._disc_reason == rtc.DisconnectReason.DUPLICATE_IDENTITY:
            log.error("another bridge joined room %s as %s and replaced this one; exiting "
                      "(run only one live bridge per room)", self.cfg.room, self.identity)
            self.stop.set()
        else:
            log.warning("disconnected from LiveKit (reason %s)", self._disc_reason)

    async def run_forever(self) -> None:
        delay = 1.0
        while not self.stop.is_set():
            try:
                await self.run_once()
                delay = 1.0
            except Exception as e:
                log.error("room session failed: %s: %s", type(e).__name__, e)
            if self.stop.is_set():
                break
            log.info("reconnecting in %.0fs", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 15)

    async def shutdown(self) -> None:
        if self.call and not self.call.ending:
            await self.end_call(self.call, "bridge shutting down")
        await self.pipe.drain(timeout=10)
        await self.close_room()


# --------------------------------------------------------------------------- replay mode
def replay_chunks(cfg: Config, args) -> list[tuple[float, str, float, float, bytes]]:
    """(end_s, speaker, start_s, speech_end_s, pcm) per chunk, cut exactly as the live path would."""
    pcm = load_wav_16k_mono(args.replay_file)
    out = []
    for c in chunk_stream(pcm, **cfg.chunker_kw()):
        out.append((c.end / SAMPLE_RATE, args.replay_speaker, c.start / SAMPLE_RATE, c.speech_end / SAMPLE_RATE, c.pcm))
    return sorted(out, key=lambda x: x[0])


async def run_replay(cfg: Config, http: httpx.AsyncClient, args) -> CallState:
    session = LiveSession(cfg, http, identity=GUARDIAN_IDENTITY + "-replay", manage_calls=False)
    items = replay_chunks(cfg, args)
    log.info("replay: %d chunks from %s at %.1fx", len(items), args.replay_file, args.speed)
    hb = None
    if args.no_livekit:
        session.stdout = True
    else:
        try:
            await session.connect(subscribe=False)
            hb = session.spawn(session.heartbeat())
        except Exception as e:
            log.warning("replay: LiveKit unavailable (%s: %s) - messages print to stdout only", type(e).__name__, e)
            await session.close_room()
            session.stdout = True

    st = session.pipe.new_call(args.call_id or new_call_id(cfg.room), args.caller_number,
                               victim_id=args.victim_id, caller_label=args.caller_label)
    session.call = st
    st.victim_seen = True
    await session.publish(session.pipe.call_started_msg(st))

    queues: dict[str, asyncio.Queue] = {}

    async def worker(q: asyncio.Queue, speaker: str) -> None:
        while True:
            pcm, t_start, speech_end, cut_at = await q.get()
            try:
                await session.pipe.process_chunk(st, speaker, pcm, t_start, speech_end, cut_at)
            except Exception:
                log.exception("chunk processing failed")
            finally:
                q.task_done()

    workers = []
    t0 = time.monotonic()
    try:
        for end_s, speaker, start_s, speech_end_s, pcm in items:
            await asyncio.sleep(max(0.0, t0 + end_s / args.speed - time.monotonic()))   # real-time pacing
            if speaker not in queues:
                queues[speaker] = asyncio.Queue()
                workers.append(asyncio.create_task(worker(queues[speaker], speaker)))
            queues[speaker].put_nowait((pcm, start_s, t0 + speech_end_s / args.speed, time.monotonic()))
        for q in queues.values():
            await q.join()
        await session.end_call(st, "replay finished")
        await session.pipe.drain()
    finally:
        for w in workers:
            w.cancel()
        if hb:
            hb.cancel()
        await session.close_room()
    return st


# --------------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Chaukanna LiveKit audio bridge")
    ap.add_argument("--replay-file", help="WAV to feed through the pipeline instead of live room audio")
    ap.add_argument("--replay-speaker", choices=["caller", "victim"], default="caller",
                    help="speaker for a mono replay file")
    ap.add_argument("--caller-number", default="+919876543210")
    ap.add_argument("--caller-label", default="CBI Officer (replay)")
    ap.add_argument("--victim-id", default="")
    ap.add_argument("--call-id", help="override the replay call id (default: <room>-<uuid8>)")
    ap.add_argument("--speed", type=float, default=1.0, help="replay speed factor (1.0 = real time)")
    ap.add_argument("--no-livekit", action="store_true", help="replay without joining a room; print messages")
    ap.add_argument("--mock-stt", action="store_true", help="skip Sarvam; canned transcript (wiring tests)")
    ap.add_argument("--verbose", "-v", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = Config.from_env()
    cfg.mock_stt = args.mock_stt

    missing = []
    if not cfg.mock_stt and not cfg.sarvam_key:
        missing.append("SARVAM_API_KEY")
    if not args.replay_file and not cfg.livekit_url:
        missing.append("LIVEKIT_URL")
    if not args.replay_file and not os.getenv("LIVEKIT_TOKEN") and not (cfg.api_key and cfg.api_secret):
        missing.append("LIVEKIT_API_KEY/LIVEKIT_API_SECRET")
    if missing:                                                # replay degrades to stdout without LiveKit
        print("missing config: " + ", ".join(missing), file=sys.stderr)
        return 2
    if not cfg.n8n_url:
        log.warning("N8N_WEBHOOK_URL is not set: no n8n events will be sent")

    async def go() -> None:
        async with httpx.AsyncClient() as http:
            if args.replay_file:
                await run_replay(cfg, http, args)
                return
            session = LiveSession(cfg, http)
            try:
                await session.run_forever()
            finally:
                await session.shutdown()

    try:
        asyncio.run(go())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
