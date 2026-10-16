import time

import pytest

import keywords as K
from callers import CallerRegistry, normalize_number


def run_call(chunks, policy="caution", lang="hi"):
    st = K.KeywordState()
    out = []
    for sp, text in chunks:
        K.scan_chunk(st, sp, text, lang)
        out.append(K.verdict(st, policy))
    return st, out


def peak(chunks, **kw):
    return max(v.pressure for v in run_call(chunks, **kw)[1])


@pytest.mark.parametrize("text,signal", [
    ("आपके आधार कार्ड से मनी लॉन्ड्रिंग हुई है, आपको डिजिटल अरेस्ट किया जा रहा है", "digital_arrest"),
    ("मैं मुंबई पुलिस साइबर क्राइम से बोल रहा हूँ", "authority"),
    ("अपना ओटीपी बताइए", "otp"),
    ("यह बात किसी को मत बताना", "secrecy"),
    ("ನಿಮ್ಮ KYC expire ಆಗಿದೆ", "kyc"),
    ("AnyDesk app install ಮಾಡಿ", "remote_access"),
    ("ಈ ವಿಷಯ ಯಾರಿಗೂ ಹೇಳಬೇಡಿ", "secrecy"),
    ("ನಿಮ್ಮ ಒಟಿಪಿ ಹೇಳಿ", "otp"),
    ("kisi ko mat batana, family ko bhi nahi", "secrecy"),
    ("call disconnect mat karna", "isolation"),
    ("please share your screen on the app", "remote_access"),
    ("transfer the money to the RBI safe account", "scam_payment"),
    ("tell me the six digit code you received", "otp"),
])
def test_signals_across_scripts(text, signal):
    st = K.KeywordState()
    K.scan_chunk(st, "caller", text, "hi")
    assert signal in st.hits, (signal, st.hits)


def test_secrecy_split_across_two_chunks():
    st = K.KeywordState()
    K.scan_chunk(st, "caller", "aur haan, yeh baat kisi ko mat", "hi")
    K.scan_chunk(st, "caller", "batana, samjhe aap?", "hi")
    assert "secrecy" in st.hits


def test_protective_otp_is_not_an_ask():
    st, vs = run_call([("caller", "This is HDFC Bank fraud monitoring, did you make a payment at Croma?"),
                       ("caller", "HDFC will never ask for your OTP or PIN, please do not share it with anyone.")])
    assert "otp" not in st.hits and "otp_protective" in st.hits and "secrecy" not in st.hits
    assert vs[-1].pressure == 0
    st, vs = run_call([("caller", "SBI branch se bol rahi hoon, aapka EMI due hai."),
                       ("caller", "OTP kisi ko mat bataiye.")])
    assert "otp" not in st.hits and "secrecy" not in st.hits and vs[-1].pressure <= 1


def test_scammer_cannot_hide_behind_protective_words():
    st, _ = run_call([("caller", "OTP kisi ko mat batana, sirf mujhe bataiye.")])
    assert "otp" in st.hits


def test_pin_code_is_not_a_pin():
    st, vs = run_call([("caller", "Swiggy delivery, aapka pin code kya hai? 560001 na?")])
    assert "otp" not in st.hits and vs[-1].pressure == 0


def test_news_gossip_is_not_a_threat():
    assert peak([("caller", "Arre tumne news dekhi? CBI ne us minister ko arrest kar liya money laundering mein.")]) <= 1


def test_digital_arrest_escalates():
    _, vs = run_call([("caller", "Namaste, main CBI officer bol raha hoon."),
                      ("caller", "Aapke naam se FedEx parcel pakda gaya hai customs mein, usme drugs hain."),
                      ("caller", "Apna OTP bataiye.")])
    assert [v.pressure for v in vs] == [1, 2, 3] and vs[-1].scam_type == "digital_arrest"


def test_victim_complying_after_otp_ask():
    _, vs = run_call([("caller", "SBI se bol raha hoon, card block ho jayega, OTP batao."), ("victim", "haan, 4 5 6 7 8 9")])
    assert vs[-1].pressure == 3


@pytest.mark.parametrize("policy,expected", [("caution", 1), ("warn", 2)])
def test_delivery_otp_policy_keywords(policy, expected):
    calls = [("caller", "Amazon delivery hai, main gate pe khada hoon."), ("caller", "OTP bata dijiye, delivery complete karni hai.")]
    assert peak(calls, policy=policy) == expected


def test_courier_otp_with_fee_is_a_scam_even_with_delivery_words():
    calls = [("caller", "Sir your parcel delivery failed, address incomplete."),
             ("caller", "Pay the 25 rupees redelivery fee on the link I sent, then tell me the OTP.")]
    assert peak(calls) >= 3


def test_language_detection():
    assert K.detect_language("नमस्ते", "en") == "hi"
    assert K.detect_language("ನಮಸ್ಕಾರ", "en") == "kn"
    assert K.detect_language("aap kya kar rahe ho, main aa raha hoon", "en") == "hi"
    assert K.detect_language("hello, how are you doing", "hi") == "hi"
    assert K.detect_language("hello, how are you doing", "xx") == "en"


def test_fast_path_latency_budget():
    """The whole keyword pass (scan + verdict) must stay far below 5 ms per chunk."""
    long_chunk = ("Aapke Aadhaar par money laundering ka case hai, arrest warrant nikal chuka hai, kisi ko mat batana, "
                  "AnyDesk install kijiye aur OTP bataiye. ನಿಮ್ಮ KYC expire ಆಗಿದೆ. आपको डिजिटल अरेस्ट किया जा रहा है। ") * 3
    times = []
    for _ in range(200):
        st = K.KeywordState()
        t = time.perf_counter()
        K.scan_chunk(st, "caller", long_chunk, "hi")
        K.verdict(st)
        times.append((time.perf_counter() - t) * 1000)
    times.sort()
    assert times[int(0.95 * len(times))] < 5.0, times[-5:]


@pytest.mark.parametrize("raw,norm", [("+91 98765-43210", "+919876543210"), ("09876543210", "+919876543210"),
                                      ("9876543210", "+919876543210"), ("0092 300 1234567", "+923001234567"),
                                      ("919876543210", "+919876543210"), ("", "")])
def test_normalize_number(raw, norm):
    assert normalize_number(raw) == norm


def test_registry_add_remove(tmp_path):
    reg = CallerRegistry(local=tmp_path / "local.json")
    assert reg.check("+91 98765 43210") is None
    reg.add("98765 43210", "digital_arrest", "test")
    assert reg.check("+919876543210").kind == "listed"
    assert CallerRegistry(local=tmp_path / "local.json").check("9876543210").kind == "listed"  # persisted
    assert reg.remove("+919876543210") and reg.check("9876543210") is None
    assert reg.check("+92 300 7654321").kind == "risky_country_code"   # unlisted +92 number
    assert reg.check("+92 300 1234567").kind == "listed"               # seeded, like Supabase
    assert reg.check("+91 80 4012 3456") is None
