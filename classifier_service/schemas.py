from typing import Literal

from pydantic import BaseModel, Field, field_validator

ScamType = Literal["digital_arrest", "kyc_update", "bank_impersonation", "prize_lottery", "pension_scam", "relative_emergency",
                   "utility_disconnection", "insurance_bonus", "upi_collect", "investment_tip", "sextortion", "other", "none"]
WhisperClip = Literal["warn_otp", "warn_digital_arrest", "warn_secrecy", "warn_known_scammer", "none"]
Lang = Literal["hi", "kn", "en"]
LANGS = ("hi", "kn", "en")


def norm_lang(code: str | None) -> str:
    """'hi-IN' -> 'hi'; anything outside hi/kn/en -> 'en'."""
    c = (code or "en").split("-")[0].split("_")[0].lower()
    return c if c in LANGS else "en"


OtpPurpose = Literal["payment", "upi", "card", "bank_login", "sim", "messaging_account", "government_id", "other_login",
                     "everyday"]
# What sharing that OTP would hand over. "high": money or the account itself; nobody on a call needs it.
OTP_RISK = {"payment": "high", "upi": "high", "card": "high", "bank_login": "high", "sim": "high", "messaging_account": "high",
            "government_id": "medium", "other_login": "medium", "everyday": "low"}


class OtpContext(BaseModel):
    """An OTP SMS the victim's phone received during the call, as read on the phone. Never the code."""
    call_id: str
    purpose: OtpPurpose = "other_login"
    service: str = ""                 # who sent it, e.g. "HDFC Bank", "Swiggy" (from the SMS sender id)
    amount: float | None = None       # rupees, for a payment OTP
    seconds_before_call: float = 0.0  # 0 = arrived during the call; >0 = arrived that long before it started


class ClassifyRequest(BaseModel):
    call_id: str
    caller_number: str = ""
    speaker: Literal["caller", "victim"]
    chunk_text: str = ""
    language: str = "en"

    @field_validator("speaker", mode="before")
    @classmethod
    def _speaker(cls, v):
        return str(v).strip().lower() if v is not None else v


class LLMVerdict(BaseModel):
    """What a classification backend returns (also the Gemini response_schema).
    Whisper clip, known-scammer and the other service-level fields are decided in code."""

    scam_type: ScamType
    pressure: int = Field(ge=0, le=3)
    asks_otp_or_pin: bool
    demands_secrecy: bool
    confidence: float = Field(ge=0.0, le=1.0)
    language: Lang
    summary_for_family: str


class Verdict(BaseModel):
    """Response of POST /classify. The first nine fields are the original contract;
    everything after them is optional and additive (CONTRACTS.md section 1)."""

    call_id: str = ""
    scam_type: ScamType
    pressure: int = Field(ge=0, le=3)
    asks_otp_or_pin: bool
    demands_secrecy: bool
    confidence: float = Field(ge=0.0, le=1.0)
    language: Lang
    recommended_whisper_clip: WhisperClip = "none"
    summary_for_family: str = ""
    # --- additive, optional ---
    known_scammer: bool = False
    caller_risk: Literal["listed", "risky_country_code", "none"] = "none"
    whisper_reason: str = ""
    degraded: bool = False
    # "keywords" (no model verdict yet) | "merged" (keywords + an earlier model verdict) |
    # the backend name, e.g. "gemini" / "jev", when a model verdict covering this chunk decided it.
    source: str = "keywords"
    backend: str | None = None  # backend that produced the latest model verdict, e.g. "gemini(fallback)"
    signals: list[str] = Field(default_factory=list)
    llm_chunks_behind: int | None = None
    chunk_index: int = 0
    latency_ms: float = 0.0
