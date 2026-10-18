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


# ---------------------------------------------------------------- scams aimed at the elderly
@pytest.mark.parametrize("chunks,stype,min_p", [
    ([("caller", "Main district treasury office se bol raha hoon, aapka jeevan pramaan update nahi hua hai."),
      ("caller", "Aaj nahi kiya to aapki pension band ho jayegi. Jo link bheja hai us par click karke OTP bataiye.")], "pension_scam", 3),
    ([("caller", "ನಿಮ್ಮ ಪಿಂಚಣಿ ನಿಲ್ಲುತ್ತೆ, ಲೈಫ್ ಸರ್ಟಿಫಿಕೇಟ್ ಅಪ್ಡೇಟ್ ಆಗಿಲ್ಲ"), ("caller", "ನಿಮ್ಮ ಒಟಿಪಿ ಹೇಳಿ")], "pension_scam", 3),
    ([("caller", "Hello dadi, pehchana kaun? Main aapka pota bol raha hoon, mera accident ho gaya hai."),
      ("caller", "Hospital mein hoon, turant 20000 rupaye bhej do, papa ko mat batana.")], "relative_emergency", 3),
    ([("caller", "Bijli vibhag se bol raha hoon, aapka pichle mahine ka bill update nahi hua."),
      ("caller", "Aaj raat 9:30 baje aapki bijli kat jayegi, abhi is number par 450 rupaye pay kijiye.")], "utility_disconnection", 3),
    ([("caller", "Sir LIC head office se bol raha hoon, aapki policy maturity ka bonus 3 lakh 40 hazaar release hona hai."),
      ("caller", "Uske liye 18 percent GST charge 6200 rupaye pehle jama karna hoga.")], "insurance_bonus", 3),
    ([("caller", "Main OLX se aapka sofa khareed raha hoon, advance bhej raha hoon."),
      ("caller", "Maine collect request bheja hai, usme apna UPI PIN daal dijiye to paise aapke account mein aa jayenge.")], "upi_collect", 3),
    ([("caller", "Sir maine galti se aapko 5000 bhej diye, please QR scan karke wapas kar dijiye.")], "upi_collect", 2),
    ([("caller", "Sir hamara VIP stock tips group join kijiye, daily 5 percent guaranteed return milega."),
      ("caller", "Bas 10000 se start kijiye, is link se trading app install kijiye.")], "investment_tip", 3),
    ([("caller", "Aapki video call ki recording hamare paas hai, nude video hai."),
      ("caller", "50000 bhejo warna aapke rishtedaaron ko bhej denge aur YouTube par viral kar denge.")], "sextortion", 3),
    ([("caller", "मैं साइबर क्राइम से बोल रहा हूँ, आपकी अश्लील वीडियो की शिकायत आई है"), ("caller", "केस बंद कराने के लिए पैसे भेजिए")], "sextortion", 3),
])
def test_elderly_scam_types(chunks, stype, min_p):
    _, vs = run_call(chunks)
    assert vs[-1].scam_type == stype, (vs[-1].scam_type, vs[-1].summary)
    assert vs[-1].pressure >= min_p, (vs[-1].pressure, vs[-1].summary)


@pytest.mark.parametrize("chunks", [
    [("caller", "Papa, pension aa gayi kya is mahine? Bank jaake passbook update kara lena.")],
    [("caller", "Namaste, LIC branch se bol rahi hoon, aapki policy ka premium 25 tareekh ko due hai.")],
    [("caller", "Aapki policy lapse ho jayegi agar premium time par nahi bhara, branch aakar jama kar dijiye.")],
    [("caller", "Main SBI branch se, aapka life certificate November mein jama hona hai, branch aa jaiye.")],
    [("caller", "Beta, share market aaj gira hai, news dekhi?")],
    [("caller", "Bijli office se bol rahe hain, kal subah 10 se 2 baje tak maintenance ke liye light nahi rahegi.")],
    [("caller", "Dadi main Rohan, kal shaam ko aa raha hoon milne.")],
])
def test_elderly_everyday_calls_stay_calm(chunks):
    assert peak(chunks) <= 1


# ---------------------------------------------------------------- not every OTP request is a scam
@pytest.mark.parametrize("text", [
    "Ola se bol raha hoon, main pickup point par khada hoon, ride OTP bata dijiye.",
    "Indane gas cylinder delivery ke liye aaya hoon, DAC code bata dijiye.",
    "Urban Company se technician, AC service ke liye aaya hoon, start OTP bataiye.",
    "Amazon return pickup ke liye aaya hoon, pickup OTP bata dijiye.",
    "Auto wala bol raha hoon, gate pe hoon, ride ka OTP batao.",
])
def test_everyday_codes_stay_calm(text):
    st, vs = run_call([("caller", text)])
    assert "otp" in st.hits and vs[-1].pressure <= 1 and vs[-1].scam_type == "none"


def trusted_call(chunks, name="Ravi (son)"):
    st = K.KeywordState()
    for sp, text in chunks:
        K.scan_chunk(st, sp, text, "hi")
    return K.verdict(st, "caution", trusted=name)


def test_family_contact_asking_for_their_otp_stays_calm():
    chunk = [("caller", "Mummy, Netflix ka OTP aaya hoga tumhare phone pe, bata do na.")]
    v = trusted_call(chunk)
    assert v.pressure == 1 and v.scam_type == "none" and v.benign_otp and "Ravi" in v.summary
    assert peak(chunk) >= 2   # the same words from an unknown number still alarm


@pytest.mark.parametrize("text,is_payment", [
    ("mere phone pe OTP aaya hai", False), ("tumhare phone pe message aaya", False),
    ("PhonePe kar dijiye 500 rupaye", True), ("phone pe se bhej do", True), ("phonepe number do", True),
])
def test_phone_pe_is_not_phonepe(text, is_payment):
    st = K.KeywordState()
    K.scan_chunk(st, "caller", text, "hi")
    assert ("payment" in st.hits) == is_payment, st.hits


@pytest.mark.parametrize("text", [
    "Mummy, SBI ka OTP aaya hai, jaldi bata do.",                                # a bank OTP
    "Mummy OTP bata do, aur papa ko mat batana.",                                 # secrecy
    "Mummy galti se mera WhatsApp code tumhare phone pe aa gaya, bata do.",       # the classic excuse
    "Mummy ek app install karo jo link bheja hai, phir OTP batao.",               # app / link
])
def test_family_contact_cannot_hide_a_scam_behind_trust(text):
    assert trusted_call([("caller", text)]).pressure >= 2


@pytest.mark.parametrize("text", [
    "Sir galti se aapke number par mera OTP chala gaya, please bata dijiye.",
    "Aapke WhatsApp ka code aaya hoga, woh bata dijiye.",
    "Aapke 5G upgrade ke liye OTP aaya hai, bata dijiye.",
])
def test_otp_excuses_are_critical(text):
    st, vs = run_call([("caller", text)])
    assert "otp_pretext" in st.hits and vs[-1].pressure == 3 and vs[-1].asks_otp_or_pin


def test_trusted_numbers(tmp_path):
    files = dict(local=tmp_path / "l.json", trusted=tmp_path / "t.json")
    reg = CallerRegistry(**files)
    assert reg.trusted_name("+91 98450 12345") is None
    reg.trust("98450 12345", "Ravi (son)")
    assert reg.trusted_name("+919845012345") == "Ravi (son)"
    assert CallerRegistry(**files).trusted_name("9845012345") == "Ravi (son)"   # persisted
    reg.add("+919845012345", "other", "reported")                              # a reported number is never trusted
    assert reg.trusted_name("+919845012345") is None
    reg.remove("+919845012345")
    assert reg.untrust("+919845012345") and reg.trusted_name("+919845012345") is None


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
