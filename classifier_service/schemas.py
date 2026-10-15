from typing import Literal

from pydantic import BaseModel, Field

ScamType = Literal["digital_arrest", "kyc_update", "bank_impersonation", "prize_lottery", "other", "none"]
WhisperClip = Literal["warn_otp", "warn_digital_arrest", "warn_secrecy", "none"]


class ClassifyRequest(BaseModel):
    call_id: str
    caller_number: str = ""
    speaker: Literal["caller", "victim"]
    chunk_text: str
    language: str = "en"


class Verdict(BaseModel):
    """Exact response shape. Also used as the Gemini response_schema."""

    call_id: str = ""
    scam_type: ScamType
    pressure: int = Field(ge=0, le=3)
    asks_otp_or_pin: bool
    demands_secrecy: bool
    confidence: float = Field(ge=0.0, le=1.0)
    language: Literal["hi", "kn", "en"]
    recommended_whisper_clip: WhisperClip
    summary_for_family: str
