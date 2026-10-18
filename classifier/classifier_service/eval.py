"""Evaluate the classifier on the labelled conversations in evalset/.

    python eval.py                                   # none (keywords only) + jev_only + gemini
    python eval.py --backends none,gemini:gemini-2.5-flash-lite --no-cache
    python eval.py --show-fails                      # per-conversation misses / false alarms

Each conversation is replayed chunk by chunk through the real Engine (in process). After each
chunk the eval waits for the background LLM run to finish, which is what the ~4 s gap between
live chunks does, so a model's verdict reaches the *next* chunk exactly as in production.

Reported per backend:
  scams  : detected (peak pressure >= 2), first chunk reaching pressure 2 (median), on time
           (by the labelled critical chunk), final scam_type accuracy
  legit  : false-alarm rate (pressure >= 2 = n8n incident + family paged), soft rate (>= 1),
           calls with any whisper
  latency: /classify response p50/p95 (what the bridge waits for) and background model p50/p95
  'model alone' rows replay the old design: block on the model, ratchet its verdicts, no keywords.

Model answers are cached in evalset/.cache/ (with their measured latency, replayed on a hit) so
re-running after keyword changes costs no API calls. Jev is capped at 3 concurrent requests.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import statistics
import time
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")
os.environ.setdefault("WARMUP", "0")

from backends import get_backend  # noqa: E402
from backends.base import Backend, LLMContext  # noqa: E402
from callers import CallerRegistry  # noqa: E402
from engine import Engine, Settings  # noqa: E402
from schemas import ClassifyRequest, LLMVerdict  # noqa: E402

EVALSET = HERE / "evalset"
CACHE = EVALSET / ".cache"


def load_set() -> list[dict]:
    convs = []
    for f in sorted(EVALSET.glob("*.json")):
        if f.name.startswith("results"):
            continue
        for c in json.loads(f.read_text()):
            c["is_scam"] = not c["category"].startswith("legit")
            c["split"] = "holdout" if f.stem == "holdout" else "tune"
            convs.append(c)
    return convs


def pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


class Cached(Backend):
    """Disk cache around a backend keyed by (backend, prompt version, snapshot). Replays the
    recorded latency on a hit so the engine behaves exactly as it did live."""

    def __init__(self, inner: Backend, tag: str, use_cache: bool) -> None:
        super().__init__()
        self.inner, self.tag, self.use = inner, tag, use_cache
        self.name = inner.name
        self.path = CACHE / f"{tag}.json"
        self.data = json.loads(self.path.read_text()) if use_cache and self.path.exists() else {}
        self.real_ms: list[float] = []
        self.replayed_ms: list[float] = []  # live latencies recorded with cached answers
        self.hits = 0

    def key(self, ctx: LLMContext) -> str:
        from backends.jev import QUESTIONS
        from prompt import SYSTEM_PROMPT

        version = SYSTEM_PROMPT if "gemini" in self.tag else json.dumps(QUESTIONS, sort_keys=True)
        raw = json.dumps([version, ctx.caller_number, ctx.chunks, ctx.earlier, ctx.language], ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()[:24]

    async def classify(self, ctx: LLMContext) -> LLMVerdict:
        k = self.key(ctx)
        raw_mode = hasattr(self.inner, "ask")  # Jev: cache raw answers, re-map on every run
        if self.use and k in self.data:
            self.hits += 1
            row = self.data[k]
            await asyncio.sleep(row["ms"] / 1000)
            self.replayed_ms.append(row["ms"])
            self.last_used = row.get("used", self.inner.name)
            return self.inner.to_verdict(row["raw"], ctx) if raw_mode else LLMVerdict.model_validate(row["v"])
        t = time.perf_counter()
        if raw_mode:
            raw = await self.inner.ask(ctx)
            v = self.inner.to_verdict(raw, ctx)
        else:
            v = await self.inner.classify(ctx)
        ms = (time.perf_counter() - t) * 1000
        self.real_ms.append(ms)
        self.last_used = getattr(self.inner, "last_used", self.inner.name)
        self.data[k] = {"ms": round(ms, 1), "used": self.last_used, **({"raw": raw} if raw_mode else {"v": v.model_dump()})}
        return v

    def save(self) -> None:
        if self.use:
            CACHE.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, ensure_ascii=False))

    async def aclose(self) -> None:
        await self.inner.aclose()


def build(spec: str, use_cache: bool) -> tuple[str, Backend | None]:
    name, _, model = spec.partition(":")
    if name == "none":
        return "keywords only", None
    if name == "gemini":
        from backends.gemini import GeminiBackend

        g = GeminiBackend(model or None)
        return f"keywords + {g.model}", Cached(g, f"gemini-{g.model}", use_cache)
    inner = get_backend(name)
    return f"keywords + {name}", Cached(inner, name, use_cache)


async def run_conv(engine: Engine, conv: dict, policy: str) -> dict:
    call_id = f"eval-{conv['id']}"
    engine.reset(call_id)
    rows = []
    llm_only_p, llm_only_peak = [], 0
    for i, (speaker, lang, text) in enumerate(conv["chunks"], 1):
        v = await engine.classify(ClassifyRequest(call_id=call_id, caller_number=conv.get("caller_number", ""),
                                                  speaker=speaker, chunk_text=text, language=lang))
        st = engine.calls.get(call_id)
        if st and st.llm_task:
            try:
                await asyncio.wait_for(asyncio.shield(st.llm_task), timeout=15)
            except Exception:
                pass
        if st and st.llm:
            llm_only_peak = max(llm_only_peak, st.llm.pressure)
        llm_only_p.append(llm_only_peak)
        rows.append({"i": i, "speaker": speaker, "pressure": v.pressure, "type": v.scam_type, "clip": v.recommended_whisper_clip,
                     "source": v.source, "ms": v.latency_ms, "degraded": v.degraded})
    final = rows[-1]
    first2 = next((r["i"] for r in rows if r["pressure"] >= 2), None)
    llm_first2 = next((i + 1 for i, p in enumerate(llm_only_p) if p >= 2), None)
    st = engine.calls.get(call_id)
    llm_type = st.llm.scam_type if st and st.llm else None
    engine.reset(call_id)
    return {"id": conv["id"], "split": conv["split"], "is_scam": conv["is_scam"], "category": conv["category"], "lang": conv["lang"],
            "critical": conv.get("critical_chunk"), "peak": max(r["pressure"] for r in rows), "first_p2": first2,
            "final_type": final["type"], "accept": conv.get("accept_types", [conv.get("expected_scam_type", "none")]),
            "type_ok": final["type"] in conv.get("accept_types", [conv.get("expected_scam_type", "none")]),
            "whispers": [r["clip"] for r in rows if r["clip"] != "none"], "ms": [r["ms"] for r in rows],
            "llm_peak": llm_only_p[-1] if llm_only_p else 0, "llm_first_p2": llm_first2, "llm_type": llm_type,
            "degraded": any(r["degraded"] for r in rows), "trace": [r["pressure"] for r in rows]}


def summarize(results: list[dict], model_ms: list[float], label: str, has_model: bool) -> dict:
    scams = [r for r in results if r["is_scam"]]
    legit = [r for r in results if not r["is_scam"]]
    det = [r for r in scams if r["first_p2"]]
    s = {
        "label": label, "n_scam": len(scams), "n_legit": len(legit),
        "detected": len(det), "on_time": sum(1 for r in det if r["first_p2"] <= r["critical"]),
        "median_first_p2": statistics.median([r["first_p2"] for r in det]) if det else None,
        "mean_delay_vs_critical": round(statistics.mean([r["first_p2"] - r["critical"] for r in det]), 2) if det else None,
        "type_acc": sum(r["type_ok"] for r in scams), "false_alarms": sum(1 for r in legit if r["peak"] >= 2),
        "soft_alarms": sum(1 for r in legit if r["peak"] >= 1), "legit_whispers": sum(1 for r in legit if r["whispers"]),
        "classify_p50_ms": pct([m for r in results for m in r["ms"]], 0.5), "classify_p95_ms": pct([m for r in results for m in r["ms"]], 0.95),
        "model_p50_ms": pct(model_ms, 0.5), "model_p95_ms": pct(model_ms, 0.95), "model_calls_measured": len(model_ms),
        "degraded_convs": sum(r["degraded"] for r in results),
    }
    if has_model:
        mdet = [r for r in scams if r["llm_first_p2"]]
        s["model_alone"] = {
            "detected": len(mdet), "on_time": sum(1 for r in mdet if r["llm_first_p2"] <= r["critical"]),
            "median_first_p2": statistics.median([r["llm_first_p2"] for r in mdet]) if mdet else None,
            "false_alarms": sum(1 for r in legit if r["llm_peak"] >= 2),
            "type_acc": sum(1 for r in scams if r["llm_type"] in r["accept"]),
        }
    return s


def fmt(v, unit=""):
    return "-" if v is None else (f"{v:.0f}{unit}" if isinstance(v, float) else f"{v}{unit}")


def print_table(summaries: list[dict]) -> None:
    for split in ("tune", "holdout", "all"):
        rows = [s for s in summaries if s.get("split") == split]
        if rows:
            print(f"\n### {split} set ({rows[0]['n_scam']} scam / {rows[0]['n_legit']} legit calls)")
            _table(rows)


def _table(summaries: list[dict]) -> None:
    print("| backend | scams caught (p>=2) | on time | median first p2 chunk | type correct | legit false alarms (p>=2) | legit p>=1 | /classify p50 / p95 | model p50 / p95 |")
    print("|---|---|---|---|---|---|---|---|---|")
    for s in summaries:
        print(f"| {s['label']} | {s['detected']}/{s['n_scam']} | {s['on_time']}/{s['n_scam']} | {fmt(s['median_first_p2'])} | "
              f"{s['type_acc']}/{s['n_scam']} | {s['false_alarms']}/{s['n_legit']} | {s['soft_alarms']}/{s['n_legit']} | "
              f"{fmt(s['classify_p50_ms'], ' ms')} / {fmt(s['classify_p95_ms'], ' ms')} | {fmt(s['model_p50_ms'], ' ms')} / {fmt(s['model_p95_ms'], ' ms')} |")
        m = s.get("model_alone")
        if m:
            print(f"| &nbsp;&nbsp;{s['label'].split('+ ')[-1]} alone, blocking | {m['detected']}/{s['n_scam']} | {m['on_time']}/{s['n_scam']} | "
                  f"{fmt(m['median_first_p2'])} | {m['type_acc']}/{s['n_scam']} | {m['false_alarms']}/{s['n_legit']} | - | = model latency | |")


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backends", default="none,jev_only,gemini")
    ap.add_argument("--policy", default=os.getenv("DELIVERY_OTP_POLICY", "caution"))
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--parallel", type=int, default=3, help="conversations in flight (Jev is capped at 3 requests anyway)")
    ap.add_argument("--only", help="comma-separated conversation ids")
    ap.add_argument("--show-fails", action="store_true")
    ap.add_argument("--out", default=str(EVALSET / "results.json"))
    a = ap.parse_args()

    convs = load_set()
    if a.only:
        convs = [c for c in convs if c["id"] in a.only.split(",")]
    print(f"{len(convs)} conversations ({sum(c['is_scam'] for c in convs)} scam / {sum(not c['is_scam'] for c in convs)} legit), "
          f"delivery-OTP policy: {a.policy}")
    summaries, all_results = [], {}
    for spec in a.backends.split(","):
        label, backend = build(spec.strip(), not a.no_cache)
        engine = Engine(backend, Settings(delivery_otp_policy=a.policy, llm_timeout_s=8.0), CallerRegistry())
        sem = asyncio.Semaphore(a.parallel)

        async def one(c):
            async with sem:
                return await run_conv(engine, c, a.policy)

        t = time.perf_counter()
        results = await asyncio.gather(*(one(c) for c in convs))
        model_ms = backend.real_ms + backend.replayed_ms if isinstance(backend, Cached) else []
        if isinstance(backend, Cached):
            backend.save()
            print(f"  {label}: {time.perf_counter() - t:.0f}s, {len(backend.real_ms)} live model calls, {backend.hits} cache hits")
        if backend:
            await backend.aclose()
        s = summarize(results, model_ms, label, backend is not None)
        s["split"] = "all"
        summaries.append(s)
        for split in ("tune", "holdout"):
            part = [r for r in results if r["split"] == split]
            if part:
                ps = summarize(part, model_ms, label, backend is not None)
                ps["split"] = split
                summaries.append(ps)
        all_results[label] = results
        if a.show_fails:
            for r in results:
                bad = (r["is_scam"] and (not r["first_p2"] or r["first_p2"] > r["critical"] or not r["type_ok"])) or \
                      (not r["is_scam"] and r["peak"] >= 1)
                if bad:
                    print(f"    {'SCAM ' if r['is_scam'] else 'LEGIT'} {r['id']:38} trace={r['trace']} crit={r['critical']} "
                          f"type={r['final_type']} ok={r['type_ok']} model_peak={r['llm_peak']} whispers={r['whispers']}")
    print_table(summaries)
    Path(a.out).write_text(json.dumps({"policy": a.policy, "summaries": summaries, "results": all_results}, indent=1, ensure_ascii=False))
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    asyncio.run(main())
