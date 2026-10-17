"""The stage demo's robot calls: who calls, from which number, and every line the robot says.

make_stage_calls.py turns these into WAVs with Sarvam TTS; stage.sh plays them into the LiveKit room
with tools/robot_caller.py. Lines are separated by GAP_S of silence so the bridge cuts one chunk per line.
`expect` is what the run sheet promises the audience; check_stage_calls.py verifies it against the classifier.
"""

GAP_S = 5.0          # slow enough for an audience to follow the graph, the warnings and n8n
PACE = 0.9           # Sarvam TTS speaking pace (1.0 = normal)

CALLS = {
    "delivery": {
        "title": "Ordinary delivery call",
        "voice": ["sumit", "dev", "rahul"],          # not the scammer's voice
        "phone": "+91 90000 20001",
        "label": "",                      # unknown number: the caller ID shows only digits
        "expect": "stays silent: pressure 0, no whisper, no alert",
        "lines": [
            "नमस्ते आंटी, मैं अमेज़न डिलीवरी से बोल रहा हूँ।",
            "आपका पार्सल आ गया है, मैं आपकी बिल्डिंग के गेट पर खड़ा हूँ।",
            "आप नीचे आ सकती हैं, या मैं वॉचमैन को दे दूँ?",
            "ठीक है आंटी, मैं वॉचमैन के पास छोड़ देता हूँ। धन्यवाद।",
        ],
    },
    "scam": {
        "title": "Courier call that turns into a digital arrest",
        "voice": ["aditya"],                        # the redial uses the same voice
        "phone": None,                     # a fresh number per run (stage.sh), so the first call is "new"
        "label": "",
        "expect": "calm for ~18 s, then whispers: digital arrest, secrecy, OTP; n8n incident at pressure 2",
        "lines": [
            "हेलो नमस्ते, मैं ब्लू डार्ट कूरियर से बोल रहा हूँ। आपके नाम से एक पार्सल आया है।",
            "क्या आप अभी घर पर हैं? पता कन्फर्म करना था।",
            "सर, पार्सल मुंबई कस्टम्स में रुका हुआ है, और यह आपके आधार कार्ड से लिंक है।",
            "इसमें ड्रग्स और फेक पासपोर्ट मिले हैं। आपके खिलाफ मनी लॉन्ड्रिंग का केस दर्ज हुआ है।",
            "मैं अभी आपकी कॉल सीबीआई ऑफिसर को ट्रांसफर कर रहा हूँ। यह बात किसी को मत बताइए, फ़ोन मत काटिए।",
            "वेरिफिकेशन के लिए आपके फ़ोन पर एक ओटीपी आया है, वो जल्दी बताइए।",
        ],
    },
    "chat": {
        "title": "A long, ordinary chat with her neighbour",
        "voice": ["priya", "neha", "kavya", "roopa"],   # a woman, and not the warnings' voice (ritu)
        "phone": "+91 90000 20002",
        "label": "Sunita (neighbour)",
        "expect": "never more than caution (pressure 1): bank, pension and police come up, but no warning and no scam named",
        "lines": [
            "हेलो दीदी, नमस्ते! मैं सुनीता बोल रही हूँ, कैसी हैं आप?",
            "बहुत दिन हो गए बात नहीं हुई। घर पर सब ठीक है?",
            "हमारे यहाँ तो अगले महीने बिट्टू की शादी है, आपको आना ही पड़ेगा।",
            "कार्ड अभी छप रहे हैं, अगले हफ्ते तक आपके घर पहुँच जाएगा।",
            "और हाँ, आपकी दवाई वाली बात डॉक्टर से पूछी थी, उन्होंने कहा सुबह खाली पेट लेनी है।",
            "कल मैं बैंक गई थी, पेंशन की पासबुक अपडेट करवानी थी, बहुत भीड़ थी।",
            "मेरा छोटा बेटा भी अब पुलिस की ट्रेनिंग में है, अगले साल पोस्टिंग होगी।",
            "दीदी, आप ठीक से खाना खाया करिए, अपना ध्यान रखिए।",
            "मंदिर में अगले रविवार भजन है, साथ चलेंगे?",
            "मैं सुबह दस बजे आ जाऊँगी आपको लेने।",
            "अच्छा, बिट्टू भी आपको नमस्ते बोल रहा है।",
            "ठीक है दीदी, बाकी बातें मिलकर करेंगे। अपना ध्यान रखना, नमस्ते!",
        ],
    },
    "chat_en": {
        "title": "The same long, ordinary chat, in English",
        "lang": "en-IN",
        "voice": ["priya", "neha", "kavya", "roopa"],
        "phone": "+91 90000 20003",
        "label": "Priya (neighbour)",
        "expect": "never more than caution (pressure 1): no warning and no scam named",
        "lines": [
            "Hello aunty, good evening! This is Priya from next door. How are you?",
            "It's been so long since we spoke. Is everything fine at home?",
            "My brother's wedding is next month, you must come.",
            "The invitation cards are being printed, they should reach your house next week.",
            "And I asked the doctor about your medicine. He said take it in the morning before breakfast.",
            "Yesterday I went to the bank to update my pension passbook. There was such a long queue.",
            "My cousin just joined police training, he will get his posting next year.",
            "Please eat properly aunty, and take care of your health.",
            "There is a bhajan at the temple next Sunday. Shall we go together?",
            "I will come to pick you up at ten in the morning.",
            "Okay aunty, my mother also says hello.",
            "Alright, we will talk more when we meet. Take care, bye!",
        ],
    },
    "scam_en": {
        "title": "The courier call that turns into a digital arrest, in English",
        "lang": "en-IN",
        "voice": ["aditya"],
        "phone": None,
        "label": "",
        "expect": "caution at 'customs', warnings at 'drugs', 'do not tell anyone', 'OTP'",
        "lines": [
            "Hello, good afternoon. I am calling from Blue Dart courier. A parcel has been booked in your name.",
            "Are you at home right now? I need to confirm your address.",
            "Madam, the parcel is held at Mumbai customs, and it is linked to your Aadhaar card.",
            "We found drugs and fake passports inside. A money laundering case has been registered against you.",
            "I am transferring your call to the CBI officer. Do not tell anyone about this, and do not disconnect the call.",
            "For verification, you have received an OTP on your phone. Tell me the OTP quickly.",
        ],
    },
    "son": {
        "title": "Her son asks for the gas-delivery OTP",
        "voice": ["kabir", "rohan", "amit"],         # not the scammer's voice
        "phone": "+91 98450 12345",        # Ravi (son): on the classifier's trusted list + Supabase trusted_contacts
        "label": "Ravi (son)",
        "expect": "an OTP request, yet calm: trusted caller + everyday code, pressure at most 1, no whisper",
        "lines": [
            "हेलो माँ, मैं रवि बोल रहा हूँ।",
            "गैस सिलिंडर वाला घर पर आया है, बुकिंग मैंने ऐप से की थी।",
            "आपके फ़ोन पर इंडेन गैस का डिलीवरी कोड आया होगा, वो ओटीपी मुझे बता दो, मैं उसको बोल देता हूँ।",
        ],
    },
    "redial": {
        "title": "The scammer calls back",
        "voice": ["aditya"],                        # same man as the scam call
        "phone": None,                     # the same number as the scam call
        "label": "",
        "expect": "flagged before he finishes the first sentence: known scam number, whisper at once",
        "lines": [
            "हेलो मैडम, कॉल कट गया था। मैं सीबीआई ऑफिसर शर्मा बोल रहा हूँ।",
            "आपका केस अभी बंद नहीं हुआ है, फ़ोन मत काटिए।",
        ],
    },
}
