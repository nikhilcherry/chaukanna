import os

from backends.base import Backend, FallbackBackend, LLMContext

__all__ = ["Backend", "FallbackBackend", "LLMContext", "get_backend"]


def get_backend(name: str | None = None) -> Backend | None:
    """CLASSIFIER_BACKEND = auto (default) | jev | gemini | sarvam | local_laya | mock | none (| jev_only).
    `none` = keyword fast path only (no LLM at all)."""
    name = (name or os.getenv("CLASSIFIER_BACKEND", "auto")).lower().strip()
    if name == "auto":  # the eval winner first: Jev (+ Gemini fallback), else Gemini, else keywords only
        name = "jev" if os.getenv("TYPESAFE_API_KEY") else "gemini" if (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")) else "none"
    if name in ("none", "keywords", "off", ""):
        return None
    if name == "jev":  # Jev first (~0.5 s), Gemini if it errors, backs off or takes > 1.5 s
        from backends.gemini import GeminiBackend
        from backends.jev import JevBackend

        return FallbackBackend(JevBackend(), GeminiBackend(), float(os.getenv("JEV_TIMEOUT_S", "1.5")))
    if name == "jev_only":
        from backends.jev import JevBackend

        return JevBackend()
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
    raise ValueError(f"unknown CLASSIFIER_BACKEND={name!r} (jev | jev_only | gemini | sarvam | local_laya | mock | none)")
