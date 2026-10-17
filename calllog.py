"""Per-call event log for the console (console/index.html, served by token_server.py at /console).

Every message the bridge sends the victim, plus the n8n events it fires, is appended as one JSON
line to `<CALL_LOG_DIR>/<call_id>.jsonl`. The console replays a finished file, or follows a call
that is still going by polling the file. Heartbeats and late-joiner snapshots are left out (they
repeat what is already there). Victim OTP digits are masked before they get here (pipeline.mask_otp).
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

log = logging.getLogger("chaukanna.calllog")
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
SKIP = {"heartbeat"}


class CallLog:
    def __init__(self, directory: str | Path | None) -> None:
        self.dir = Path(directory) if directory else None
        self._warned = False

    def write(self, msg: dict) -> None:
        """Append one record. Never raises: the console must not be able to break a call."""
        if self.dir is None or not isinstance(msg, dict) or msg.get("type") in SKIP or msg.get("snapshot"):
            return
        call_id = str(msg.get("call_id") or "")
        if not SAFE_ID.match(call_id):
            return
        rec = {**msg, "logged": round(time.time(), 3)}
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            with open(self.dir / f"{call_id}.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except (OSError, TypeError, ValueError) as e:
            if not self._warned:
                log.warning("call log not written to %s (%s); the console will not see calls", self.dir, e)
                self._warned = True

    def status(self, state: dict) -> None:
        """The bridge's heartbeat (`_bridge.json`): the console reads its age to tell whether the
        bridge is in the LiveKit room, and whether the victim's phone is connected."""
        if self.dir is None:
            return
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.dir / "_bridge.json.tmp"
            tmp.write_text(json.dumps({**state, "ts": round(time.time(), 3)}))
            tmp.replace(self.dir / STATUS_FILE)
        except OSError:
            pass


STATUS_FILE = "_bridge.json"


def read_status(directory: str | Path) -> dict | None:
    try:
        return json.loads((Path(directory) / STATUS_FILE).read_text())
    except (OSError, ValueError):
        return None


def read_call(directory: str | Path, call_id: str, start: int = 0) -> list[dict] | None:
    """Records of one call from line `start` on; None if there is no such call. A half-written last
    line (the bridge is mid-append) is left for the next poll."""
    if not SAFE_ID.match(call_id):
        return None
    p = Path(directory) / f"{call_id}.jsonl"
    if not p.is_file():
        return None
    out = []
    with open(p, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i < start:
                continue
            if not line.endswith("\n"):
                break
            try:
                out.append(json.loads(line))
            except ValueError:
                out.append({"type": "unreadable"})        # keep line numbers aligned with `start`
    return out


def summarize(directory: str | Path, limit: int = 60) -> list[dict]:
    """Newest calls first, one row each, for the console's call list."""
    d = Path(directory)
    if not d.is_dir():
        return []
    files = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    rows = []
    for p in files:
        recs = read_call(d, p.stem) or []
        start = next((r for r in recs if r.get("type") == "call_started"), {})
        verdicts = [r for r in recs if r.get("type") == "verdict"]
        last = verdicts[-1] if verdicts else {}
        ended = next((r for r in recs if r.get("type") == "call_ended"), None)
        rows.append({
            "call_id": p.stem,
            "started": start.get("ts") or (recs[0].get("logged") if recs else p.stat().st_mtime),
            "caller_number": start.get("caller_number", ""),
            "caller_label": start.get("caller_label", ""),
            "known_scammer": bool(start.get("known_scammer") or last.get("known_scammer")),
            "peak_pressure": max([int(v.get("pressure") or 0) for v in verdicts] or [0]),
            "scam_type": last.get("scam_type", "none"),
            "chunks": len(verdicts),
            "incident": any(r.get("type") == "incident" for r in recs),
            "ended": ended is not None,
            "duration_seconds": (ended or {}).get("duration_seconds"),
            "updated": p.stat().st_mtime,
        })
    return rows
