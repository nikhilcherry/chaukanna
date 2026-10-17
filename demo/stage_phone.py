"""Helpers for the phone-call stage demo (demo/stage.sh phone ...).

In phone mode the scammer really dials Kamala's SIM. When she answers, the app's call tap (PR #1,
`CallTap`) joins the LiveKit room as `caller-phone` with the caller's number, and the bridge starts a
call log in calls/. These helpers watch that log, so stage.sh knows when to start the recording and
when the call is over.

    python demo/stage_phone.py wait-call --since 1792250000 --number +919876543210 --timeout 45
    python demo/stage_phone.py wait-end --call-id chaukanna-1a2b3c4d --timeout 20
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CALLS = Path(os.getenv("CALL_LOG_DIR") or HERE.parent / "calls")


def last10(number: str) -> str:
    return re.sub(r"\D", "", number or "")[-10:]


def first_record(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            line = f.readline()
        return json.loads(line) if line.endswith("\n") else {}
    except (OSError, ValueError):
        return {}


def wait_call(since: float, number: str, timeout: float) -> str | None:
    """The first call that started after `since` from `number` (any number if the phone hid it)."""
    want = last10(number)
    end = time.time() + timeout
    while time.time() < end:
        for p in sorted(CALLS.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:10]:
            if p.stat().st_mtime < since:
                continue
            rec = first_record(p)
            if rec.get("type") != "call_started" or rec.get("ts", 0) < since:
                continue
            got = last10(rec.get("caller_number", ""))
            if not want or not got or got == want:
                return p.stem
        time.sleep(0.25)
    return None


def wait_end(call_id: str, timeout: float) -> bool:
    end = time.time() + timeout
    p = CALLS / f"{call_id}.jsonl"
    while time.time() < end:
        try:
            if '"type": "call_ended"' in p.read_text(encoding="utf-8"):
                return True
        except OSError:
            pass
        time.sleep(0.5)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("wait-call")
    w.add_argument("--since", type=float, required=True)
    w.add_argument("--number", default="")
    w.add_argument("--timeout", type=float, default=45)
    e = sub.add_parser("wait-end")
    e.add_argument("--call-id", required=True)
    e.add_argument("--timeout", type=float, default=20)
    a = ap.parse_args()
    if a.cmd == "wait-call":
        cid = wait_call(a.since, a.number, a.timeout)
        if cid:
            print(cid)
        return 0 if cid else 1
    return 0 if wait_end(a.call_id, a.timeout) else 1


if __name__ == "__main__":
    sys.exit(main())
