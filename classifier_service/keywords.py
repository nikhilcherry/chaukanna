"""Keyword fast path: a deterministic, sub-millisecond scam signal detector.

Runs on every chunk before (and independently of) the LLM, so an OTP demand or an arrest
threat is caught on the chunk it is spoken, not one LLM round-trip later.

Covers English, Hindi (Devanagari + Roman/Hinglish) and Kannada (script + Roman/Kanglish).
Signals are sticky for the whole call (KeywordState), and the pressure rules below turn the
accumulated signals into a verdict. Every signal keeps the text that triggered it, so the
whisper_reason can say exactly why.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- pattern helpers
_ZW = dict.fromkeys(map(ord, "​‌‍﻿"), None)


def normalize(text: str) -> str:
    """NFC, drop zero-width joiners (common in Kannada/Devanagari STT output), casefold,
    collapse whitespace."""
    t = unicodedata.normalize("NFC", text or "").translate(_ZW).casefold()
    return re.sub(r"\s+", " ", t).strip()


def _rx(latin: list[str], indic: list[str] = ()) -> re.Pattern:
    """Latin alternatives get word boundaries; Indic ones are matched as plain substrings,
    because Python's \\b treats Devanagari/Kannada vowel signs as non-word characters."""
    parts = []
    if latin:
        parts.append(r"(?<![a-z0-9])(?:" + "|".join(latin) + r")(?![a-z0-9])")
    if indic:
        parts.append("(?:" + "|".join(indic) + ")")
    return re.compile("|".join(parts))


# --------------------------------------------------------------------------- caller signals
OTP = _rx(
    [r"o\.? ?t\.? ?p\.?", r"otp", r"one[- ]?time[- ]?pass(word|code)", r"(upi|atm|card|debit card|m|net ?banking|secret) ?-?pin",
     r"pin( number| no\.?)", r"pin (bata\w*|bol\w*|daal\w*|enter\w*|share\w*|dijiye|do|de do|type\w*|kya hai)",
     r"(your|apna|aapka|apni|aapki) pin", r"cvv", r"cvc", r"(card|debit card|credit card) (number|details|ke peeche|ke piche)",
     r"(net ?banking |login |bank )?password", r"verification code", r"(6|six|4|four)[- ]digit (code|number|otp|pin)",
     r"code (bata\w*|bol\w*|share\w*|send|bhej\w*|read|tell|batao|bataiye)", r"(sms|message) (mein|me|par|pe) (jo|aaya|code)",
     r"expiry date", r"otp ?ne", r"otp ?gala", r"otp ?annu"],
    ["ओटीपी", "ओ टी पी", "ओ.टी.पी", "सीवीवी", "पासवर्ड", "वन टाइम पासवर्ड", "पिन नंबर", "पिन बता", "यूपीआई पिन", "एटीएम पिन",
     "कोड बता", "ಒಟಿಪಿ", "ಓಟಿಪಿ", "ಒ ಟಿ ಪಿ", "ಓ ಟಿ ಪಿ", "ಸಿವಿವಿ", "ಪಾಸ್ವರ್ಡ್", "ಪಿನ್ ನಂಬರ್", "ಯುಪಿಐ ಪಿನ್", "ಎಟಿಎಂ ಪಿನ್", "ಕೋಡ್ ಹೇಳಿ"],
)
NOT_OTP = re.compile(r"pin ?code|पिन कोड|ಪಿನ್ ಕೋಡ್|wi-?fi password|वाईफाई")
# A clause that mentions the OTP *protectively* (legit bank: "never share your OTP").
PROTECT = _rx(
    [r"never (ask|share|call|request)\w*", r"(do not|don'?t|dont|never) (share|give|tell|disclose)", r"will never",
     r"kabhi (bhi )?(nahi|na|nhi)", r"share (mat|na|nahi) (karein|kijiye|karna|karo|kare)",
     r"(mat|na|nahi) (bataiye|batayein|bataen|batana|batao|bataye|bataen|dijiye|dena)", r"kisi (ko|se) (bhi )?(share )?(mat|na|nahi)",
     r"yarigu (helbedi|helabedi|kodabedi)", r"share madbedi"],
    ["कभी नहीं", "कभी भी नहीं", "शेयर न करें", "शेयर ना करें", "साझा न करें", "न बताएं", "ना बताएं", "मत बताइए", "मत बताना",
     "ಯಾರಿಗೂ ಹೇಳಬೇಡಿ", "ಯಾರಿಗೂ ಕೊಡಬೇಡಿ", "ಶೇರ್ ಮಾಡಬೇಡಿ", "ಎಂದಿಗೂ ಕೇಳುವುದಿಲ್ಲ", "ಕೇಳುವುದಿಲ್ಲ"],
)
# A positive request for the code ("OTP bataiye", "tell me the OTP"), not preceded by a negation.
_NEG_LB = r"(?<!mat )(?<!na )(?<!nahi )(?<!kabhi )(?<!never )(?<!not )(?<!don't )(?<!dont )"
ASK = re.compile(
    r"(?:otp|o\.? ?t\.? ?p|pin|cvv|code|password)(?: number| no| jo| ko| aapko| aapke)?(?: \w+){0,2} " + _NEG_LB +
    r"(?:batao|bataiye|batayiye|bata do|bata dijiye|bata dijie|boliye|bolo|bol do|bol dijiye|share karo|share kijiye|share kar do|de do|dedo|dijiye|"
    r"send karo|send kijiye|bhejo|bhej do|bhej dijiye|read out|padh ke|padhiye|enter karo|daalo|daliye|heli|helbeku|kodi)(?![a-z])"
    r"|(?<!don't )(?<!dont )(?<!never )(?<!not )(?:tell|give|read|share|send|say|confirm) (?:me |us )?(?:the |your |that |this )?(?:otp|o\.?t\.?p|pin|cvv|code|password)"
    r"|(?:ओटीपी|पिन|कोड|सीवीवी|पासवर्ड)(?: \S+){0,2} (?<!मत )(?<!न )(?<!ना )(?:बताइए|बताइये|बताओ|बता दीजिए|बता दो|बोलिए|बोलो|दीजिए|भेजिए|शेयर कीजिए|शेयर करें)"
    r"|(?:ಒಟಿಪಿ|ಓಟಿಪಿ|ಪಿನ್|ಕೋಡ್|ಸಿವಿವಿ)(?: \S+){0,2} ?(?:ಹೇಳಿ|ಕೊಡಿ|ಕಳಿಸಿ|ಹೇಳ್ತೀರಾ|ಹೇಳಬೇಕು|ಕೊಡಬೇಕು|ಹೇಳ್ಬೇಕು)"
)
# ...or the caller asking for it themselves ("don't tell anyone, only tell me").
TO_ME = _rx([r"mujhe", r"muje", r"humein", r"hume", r"hamein", r"to me", r"tell me", r"give me", r"only me", r"sirf", r"except me",
             r"nange", r"nanage"], ["मुझे", "हमें", "सिर्फ", "ನನಗೆ", "ನಂಗೆ", "ನನಗೆ ಮಾತ್ರ"])

SECRECY = _rx(
    [r"(do not|don'?t|dont|never) (tell|inform|share this with|speak to|talk to|discuss)( this to| this with| it to| it with| about this to)? (anyone|anybody|any ?one|your|the|family|police|bank)",
     r"tell no ?one", r"(no ?one|nobody) (should|must|can) know", r"keep (this|it|the matter) (a )?(secret|confidential|between us|private)",
     r"(strictly|highly|top) confidential", r"confidential (matter|investigation|case|hai|h|rakhna|rakhiye|rakho|rahega)",
     r"(matter|case|investigation|baat) (is )?confidential", r"secret (matter|investigation|operation|case)",
     r"kisi (ko|se) (bhi )?(kuch )?(mat|na|nahi|nahin) (bata|bol|baat|kah)\w*",
     r"(ghar|family|parivar|parivaar|bete|beti|husband|pati|wife|patni|bank|police|beta|mummy|papa|kisi)( walon| wale| waalon)? ko (bhi )?(kuch )?(mat|na|nahi) (bata|bol)\w*",
     r"gupt (rakh|rakhna|rakhiye|hai|jaanch)\w*", r"gopniya", r"yarigu (helbedi|helabedi|tilisabedi)"],
    ["किसी को मत बता", "किसी को न बता", "किसी को ना बता", "किसी को नहीं बता", "किसी को भी मत", "किसी को भी न", "किसी से बात मत",
     "किसी से मत", "गोपनीय", "गुप्त रख", "गुप्त है", "परिवार को मत", "परिवार को न", "घरवालों को मत", "घर वालों को मत",
     "ಯಾರಿಗೂ ಹೇಳಬೇಡಿ", "ಯಾರಿಗೂ ಹೇಳ್ಬೇಡಿ", "ಯಾರಿಗೂ ಹೇಳಬಾರದು", "ಯಾರಿಗೂ ತಿಳಿಸಬೇಡಿ", "ಯಾರ ಜೊತೆಗೂ ಮಾತಾಡಬೇಡಿ", "ಯಾರ ಜೊತೆ ಮಾತಾಡಬೇಡಿ",
     "ರಹಸ್ಯ", "ಗೌಪ್ಯ", "ಕುಟುಂಬಕ್ಕೆ ಹೇಳಬೇಡಿ", "ಮನೆಯವರಿಗೆ ಹೇಳಬೇಡಿ"],
)
# Isolation: keep the victim on the line / on camera / alone. Legit agents also say "please don't
# disconnect", so on its own this is only suspicious; with an authority/threat script it is critical.
ISOLATION = _rx(
    [r"(do not|don'?t|dont) (hang up|disconnect|cut (the |this )?(call|phone)|leave the call)", r"stay on (the )?(video|camera)( call)?",
     r"(stay|remain) on (the )?(call|line) (till|until|for|24|all)", r"keep (your )?(the )?(camera|video) on",
     r"(go|stay|sit) (in|into|to) a (separate|closed|private|locked) room", r"(call|phone|line|video) (bilkul )?(mat|na|nahi|nahin) (kaat|kat|rakh|band|disconnect|cut)\w*",
     r"(call|phone) disconnect (mat|na)\w*", r"cut (mat|na) (karna|karo|kijiye)", r"akele (room|kamre)", r"band kamre",
     r"(phone|call) cut (madbedi|madabedi|maadbedi)"],
    ["फ़ोन मत काट", "फोन मत काट", "कॉल मत काट", "फ़ोन न काट", "फोन न काट", "कॉल न काट", "कॉल डिस्कनेक्ट मत", "अकेले कमरे", "वीडियो कॉल पर रहिए",
     "ಕಟ್ ಮಾಡಬೇಡಿ", "ಕಟ್ ಮಾಡ್ಬೇಡಿ", "ಕರೆ ಇಡಬೇಡಿ", "ಫೋನ್ ಇಡಬೇಡಿ"],
)
AUTHORITY = _rx(
    [r"c\.? ?b\.? ?i\.?", r"cbi", r"police", r"cyber ?(crime|cell|police|branch)", r"crime branch", r"customs", r"custom (department|office|officer|duty|wale|se)", r"narcotics?", r"ncb",
     r"enforcement directorate", r"ed (officer|department|office|se|ki team)", r"trai", r"rbi", r"reserve bank", r"income ?tax", r"interpol",
     r"(supreme|high|district|sessions|family) court", r"court (order|notice|summon\w*|case|mein|me|se|ka|ki|ne|hearing)", r"judge", r"magistrate", r"(sub[- ])?inspector", r"dcp", r"\bips\b", r"thane? (se|mein|me)",
     r"investigation officer", r"telecom (department|authority)", r"dot (department|se)", r"mumbai police", r"delhi police"],
    ["पुलिस", "सीबीआई", "सी बी आई", "कस्टम", "नारकोटिक्स", "साइबर क्राइम", "साइबर सेल", "क्राइम ब्रांच", "ईडी ", "इनकम टैक्स", "आयकर",
     "अदालत", "कोर्ट", "जज", "इंस्पेक्टर", "ट्राई", "आरबीआई", "थाने", "थाना",
     "ಪೊಲೀಸ್", "ಪೋಲೀಸ್", "ಪೊಲೀಸರು", "ಸಿಬಿಐ", "ಕಸ್ಟಮ್ಸ್", "ಸೈಬರ್ ಕ್ರೈಂ", "ಸೈಬರ್ ಕ್ರೈಮ್", "ನಾರ್ಕೋಟಿಕ್ಸ್", "ಕೋರ್ಟ್", "ನ್ಯಾಯಾಲಯ",
     "ಇನ್ಸ್ಪೆಕ್ಟರ್", "ಟ್ರಾಯ್", "ಆರ್ಬಿಐ", "ಠಾಣೆ"],
)
DIGITAL_ARREST = _rx([r"digital(ly)? arrest\w*", r"online arrest", r"video arrest", r"house arrest"],
                     ["डिजिटल अरेस्ट", "डिजिटल गिरफ्तार", "ಡಿಜಿಟಲ್ ಅರೆಸ್ಟ್", "ಡಿಜಿಟಲ್ ಬಂಧನ"])
# Legal-trouble threats: arrest, warrant, case, drugs... (the digital-arrest vocabulary)
LEGAL = _rx(
    [r"arrest\w*", r"warrant", r"jail", r"prison", r"f\.?i\.?r\.?", r"(case|complaint|fir) (hai|darj|darz|registered|file|filed|lodged|against|chal|ban|bana|ho gaya|hua)\w*",
     r"(legal|police|strict|criminal) action", r"money laundering", r"hawala", r"drugs?", r"mdma", r"ganja", r"heroin", r"fake passports?",
     r"illegal", r"gair ?(kanooni|kaanooni|qanooni|kanuni)", r"giraft?ar\w*", r"girftar\w*", r"terror(ist|ism)? funding", r"human trafficking",
     r"arrest madtivi", r"sezed|seized", r"(under|in) investigation"],
    ["गिरफ्तार", "गिरफ़्तार", "अरेस्ट", "वारंट", "जेल", "एफआईआर", "एफ आई आर", "मनी लॉन्ड्रिंग", "मनी लॉंड्रिंग", "ड्रग्स", "नशीले", "गैरकानूनी",
     "गैर कानूनी", "अवैध", "केस दर्ज", "कानूनी कार्रवाई", "जांच चल",
     "ಅರೆಸ್ಟ್", "ಬಂಧನ", "ಬಂಧಿಸ", "ವಾರಂಟ್", "ಜೈಲ್", "ಜೈಲು", "ಎಫ್ಐಆರ್", "ಮನಿ ಲಾಂಡರಿಂಗ್", "ಡ್ರಗ್ಸ್", "ಮಾದಕ", "ಅಕ್ರಮ", "ಕೇಸ್ ದಾಖಲ",
     "ಕೇಸ್ ಆಗಿದೆ", "ಕಾನೂನು ಕ್ರಮ", "ತನಿಖೆ"],
)
# Account/service threats: block, freeze, disconnect...
BLOCK = _rx(
    [r"(account|card|sim|number|connection|khata|upi|wallet|pan|aadhaa?r)( will be| is| has been| ho| hoga| ko)? (block|blocked|freeze|frozen|suspend|suspended|band|deactivat\w*|disconnect\w*|cancel\w*|close\w*)",
     r"(block|band|freeze|suspend|deactivate|disconnect|cut) (ho )?(jayega|jaega|jayegi|jaegi|kar diya jayega|kar denge|ho jayega)",
     r"(will be|get) (blocked|frozen|suspended|deactivated|disconnected|cut)", r"block aagutte", r"block agutte", r"block aagthide",
     r"bandh? ho jayega", r"kat jayega", r"penalty", r"fine of", r"jurmana"],
    ["ब्लॉक हो", "ब्लॉक कर", "बंद हो जाएगा", "बंद हो जायेगा", "बंद कर दिया जाएगा", "फ्रीज", "फ़्रीज़", "सस्पेंड", "कट जाएगा", "जुर्माना",
     "ಬ್ಲಾಕ್ ಆಗುತ್ತೆ", "ಬ್ಲಾಕ್ ಆಗುತ್ತದೆ", "ಬ್ಲಾಕ್ ಆಗುತ್ತೆ", "ಬ್ಲಾಕ್ ಮಾಡ", "ಬ್ಲಾಕ್ ಆಗಿದೆ", "ಫ್ರೀಜ್", "ಸ್ಥಗಿತ", "ಕಟ್ ಆಗುತ್ತೆ", "ದಂಡ"],
)
# The threat is aimed at the listener (2nd-person possessive/object forms). Bare "you" and
# "aapne/tumne" ("did you see the news?") are deliberately absent: gossip is not a threat.
TARGET = _rx(
    [r"your", r"you'?re", r"you are", r"you will", r"you have been", r"you'?ve been", r"against you", r"yourself", r"aapke", r"aapka", r"aapki",
     r"aapko", r"aap par", r"aap pe", r"aapse", r"apke", r"apka", r"apki", r"apko", r"tumhare", r"tumhara", r"tumko", r"tumhe", r"tumhein",
     r"nimma", r"nimge", r"nimage", r"nimmanna", r"nim mele"],
    ["आपके", "आपका", "आपकी", "आपको", "आप पर", "आपसे", "तुम्हारे", "तुम्हारा", "तुम्हें", "ನಿಮ್ಮ", "ನಿಮಗೆ", "ನಿಮ್ಮನ್ನು", "ನಿಮ್ಮ ಮೇಲೆ"],
)
KYC = _rx([r"e-?kyc", r"re-?kyc", r"kyc", r"k\.y\.c", r"sim (card )?(verification|kyc|update|reverification)", r"re-?verification"],
          ["केवाईसी", "के वाई सी", "ಕೆವೈಸಿ", "ಕೆ ವೈ ಸಿ"])
ID_DOCS = _rx([r"aadhaa?r", r"adhaar", r"aadhar", r"pan (card|number|no|link|details|update)", r"(link|update) (your |apna |aapka )?(pan|aadhaa?r)"],
              ["आधार", "पैन कार्ड", "पैन नंबर", "ಆಧಾರ್", "ಪ್ಯಾನ್ ಕಾರ್ಡ್", "ಪ್ಯಾನ್ ನಂಬರ್"])
EXPIRY = _rx([r"expire\w*", r"expiry", r"outdated", r"pending", r"not (updated|linked|verified)", r"update (karna|karwana|kijiye|karo|now|today)",
               r"update (maadi|madi|madbeku)"],
             ["एक्सपायर", "अपडेट नहीं", "अपडेट कर", "ಎಕ್ಸ್ಪೈರ್", "ಅಪ್ಡೇಟ್ ಮಾಡಿ", "ಅಪ್ಡೇಟ್ ಆಗಿಲ್ಲ", "ಅಪ್ಡೇಟ್ ಮಾಡಿಲ್ಲ"])
REMOTE = _rx([r"any ?desk", r"team ?viewer", r"quick ?support", r"rust ?desk", r"air ?droid", r"screen ?shar\w*", r"share (your |the |apna |apni )?screen",
              r"remote (access|app|control)", r"\.?apk( file)?"],
             ["एनीडेस्क", "एनी डेस्क", "टीमव्यूअर", "स्क्रीन शेयर", "ಎನಿಡೆಸ್ಕ್", "ಎನಿ ಡೆಸ್ಕ್", "ಟೀಮ್ ವ್ಯೂವರ್", "ಸ್ಕ್ರೀನ್ ಶೇರ್"])
APP_LINK = _rx([r"(download|install) (karo|kijiye|kar lo|kar lijiye|madi|maadi|this|the|an?|ye|yeh|ek)?( \w+)? ?(app|application)",
                r"(app|application) (download|install)\w*", r"link (pe|par|per|on|ko) (click|tap|open)\w*", r"click (on )?(the |this |that )?link",
                r"link (bhej|send|sent|bheja|aayega|share)\w*", r"(sms|message|whatsapp) (mein|me|par|pe) (link|jo link)", r"link (open|khol)\w*"],
               ["ऐप डाउनलोड", "ऐप इंस्टॉल", "एप डाउनलोड", "लिंक पर क्लिक", "लिंक भेज", "लिंक खोल",
                "ಆಪ್ ಇನ್ಸ್ಟಾಲ್", "ಆ್ಯಪ್ ಇನ್ಸ್ಟಾಲ್", "ಇನ್ಸ್ಟಾಲ್ ಮಾಡಿ", "ಡೌನ್ಲೋಡ್ ಮಾಡಿ", "ಲಿಂಕ್ ಕ್ಲಿಕ್", "ಲಿಂಕ್ ಕಳುಹಿಸ", "ಲಿಂಕ್ ಕಳಿಸ", "ಲಿಂಕ್ ಓಪನ್"])
# Payments that only scams ask for over a call.
SCAM_PAYMENT = _rx(
    [r"(processing|registration|clearance|reschedule|rescheduling|re-?delivery|redelivery|verification|security|customs|gst|tax|refundable|release|insurance|stamp duty|transfer) (fee|fees|charge|charges|amount|deposit|money)",
     r"safe (account|custody)", r"secure (account|wallet)", r"rbi (account|wallet|safe)", r"government account", r"(verification|security) (amount|deposit|money|rashi)",
     r"collect request", r"(accept|approve) (the )?(request|payment request)", r"gift ?cards?", r"crypto", r"bitcoin", r"usdt",
     r"(enter|daal\w*) (your )?(upi )?pin (to|se) (receive|get|claim)", r"pin (daal\w*|enter\w*) (karke|kar ke)? ?(paise|refund|cashback) (milenge|aayenge)"],
    ["सेफ अकाउंट", "सुरक्षित खाते", "वेरिफिकेशन अमाउंट", "प्रोसेसिंग फीस", "रजिस्ट्रेशन फीस", "ಸೇಫ್ ಅಕೌಂಟ್", "ಪ್ರೊಸೆಸಿಂಗ್ ಫೀ", "ವೆರಿಫಿಕೇಶನ್ ಅಮೌಂಟ್"],
)
PAYMENT = _rx(
    [r"transfer", r"send (the )?(money|amount|rs|rupees|\d)", r"(paise|paisa|paisey|rupees?|rupaye|amount|payment|rs\.?|money) (bhej|transfer|daal|jama|pay|send|kar)\w*",
     r"bhej (do|dijiye|dena|dijie)", r"pay (now|immediately|the|rs|₹|\d|kar\w*|karo)", r"google ?pay", r"phone ?pe", r"paytm (kar|karo|kijiye)",
     r"rtgs", r"neft", r"imps", r"upi (id|se|kar|karo|payment)", r"jama (karo|kijiye|kar do|karna)", r"duddu (kalisi|haaki|haki|kalsi)"],
    ["ट्रांसफर", "पैसे भेज", "पैसा भेज", "पैसे जमा", "पैसे डाल", "भुगतान", "पेमेंट", "रुपये भेज",
     "ಹಣ ಕಳುಹಿಸ", "ಹಣ ಕಳಿಸ", "ಹಣ ಹಾಕಿ", "ಹಣ ವರ್ಗಾಯಿಸ", "ಟ್ರಾನ್ಸ್ಫರ್", "ದುಡ್ಡು ಕಳಿಸ", "ದುಡ್ಡು ಹಾಕಿ", "ಪೇಮೆಂಟ್", "ಪಾವತಿ"],
)
URGENCY = _rx([r"immediately", r"right now", r"urgent\w*", r"turant", r"fauran", r"jaldi", r"abhi ke abhi", r"within (\d+|one|two|24|an?) (hours?|minutes?|mins?)",
               r"(aaj|today) (hi|only|tak|raat|itself|before)", r"(\d+|do|ek|teen) ghante", r"last (chance|warning)", r"thakshana", r"eega(le)?"],
              ["तुरंत", "फौरन", "जल्दी", "अभी के अभी", "आज ही", "घंटे में", "ತಕ್ಷಣ", "ಈಗಲೇ", "ಇವತ್ತೇ", "ಗಂಟೆಯೊಳಗೆ"])
BANK = _rx([r"bank", r"sbi", r"hdfc", r"icici", r"axis", r"kotak", r"pnb", r"canara", r"baroda", r"union bank", r"(credit|debit|atm) card", r"card (block|band)\w*",
            r"account", r"khata", r"transaction", r"upi", r"net ?banking", r"suspicious (activity|transaction|login)", r"unauthori[sz]ed", r"loan", r"emi"],
           ["बैंक", "खाता", "खाते", "कार्ड", "लेनदेन", "ट्रांजैक्शन", "ಬ್ಯಾಂಕ್", "ಖಾತೆ", "ಅಕೌಂಟ್", "ಕಾರ್ಡ್", "ವಹಿವಾಟು", "ಟ್ರಾನ್ಸಾಕ್ಷನ್"])
PRIZE = _rx([r"lottery", r"lucky (draw|winner|customer)", r"prize", r"you('ve| have)? won", r"winner", r"(aapne|aap ne|apne|aap|tumne) (\w+ ){0,3}(jeet|jeeta|jeete|jeeti)\w*", r"jeetne wale", r"inaam", r"inam", r"kbc", r"kaun banega crorepati",
             r"gift (hamper|voucher)", r"cashback", r"reward points?", r"bumper"],
            ["लॉटरी", "इनाम", "आपने जीत", "लकी ड्रा", "कैशबैक", "ಲಾಟರಿ", "ಬಹುಮಾನ", "ಗೆದ್ದಿದ್ದೀರಿ", "ಲಕ್ಕಿ ಡ್ರಾ", "ಕ್ಯಾಶ್ಬ್ಯಾಕ್"])
RELATIVE = _rx([r"your (son|daughter|husband|wife|father|mother|grandson|granddaughter|nephew|brother)", r"(aapka|aapke|apka|apke) (beta|bete|pati|bhai|pota|nati)",
                r"(aapki|apki) (beti|patni|poti)", r"papa", r"mummy", r"mumma", r"\bmom\b", r"\bdad\b", r"beta", r"beti", r"nimma (maga|magalu|ganda)"],
               ["आपका बेटा", "आपके बेटे", "आपकी बेटी", "बेटा", "बेटी", "पापा", "मम्मी", "ನಿಮ್ಮ ಮಗ", "ನಿಮ್ಮ ಮಗಳು", "ಅಪ್ಪ", "ಅಮ್ಮ"])
TROUBLE = _rx([r"accident", r"hospital", r"police station", r"thane mein", r"lock-?up", r"bail", r"zamanat", r"pakda gaya", r"pakad liya", r"(got |been )?arrested",
               r"emergency", r"operation", r"(in|big) trouble", r"musibat", r"phas gaya", r"phans gaya", r"kidnap\w*"],
              ["एक्सीडेंट", "हादसा", "अस्पताल", "हॉस्पिटल", "थाने में", "जमानत", "पकड़ा गया", "मुसीबत", "फंस गया",
               "ಆಕ್ಸಿಡೆಂಟ್", "ಅಪಘಾತ", "ಆಸ್ಪತ್ರೆ", "ಹಾಸ್ಪಿಟಲ್", "ಪೊಲೀಸ್ ಸ್ಟೇಷನ್", "ಬೇಲ್", "ಜಾಮೀನು", "ತೊಂದರೆ"])
COURIER = _rx([r"fedex", r"fed ex", r"dhl", r"blue ?dart", r"dtdc", r"courier", r"parcel", r"package", r"consignment", r"shipment", r"india post"],
              ["फेडेक्स", "पार्सल", "कूरियर", "कुरियर", "ಪಾರ್ಸೆಲ್", "ಕೊರಿಯರ್", "ಫೆಡೆಕ್ಸ್"])
DELIVERY = _rx([r"delivery( boy| agent| executive| partner| wala)?", r"swiggy", r"zomato", r"zepto", r"blinkit", r"instamart", r"amazon", r"flipkart", r"myntra",
                r"meesho", r"dunzo", r"big ?basket", r"porter", r"rider", r"(main|your|front|society) gate", r"gate (pe|par|ke paas|near)", r"building",
                r"flat( no)?", r"floor", r"landmark", r"cash on delivery", r"cod", r"order"],
               ["डिलीवरी", "ऑर्डर", "गेट", "ಡೆಲಿವರಿ", "ಆರ್ಡರ್", "ಗೇಟ್", "ಅಡ್ರೆಸ್", "ವಿಳಾಸ", "ಲೊಕೇಶನ್"])

# --------------------------------------------------------------------------- victim signals
DIGIT_RUN = re.compile(r"(?:\d[\s-]*){4,}|\*{3,}|x{4,}|(?:(?:zero|one|two|three|four|five|six|seven|eight|nine|oh)[\s,-]+){3,}(?:zero|one|two|three|four|five|six|seven|eight|nine|oh)")
COMPLY = _rx(
    [r"(otp|code|pin) (hai|is|ide|ಇದೆ|aaya|aa gaya|bol rahi|bol raha|bata rahi|bata raha)", r"bhej (diya|di|rahi|raha|deti|deta|dungi|dunga)\w*",
     r"transfer (kar|ho) (diya|di|rahi|raha|deti|deta|dungi|dunga|gaya)\w*", r"install (ho gaya|kar liya|kar diya|kar rahi|kar raha|ho raha|aaytu|aaythu|madide)",
     r"i('ll| will| am going to) (send|transfer|share|install|pay|tell|read)", r"i (have )?(sent|transferred|installed|shared|paid)",
     r"(kisi ko )?nahi? bataung[ia]", r"nahi bataungi", r"i won'?t tell (anyone|anybody)", r"main (abhi )?(bhej|transfer|kar|bata) (rahi|raha|deti|deta) (hoon|hu)",
     r"kalistini", r"kalsthini", r"haaktini", r"yarigu helalla"],
    ["भेज दिया", "भेज रही", "भेज रहा", "ट्रांसफर कर", "बता रही हूँ", "बता रहा हूँ", "किसी को नहीं बताऊंगी", "किसी को नहीं बताऊँगी", "इंस्टॉल कर लिया",
     "ಕಳಿಸ್ತೀನಿ", "ಕಳುಹಿಸುತ್ತೇನೆ", "ಹಾಕ್ತೀನಿ", "ಇನ್ಸ್ಟಾಲ್ ಆಯ್ತು", "ಯಾರಿಗೂ ಹೇಳಲ್ಲ", "ಕಳಿಸಿದ್ದೀನಿ", "ಟ್ರಾನ್ಸ್ಫರ್ ಮಾಡ್ತೀನಿ"],
)

# --------------------------------------------------------------------------- language
_HI_WORDS = re.compile(r"(?<![a-z])(hai|hain|nahi|nahin|aap|aapke|aapka|kya|main|hoon|hu|kar|karo|kijiye|ko|ka|ki|se|mein|ji|haan|bata\w*|bol\w*|raha|rahi|abhi|mat|ye|yeh|toh|bhi)(?![a-z])")
_KN_WORDS = re.compile(r"(?<![a-z])(illa|beku|maadi|madi|nimma|naanu|nanu|ide|alli|enu|yenu|hegidira|howdu|houdu|saar|swalpa|helbedi|aagutte|madtini|banni|guru|nodi)(?![a-z])")


def detect_language(text: str, hint: str) -> str:
    """Script first (Devanagari -> hi, Kannada -> kn), then Roman Hinglish/Kanglish
    function words, then the STT language hint."""
    for ch in text:
        o = ord(ch)
        if 0x0900 <= o <= 0x097F:
            return "hi"
        if 0x0C80 <= o <= 0x0CFF:
            return "kn"
    t = text.casefold()
    kn, hi = len(_KN_WORDS.findall(t)), len(_HI_WORDS.findall(t))
    if kn >= 2 and kn >= hi:
        return "kn"
    if hi >= 2:
        return "hi"
    return hint if hint in ("hi", "kn", "en") else "en"


# --------------------------------------------------------------------------- state + rules
CLAUSE_SPLIT = re.compile(r"[.!?।॥|;\n]+")

# Short human-readable label per signal, used in whisper_reason / summary.
LABELS = {
    "otp": "asked for an OTP/PIN/card details", "secrecy": "told the victim to keep it secret",
    "isolation": "told the victim not to hang up / to stay on camera", "authority": "claimed to be police/CBI/customs/RBI",
    "digital_arrest": "said the victim is under 'digital arrest'", "legal_threat": "threatened arrest/case/warrant",
    "block_threat": "threatened to block the account/SIM", "targeted": "aimed the threat at the victim", "kyc": "raised a KYC problem",
    "id_docs": "mentioned Aadhaar/PAN", "expiry": "said documents are expired/not updated", "remote_access": "asked for AnyDesk/screen-share",
    "app_or_link": "asked to install an app / click a link", "scam_payment": "asked for a fee / 'safe account' transfer",
    "payment": "asked for a money transfer", "urgency": "created urgency", "bank": "said they are from the bank",
    "prize": "offered a prize/lottery/cashback", "relative": "mentioned a family member", "trouble": "said someone is in trouble",
    "courier": "mentioned a parcel/courier", "delivery": "delivery context", "victim_complying": "the victim started complying",
    "otp_protective": "warned the victim not to share the OTP (legit-bank cue)",
}

CALLER_RULES: list[tuple[str, re.Pattern]] = [
    ("isolation", ISOLATION), ("authority", AUTHORITY), ("digital_arrest", DIGITAL_ARREST), ("legal_threat", LEGAL),
    ("block_threat", BLOCK), ("targeted", TARGET), ("kyc", KYC), ("id_docs", ID_DOCS), ("expiry", EXPIRY), ("remote_access", REMOTE),
    ("app_or_link", APP_LINK), ("scam_payment", SCAM_PAYMENT), ("payment", PAYMENT), ("urgency", URGENCY), ("bank", BANK),
    ("prize", PRIZE), ("relative", RELATIVE), ("trouble", TROUBLE), ("courier", COURIER), ("delivery", DELIVERY),
]
# Signals that say nothing about a scam on their own (not counted for confidence).
NEUTRAL = {"delivery", "otp_protective", "targeted", "relative", "urgency"}


@dataclass
class KeywordState:
    """Signals accumulated over the whole call (sticky)."""

    hits: dict[str, str] = field(default_factory=dict)  # signal -> first snippet that triggered it
    last_text: dict[str, str] = field(default_factory=dict)  # speaker -> previous chunk (boundary-spanning matches)
    lang_votes: dict[str, dict[str, int]] = field(default_factory=lambda: {"caller": {}, "victim": {}})

    def has(self, *names: str) -> bool:
        return any(n in self.hits for n in names)


@dataclass
class KeywordVerdict:
    scam_type: str
    pressure: int
    asks_otp_or_pin: bool
    demands_secrecy: bool
    confidence: float
    language: str
    delivery_otp: bool
    summary: str


def _snip(m: re.Match, text: str) -> str:
    """The match plus a few words of context, cut on word boundaries."""
    a, b = max(0, m.start() - 18), min(len(text), m.end() + 18)
    if a > 0 and " " in text[a:m.start()]:
        a = text.index(" ", a) + 1
    if b < len(text) and " " in text[m.end():b]:
        b = text.rindex(" ", m.end(), b)
    return text[a:b].strip()


def _hit(st: KeywordState, name: str, snippet: str, new: list[str]) -> None:
    if name not in st.hits:
        st.hits[name] = snippet
        new.append(name)


def otp_clause(clause: str) -> tuple[str, re.Match] | None:
    """('ask' | 'protective', match) for a clause that mentions an OTP/PIN, else None."""
    m = OTP.search(clause)
    if not m or NOT_OTP.search(clause[max(0, m.start() - 6): m.end() + 6]):
        return None
    if ASK.search(clause) or TO_ME.search(clause):
        return "ask", m
    if PROTECT.search(clause):
        return "protective", m
    return "ask", m


def scan_chunk(st: KeywordState, speaker: str, text: str, lang_hint: str = "en") -> list[str]:
    """Update the call's KeywordState with one chunk. Returns the newly seen signal names."""
    t = normalize(text)
    new: list[str] = []
    if not t:
        return new
    lang = detect_language(t, lang_hint)
    votes = st.lang_votes.setdefault(speaker, {})
    votes[lang] = votes.get(lang, 0) + 1
    # Join with the tail of this speaker's previous chunk so "kisi ko mat | batana" split across
    # two 4-second chunks still matches.
    joined = (st.last_text.get(speaker, "")[-60:] + " " + t).strip()
    st.last_text[speaker] = t

    if speaker == "victim":
        if st.has("otp", "remote_access", "app_or_link", "scam_payment", "payment", "secrecy"):
            m = DIGIT_RUN.search(t) or COMPLY.search(t)
            if m:
                _hit(st, "victim_complying", _snip(m, t), new)
        return new

    for clause in CLAUSE_SPLIT.split(joined):
        kind = otp_clause(clause)
        if kind:
            _hit(st, "otp" if kind[0] == "ask" else "otp_protective", _snip(kind[1], clause), new)
        m = SECRECY.search(clause)
        # "OTP kisi ko mat bataiye" is the bank protecting you, not the caller isolating you.
        if m and not (kind and kind[0] == "protective"):
            _hit(st, "secrecy", _snip(m, clause), new)
    for name, rx in CALLER_RULES:
        if name not in st.hits:
            m = rx.search(joined)
            if m:
                _hit(st, name, _snip(m, joined), new)
    return new


def _dominant(votes: dict[str, int]) -> str | None:
    return max(votes, key=votes.get) if votes else None


def verdict(st: KeywordState, delivery_otp_policy: str = "caution") -> KeywordVerdict:
    """Turn the accumulated signals into a verdict. See README "Keyword rules"."""
    h = st.has
    authority, da = h("authority"), h("digital_arrest")
    legal, block, targeted = h("legal_threat"), h("block_threat"), h("targeted")
    kyc = h("kyc") or (h("id_docs") and h("expiry"))
    id_docs = h("id_docs")
    remote, app_link = h("remote_access"), h("app_or_link")
    scam_pay, pay = h("scam_payment"), h("payment")
    otp, secrecy, isolation, urgency = h("otp"), h("secrecy"), h("isolation"), h("urgency")
    bank, prize = h("bank"), h("prize")
    relative_trouble = h("relative") and h("trouble")
    courier, delivery = h("courier"), h("delivery")
    complying = h("victim_complying")
    threat = legal or block or da
    courier_scam = courier and (authority or legal)

    context_strong = authority or da or legal or kyc or prize or courier_scam
    context_weak = bank or id_docs or courier or block or urgency or relative_trouble
    critical_hard = otp or remote or secrecy
    critical_soft = scam_pay or (app_link and (context_strong or bank or courier or id_docs)) or (isolation and context_strong)

    # Delivery OTP: a rider asking for the parcel OTP is the one OTP request that is usually legit.
    delivery_otp = delivery and otp and not (
        context_strong or bank or id_docs or block or relative_trouble or remote or secrecy or isolation or scam_pay or app_link)
    if delivery_otp and delivery_otp_policy == "caution":
        critical_hard = False

    p = 0
    if context_strong or relative_trouble or kyc or (bank and (urgency or block)) or isolation or \
            (pay and context_weak and not delivery):
        p = 1
    if (critical_hard or critical_soft or da
            or ((authority or kyc or bank or id_docs or prize or courier) and threat and targeted)
            or (relative_trouble and (pay or scam_pay) and (urgency or authority))):
        p = 2
    if ((critical_hard and (context_strong or context_weak)) or (critical_soft and context_strong)
            or (pay and (authority or da or legal or courier_scam or kyc)) or (relative_trouble and (secrecy or isolation))):
        p = 3
    if complying and p >= 2:
        p = 3
    if delivery_otp:
        p = max(p, 1 if delivery_otp_policy == "caution" else 2)

    if relative_trouble and not (da or courier_scam):
        stype = "other"
    elif authority or da or courier_scam:
        stype = "digital_arrest"
    elif remote or kyc or (id_docs and (threat or app_link or scam_pay or pay)):
        stype = "kyc_update"
    elif bank and (otp or threat or pay or scam_pay or app_link):
        stype = "bank_impersonation"
    elif prize:
        stype = "prize_lottery"
    elif p >= 2:
        stype = "other"
    else:
        stype = "none"
    if p == 0 or (delivery_otp and delivery_otp_policy == "caution"):
        stype = "none"

    n_signals = sum(1 for k in st.hits if k not in NEUTRAL)
    conf = 0.85 if p == 0 else min(0.95, 0.45 + 0.07 * n_signals + 0.05 * p)
    lang = _dominant(st.lang_votes.get("victim", {})) or _dominant(st.lang_votes.get("caller", {})) or "en"
    return KeywordVerdict(
        scam_type=stype, pressure=p, asks_otp_or_pin=otp, demands_secrecy=secrecy or isolation, confidence=round(conf, 2),
        language=lang, delivery_otp=delivery_otp, summary=summarize(st, stype, p, delivery_otp and delivery_otp_policy == "caution"),
    )


_TYPE_PHRASE = {
    "digital_arrest": "posing as police/CBI/customs (digital-arrest script)", "kyc_update": "running a KYC / account-block script",
    "bank_impersonation": "posing as the bank", "prize_lottery": "offering a fake prize/lottery", "other": "running a scam",
}
_SUMMARY_ORDER = ["authority", "digital_arrest", "legal_threat", "block_threat", "kyc", "remote_access", "app_or_link", "otp",
                  "scam_payment", "payment", "secrecy", "isolation", "prize", "trouble", "victim_complying"]


def summarize(st: KeywordState, stype: str, p: int, delivery_otp: bool) -> str:
    if delivery_otp and stype == "none":
        return "A delivery rider asked for the delivery OTP over the call; share it only in person at the door."
    if p == 0:
        return "Ordinary call, nothing suspicious so far."
    parts = [LABELS[k] for k in _SUMMARY_ORDER if k in st.hits][:4]
    head = f"Caller appears to be {_TYPE_PHRASE[stype]}" if stype in _TYPE_PHRASE else "Caller sounds suspicious"
    return head + (": " + ", ".join(parts) + "." if parts else ".")
