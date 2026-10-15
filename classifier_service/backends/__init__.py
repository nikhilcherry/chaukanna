import os

from backends.base import Backend, FallbackBackend, LLMContext

__all__ = ["Backend", "FallbackBackend", "LLMContext", "get_backend"]


def get_backend(name: str | None = None) -> Backend | None:
    """CLASSIFIER_BACKEND = gemini | sarvam | local_laya | mock | none.
    `none` = keyword fast path only (no LLM at all)."""
    name = (name or os.getenv("CLASSIFIER_BACKEND", "gemini")).lower().strip()
    if name in ("none", "keywords", "off", ""):
        return None
    if name == "gemini":
        from backends.gemini import GeminiBackend

        return GeminiBackend()
    if name == "sarvam":
        from backends.sarvam import SarvamBackend

        return SarvamBackend()
    if name == "local_laya":
        from backends.gemini import GeminiBackend
        from backends.local_laya import LocalLayaBackend

        return FallbackBackend(LocalLayaBackend(), GeminiBackend(), float(os.getenv("LAYA_TIMEOUT_S", "1.5")))
    if name == "mock":
        from backends.mock import MockBackend

        return MockBackend()
    raise ValueError(f"unknown CLASSIFIER_BACKEND={name!r} (gemini | sarvam | local_laya | mock | none)")
