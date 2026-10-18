"""Judge demo: call the victim phone from the laptop with the pre-recorded slow-burn scam call.
Joins the room as a caller with a fresh random number (so it is never already a "known scammer"),
plays demo/scam_call_slow_burn.wav in real time, then hangs up. The live bridge does the rest.
Usage: .venv/bin/python demo/play_demo_call.py [wav]"""
import asyncio, os, random, sys, wave
from datetime import timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(HERE.parent / ".env")
import tokens  # noqa: E402
from livekit import api, rtc  # noqa: E402


async def main() -> None:
    wav = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "scam_call_slow_burn.wav"
    room_name = os.getenv("LIVEKIT_ROOM", "chaukanna")
    lk = api.LiveKitAPI(os.environ["LIVEKIT_URL"].replace("wss://", "https://"), os.environ["LIVEKIT_API_KEY"],
                        os.environ["LIVEKIT_API_SECRET"])
    who = {p.identity for p in (await lk.room.list_participants(api.ListParticipantsRequest(room=room_name))).participants}
    await lk.aclose()
    if "victim" not in who:
        sys.exit("The victim phone is not in the room: open the Chaukanna app on it (it should say Protected).")
    if "chaukanna-guardian" not in who:
        sys.exit("The guardian (bridge.py) is not in the room: start it first.")

    number = f"+91 9{random.randint(100, 999)} {random.randint(10000, 99999)}"
    tok = tokens.mint("caller", room_name, identity=f"demo-{random.randint(1000, 9999)}", phone=number,
                      label=number, ttl=timedelta(minutes=10))
    with wave.open(str(wav)) as w:
        sr, pcm = w.getframerate(), w.readframes(w.getnframes())
    room = rtc.Room()
    await room.connect(os.environ["LIVEKIT_URL"], tok)
    source = rtc.AudioSource(sr, 1)
    track = rtc.LocalAudioTrack.create_audio_track("caller-mic", source)
    await room.local_participant.publish_track(track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
    print(f"Calling the victim from {number} ...", flush=True)
    await asyncio.sleep(2.0)                      # let the phone pick up and the bridge subscribe
    step = sr // 100                              # 10 ms frames, real time
    for i in range(0, len(pcm) // 2, step):
        chunk = pcm[i * 2:(i + step) * 2]
        n = len(chunk) // 2
        frame = rtc.AudioFrame.create(sr, 1, n)
        frame.data[:n] = memoryview(chunk).cast("h")
        await source.capture_frame(frame)
    await asyncio.sleep(4.0)                      # let the last line reach the guardian
    await room.disconnect()
    print("Caller hung up.", flush=True)


asyncio.run(main())
os._exit(0)   # skip the LiveKit FFI finalizers, which print a harmless traceback at interpreter exit
