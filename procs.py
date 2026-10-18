"""Find and stop the demo's own processes by their argv, never by a pattern in some shell's command line.

    python procs.py running bridge.py            # exit 0 if <python> <repo>/bridge.py is up
    python procs.py stop tools/ai_scammer.py     # SIGTERM each one; prints how many

A process counts only when argv[0] is a python and argv[1] resolves (from its cwd) to this repo's script, so
`grep bridge.py` or a Claude shell that mentions it never matches, and another project's bridge.py neither.
"""
from __future__ import annotations

import os
import signal
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def find(script: str) -> list[int]:
    want = (HERE / script).resolve()
    out = []
    for p in Path("/proc").iterdir():
        if not p.name.isdigit() or int(p.name) == os.getpid():
            continue
        try:
            argv = (p / "cmdline").read_bytes().split(b"\0")
            if len(argv) < 2 or not os.path.basename(argv[0]).startswith(b"python"):
                continue
            if (Path(os.readlink(p / "cwd")) / os.fsdecode(argv[1])).resolve() == want:
                out.append(int(p.name))
        except OSError:
            continue
    return out


def stop(script: str, sig: int = signal.SIGTERM) -> int:
    n = 0
    for pid in find(script):
        try:
            os.kill(pid, sig)
            n += 1
        except OSError:
            pass
    return n


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("running", "stop"):
        sys.exit(__doc__)
    if sys.argv[1] == "running":
        sys.exit(0 if find(sys.argv[2]) else 1)
    print(stop(sys.argv[2]))
