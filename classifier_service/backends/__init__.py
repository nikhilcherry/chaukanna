import os

from backends.base import Backend


def get_backend() -> Backend:
    name = os.getenv("CLASSIFIER_BACKEND", "gemini").lower()
    if name == "gemini":
        from backends.gemini import GeminiBackend

        return GeminiBackend()
    if name == "sarvam":
        from backends.sarvam import SarvamBackend

        return SarvamBackend()
    if name == "local_laya":
        from backends.local_laya import LocalLayaBackend

        return LocalLayaBackend()
    if name == "mock":
        from backends.mock import MockBackend

        return MockBackend()
    raise ValueError(f"unknown CLASSIFIER_BACKEND={name!r} (gemini | sarvam | local_laya | mock)")
