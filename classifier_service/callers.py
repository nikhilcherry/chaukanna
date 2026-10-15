"""Caller-number risk: a known-scam number list plus scam-compound country codes."""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("classifier.callers")
DATA = Path(__file__).resolve().parent / "data"


def normalize_number(raw: str) -> str:
    """Best-effort E.164: '+91 98765-43210', '09876543210', '9876543210', '0091...' -> '+919876543210'."""
    s = (raw or "").strip()
    digits = re.sub(r"\D", "", s)
    if not digits:
        return ""
    if s.startswith("+"):
        return "+" + digits
    if digits.startswith("00"):
        return "+" + digits[2:]
    if len(digits) == 10 and digits[0] in "6789":
        return "+91" + digits
    if len(digits) == 11 and digits.startswith("0"):
        return "+91" + digits[1:]
    if len(digits) == 12 and digits.startswith("91"):
        return "+" + digits
    return "+" + digits


@dataclass
class CallerRisk:
    kind: str  # "listed" | "risky_country_code"
    reason: str
    scam_type: str | None = None


class CallerRegistry:
    def __init__(self, seed: Path | None = None, codes: Path | None = None, local: Path | None = None) -> None:
        self.seed = Path(seed or os.getenv("SCAM_NUMBERS_FILE", DATA / "scam_numbers.json"))
        self.codes_file = Path(codes or os.getenv("RISKY_CODES_FILE", DATA / "risky_country_codes.json"))
        self.local = Path(local or os.getenv("SCAM_NUMBERS_LOCAL_FILE", DATA / "scam_numbers.local.json"))
        self._lock = threading.Lock()
        self.numbers: dict[str, dict] = {}
        self.codes: dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        numbers: dict[str, dict] = {}
        for path in (self.seed, self.local):
            try:
                for row in json.loads(path.read_text()).get("numbers", []):
                    n = normalize_number(row.get("number", ""))
                    if n:
                        numbers[n] = {**row, "number": n}
            except FileNotFoundError:
                pass
            except Exception as e:  # a broken data file must not take the service down
                log.warning("could not load %s: %s", path, e)
        try:
            codes = json.loads(self.codes_file.read_text()).get("codes", {})
        except Exception as e:
            log.warning("could not load %s: %s", self.codes_file, e)
            codes = {}
        with self._lock:
            self.numbers = numbers
            self.codes = {("+" + c.lstrip("+")): name for c, name in codes.items()}

    def check(self, raw: str) -> CallerRisk | None:
        n = normalize_number(raw)
        if not n:
            return None
        row = self.numbers.get(n)
        if row:
            what = (row.get("scam_type") or "scam").replace("_", " ")
            return CallerRisk("listed", f"caller number {n} is on the Chaukanna scam list ({what})", row.get("scam_type"))
        for code in sorted(self.codes, key=len, reverse=True):
            if n.startswith(code):
                return CallerRisk("risky_country_code", f"caller number {n} is from {code} ({self.codes[code]}), a common scam-call origin")
        return None

    def _save_local(self) -> None:
        seed = set()
        try:
            seed = {normalize_number(r.get("number", "")) for r in json.loads(self.seed.read_text()).get("numbers", [])}
        except Exception:
            pass
        rows = [r for n, r in self.numbers.items() if n not in seed]
        try:
            self.local.write_text(json.dumps({"numbers": rows}, indent=2, ensure_ascii=False))
        except OSError as e:
            log.warning("could not persist %s: %s", self.local, e)

    def add(self, raw: str, scam_type: str | None = None, note: str = "") -> str:
        n = normalize_number(raw)
        if not n:
            raise ValueError("empty number")
        with self._lock:
            self.numbers[n] = {"number": n, "scam_type": scam_type, "note": note}
            self._save_local()
        return n

    def remove(self, raw: str) -> bool:
        n = normalize_number(raw)
        with self._lock:
            found = self.numbers.pop(n, None) is not None
            if found:
                self._save_local()
        return found
