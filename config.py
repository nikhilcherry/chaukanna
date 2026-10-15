"""Constants and env-driven configuration shared by every bridge module."""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

SAMPLE_RATE = 16000
CHUNK_SECONDS = 4
CHUNK_BYTES = SAMPLE_RATE * CHUNK_SECONDS * 2          # int16 mono -> 128,000
MIN_FLUSH_BYTES = SAMPLE_RATE * 2                      # flush a track tail only if >= 1 s
DATA_TOPIC = "chaukanna.verdict"
GUARDIAN_IDENTITY = "chaukanna-guardian"
SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"

# Higher = more serious. Unknown clip names from a newer classifier rank 1.
CLIP_SEVERITY = {"none": 0, "warn_secrecy": 1, "warn_digital_arrest": 2, "warn_known_scammer": 3, "warn_otp": 4}


def env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


def new_call_id(room: str) -> str:
    """A fresh id per call, so the classifier's never-decreasing pressure starts at 0 again."""
    return f"{room}-{uuid.uuid4().hex[:8]}"


@dataclass
class Config:
    livekit_url: str = ""
    api_key: str = ""
    api_secret: str = ""
    room: str = "chaukanna"
    victim_identity: str = "victim"
    victim_id: str = "demo-victim-1"
    sarvam_key: str = ""
    stt_model: str = "saaras:v3"
    stt_mode: str = "transcribe"
    classifier_url: str = "http://localhost:8010/classify"
    n8n_url: str = ""
    n8n_pressure: int = 2
    n8n_incident_timeout: float = 45.0
    whisper_cooldown: float = 20.0
    call_end_grace: float = 6.0
    heartbeat_seconds: float = 5.0
    silence_rms: float = 120.0
    mock_stt: bool = False

    @classmethod
    def from_env(cls) -> "Config":
        e = os.getenv
        return cls(
            livekit_url=e("LIVEKIT_URL", ""),
            api_key=e("LIVEKIT_API_KEY", ""),
            api_secret=e("LIVEKIT_API_SECRET", ""),
            room=e("LIVEKIT_ROOM", "chaukanna"),
            victim_identity=e("VICTIM_IDENTITY", "victim"),
            victim_id=e("VICTIM_ID", "demo-victim-1"),
            sarvam_key=e("SARVAM_API_KEY", ""),
            stt_model=e("SARVAM_STT_MODEL", "saaras:v3"),
            stt_mode=e("SARVAM_STT_MODE", "transcribe"),
            classifier_url=e("CLASSIFIER_URL", "http://localhost:8010/classify"),
            n8n_url=e("N8N_WEBHOOK_URL", ""),
            n8n_pressure=int(e("N8N_PRESSURE_THRESHOLD", "2")),
            n8n_incident_timeout=float(e("N8N_INCIDENT_TIMEOUT_SECONDS", "45")),
            whisper_cooldown=float(e("WHISPER_COOLDOWN_SECONDS", "20")),
            call_end_grace=float(e("CALL_END_GRACE_SECONDS", "6")),
            heartbeat_seconds=float(e("HEARTBEAT_SECONDS", "5")),
            silence_rms=float(e("SILENCE_RMS", "120")),
        )

    @property
    def reset_url_base(self) -> str:
        """http://host:8010/classify -> http://host:8010/reset"""
        u = self.classifier_url.rstrip("/")
        return (u[: -len("/classify")] if u.endswith("/classify") else u) + "/reset"
