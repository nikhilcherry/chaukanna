// Content for the offline Demo Simulator: scripted scam-call lines and the
// n8n-style incident reply, in English, Hindi and Kannada.

String _pick(Map<String, String> m, String lang) => m[lang] ?? m['en']!;

class ScriptLine {
  const ScriptLine(this.speaker, this.text, this.verdict);
  final String speaker; // caller | victim
  final Map<String, String> text;

  /// Verdict fields for this chunk (scam_type, pressure, flags, whisper clip).
  final Map<String, Object> verdict;

  String textFor(String lang) => _pick(text, lang);
}

const _safe = {'scam_type': 'none', 'pressure': 0, 'asks_otp_or_pin': false, 'demands_secrecy': false};
const _arrest1 = {'scam_type': 'digital_arrest', 'pressure': 1, 'asks_otp_or_pin': false, 'demands_secrecy': false};
const _arrest2 = {
  'scam_type': 'digital_arrest',
  'pressure': 2,
  'asks_otp_or_pin': false,
  'demands_secrecy': true,
  'whisper_clip': 'warn_digital_arrest',
};
const _arrest2quiet = {'scam_type': 'digital_arrest', 'pressure': 2, 'asks_otp_or_pin': false, 'demands_secrecy': true};
const _otp3 = {
  'scam_type': 'digital_arrest',
  'pressure': 3,
  'asks_otp_or_pin': true,
  'demands_secrecy': true,
  'whisper_clip': 'warn_otp',
};
const _otp3quiet = {'scam_type': 'digital_arrest', 'pressure': 3, 'asks_otp_or_pin': true, 'demands_secrecy': true};

/// The full scripted "CBI digital arrest" call, in order.
const fullScamScript = <ScriptLine>[
  ScriptLine('caller', {
    'en': 'Hello, am I speaking with Mr. Ramesh Rao?',
    'hi': 'नमस्ते, क्या मैं रमेश राव जी से बात कर रहा हूँ?',
    'kn': 'ನಮಸ್ಕಾರ, ರಮೇಶ್ ರಾವ್ ಅವರ ಜೊತೆ ಮಾತನಾಡುತ್ತಿದ್ದೇನಾ?',
  }, _safe),
  ScriptLine('victim', {
    'en': 'Yes, speaking. Who is this?',
    'hi': 'हाँ, बोल रहा हूँ। आप कौन?',
    'kn': 'ಹೌದು, ಮಾತಾಡ್ತಿದ್ದೀನಿ. ನೀವು ಯಾರು?',
  }, _safe),
  ScriptLine('caller', {
    'en': 'This is Inspector Vikram Sharma from CBI Mumbai. Your Aadhaar number is linked to a money laundering case.',
    'hi': 'मैं CBI मुंबई से इंस्पेक्टर विक्रम शर्मा बोल रहा हूँ। आपका आधार नंबर मनी लॉन्ड्रिंग केस से जुड़ा है।',
    'kn': 'ನಾನು CBI ಮುಂಬೈನಿಂದ ಇನ್ಸ್‌ಪೆಕ್ಟರ್ ವಿಕ್ರಮ್ ಶರ್ಮಾ. ನಿಮ್ಮ ಆಧಾರ್ ನಂಬರ್ ಮನಿ ಲಾಂಡರಿಂಗ್ ಕೇಸ್‌ಗೆ ಲಿಂಕ್ ಆಗಿದೆ.',
  }, _arrest1),
  ScriptLine('caller', {
    'en': 'A warrant is issued in your name. You are under digital arrest. Do not tell anyone, not even your family, and do not disconnect this call.',
    'hi': 'आपके नाम पर वारंट जारी हुआ है। आप डिजिटल अरेस्ट में हैं। किसी को मत बताइए, परिवार को भी नहीं, और कॉल मत काटिए।',
    'kn': 'ನಿಮ್ಮ ಹೆಸರಿನಲ್ಲಿ ವಾರಂಟ್ ಹೊರಡಿಸಲಾಗಿದೆ. ನೀವು ಡಿಜಿಟಲ್ ಅರೆಸ್ಟ್‌ನಲ್ಲಿದ್ದೀರಿ. ಯಾರಿಗೂ ಹೇಳಬೇಡಿ, ಮನೆಯವರಿಗೂ ಸಹ, ಕರೆ ಕಟ್ ಮಾಡಬೇಡಿ.',
  }, _arrest2),
  ScriptLine('victim', {
    'en': 'What? I have not done anything wrong...',
    'hi': 'क्या? मैंने कुछ गलत नहीं किया...',
    'kn': 'ಏನು? ನಾನು ಏನೂ ತಪ್ಪು ಮಾಡಿಲ್ಲ...',
  }, _arrest2quiet),
  ScriptLine('caller', {
    'en': 'To clear your name, read me the OTP we just sent. Is it 482913?',
    'hi': 'अपना नाम साफ़ करने के लिए अभी आया OTP बताइए। क्या वो 482913 है?',
    'kn': 'ನಿಮ್ಮ ಹೆಸರು ಕ್ಲಿಯರ್ ಮಾಡಲು ಈಗ ಬಂದ OTP ಹೇಳಿ. ಅದು 482913 ಅಲ್ವಾ?',
  }, _otp3),
  ScriptLine('victim', {
    'en': 'No. I will not share any OTP. I am calling my son.',
    'hi': 'नहीं, मैं कोई OTP नहीं बताऊँगा। मैं अपने बेटे को फ़ोन कर रहा हूँ।',
    'kn': 'ಇಲ್ಲ, ನಾನು ಯಾವುದೇ OTP ಹೇಳುವುದಿಲ್ಲ. ನನ್ನ ಮಗನಿಗೆ ಕರೆ ಮಾಡುತ್ತಿದ್ದೇನೆ.',
  }, _otp3quiet),
];

const simSafeLine = {
  'en': 'Hello sir, this is a courtesy call about your electricity bill for this month.',
  'hi': 'नमस्ते सर, यह इस महीने के आपके बिजली बिल के बारे में एक सामान्य कॉल है।',
  'kn': 'ನಮಸ್ಕಾರ ಸರ್, ಇದು ಈ ತಿಂಗಳ ನಿಮ್ಮ ವಿದ್ಯುತ್ ಬಿಲ್ ಬಗ್ಗೆ ಕರೆ.',
};
const simOtpLine = {
  'en': 'Your account will be blocked today. Please tell me the OTP you just received on your phone.',
  'hi': 'आपका खाता आज बंद हो जाएगा। आपके फोन पर जो OTP आया है वह अभी बताइए।',
  'kn': 'ನಿಮ್ಮ ಖಾತೆ ಇಂದೇ ಬ್ಲಾಕ್ ಆಗುತ್ತದೆ. ನಿಮ್ಮ ಫೋನ್‌ಗೆ ಬಂದ OTP ಈಗಲೇ ಹೇಳಿ.',
};
const simArrestLine = {
  'en': 'This is CBI officer Sharma. A warrant is issued against you. You are under digital arrest, do not tell anyone and do not disconnect the call.',
  'hi': 'मैं CBI अधिकारी शर्मा बोल रहा हूँ। आपके खिलाफ वारंट जारी है। आप डिजिटल अरेस्ट में हैं, किसी को मत बताइए और कॉल मत काटिए।',
  'kn': 'ನಾನು CBI ಅಧಿಕಾರಿ ಶರ್ಮಾ. ನಿಮ್ಮ ವಿರುದ್ಧ ವಾರಂಟ್ ಹೊರಡಿಸಲಾಗಿದೆ. ನೀವು ಡಿಜಿಟಲ್ ಅರೆಸ್ಟ್‌ನಲ್ಲಿದ್ದೀರಿ, ಯಾರಿಗೂ ಹೇಳಬೇಡಿ, ಕರೆ ಕಟ್ ಮಾಡಬೇಡಿ.',
};
const simKnownLine = {
  'en': 'Hello, I am calling from your bank, please verify your KYC details.',
  'hi': 'नमस्ते, मैं आपके बैंक से बोल रहा हूँ, कृपया अपनी KYC जानकारी बताइए।',
  'kn': 'ನಮಸ್ಕಾರ, ನಾನು ನಿಮ್ಮ ಬ್ಯಾಂಕ್‌ನಿಂದ ಕರೆ ಮಾಡುತ್ತಿದ್ದೇನೆ, ದಯವಿಟ್ಟು KYC ವಿವರ ನೀಡಿ.',
};

String pickLine(Map<String, String> m, String lang) => _pick(m, lang);

// ---- simulated n8n incident reply -----------------------------------------

const _scamNames = <String, Map<String, String>>{
  'digital_arrest': {'en': 'digital arrest fraud', 'hi': 'डिजिटल अरेस्ट धोखाधड़ी', 'kn': 'ಡಿಜಿಟಲ್ ಅರೆಸ್ಟ್ ವಂಚನೆ'},
  'kyc_update': {'en': 'KYC update fraud', 'hi': 'KYC अपडेट धोखाधड़ी', 'kn': 'KYC ಅಪ್‌ಡೇಟ್ ವಂಚನೆ'},
  'bank_impersonation': {
    'en': 'bank impersonation fraud',
    'hi': 'बैंक अधिकारी बनकर धोखाधड़ी',
    'kn': 'ಬ್ಯಾಂಕ್ ಅಧಿಕಾರಿಯಂತೆ ನಟಿಸಿ ವಂಚನೆ',
  },
  'prize_lottery': {'en': 'prize / lottery fraud', 'hi': 'इनाम / लॉटरी धोखाधड़ी', 'kn': 'ಬಹುಮಾನ / ಲಾಟರಿ ವಂಚನೆ'},
  'other': {'en': 'phone fraud', 'hi': 'फ़ोन धोखाधड़ी', 'kn': 'ಫೋನ್ ವಂಚನೆ'},
};

String scamNameIn(String scamType, String lang) => _pick(_scamNames[scamType] ?? _scamNames['other']!, lang);

/// The complaint text n8n's AI drafts (simulated), in [lang].
String simComplaint(
  String lang, {
  required String scamType,
  required String number,
  required DateTime when,
  required bool otp,
  required bool secrecy,
  required bool known,
}) {
  final d = '${_two(when.day)}-${_two(when.month)}-${when.year}';
  final t = '${_two(when.hour)}:${_two(when.minute)}';
  final scam = scamNameIn(scamType, lang);
  final arrest = scamType == 'digital_arrest';
  switch (lang) {
    case 'hi':
      return [
        'सेवा में: राष्ट्रीय साइबर अपराध रिपोर्टिंग पोर्टल (cybercrime.gov.in) / हेल्पलाइन 1930',
        '',
        'विषय: फ़ोन कॉल द्वारा $scam का प्रयास',
        '',
        '$d को $t बजे मुझे $number से कॉल आया। '
            '${arrest ? "कॉल करने वाले ने ख़ुद को CBI अधिकारी बताया और कहा कि मैं 'डिजिटल अरेस्ट' में हूँ। " : ''}'
            '${otp ? 'उसने मुझसे OTP/PIN माँगा। ' : ''}'
            '${secrecy ? 'उसने मुझे परिवार या पुलिस को न बताने को कहा। ' : ''}'
            '${known ? 'यह नंबर पहले से साझा फ्रॉड-नंबर सूची में है। ' : ''}'
            'मैंने कोई OTP या PIN नहीं बताया और कोई पैसा नहीं भेजा गया। '
            'कॉल की ट्रांसक्रिप्ट समय के साथ सबूत के रूप में सुरक्षित है। कृपया इस नंबर की जाँच करके इसे ब्लॉक करें।',
      ].join('\n');
    case 'kn':
      return [
        'ಗೆ: ರಾಷ್ಟ್ರೀಯ ಸೈಬರ್ ಅಪರಾಧ ವರದಿ ಪೋರ್ಟಲ್ (cybercrime.gov.in) / ಸಹಾಯವಾಣಿ 1930',
        '',
        'ವಿಷಯ: ಫೋನ್ ಕರೆಯ ಮೂಲಕ $scamಯ ಪ್ರಯತ್ನ',
        '',
        '$d ರಂದು $tಕ್ಕೆ ನನಗೆ $number ಸಂಖ್ಯೆಯಿಂದ ಕರೆ ಬಂತು. '
            '${arrest ? "ಕರೆ ಮಾಡಿದವರು ತಮ್ಮನ್ನು CBI ಅಧಿಕಾರಿ ಎಂದು ಹೇಳಿಕೊಂಡು, ನಾನು 'ಡಿಜಿಟಲ್ ಅರೆಸ್ಟ್'ನಲ್ಲಿದ್ದೇನೆ ಎಂದರು. " : ''}'
            '${otp ? 'ಅವರು ನನ್ನಿಂದ OTP/PIN ಕೇಳಿದರು. ' : ''}'
            '${secrecy ? 'ಕುಟುಂಬಕ್ಕೆ ಅಥವಾ ಪೊಲೀಸರಿಗೆ ತಿಳಿಸಬಾರದು ಎಂದು ಹೇಳಿದರು. ' : ''}'
            '${known ? 'ಈ ಸಂಖ್ಯೆ ಈಗಾಗಲೇ ಹಂಚಿಕೊಂಡ ವಂಚಕರ ಪಟ್ಟಿಯಲ್ಲಿದೆ. ' : ''}'
            'ನಾನು ಯಾವುದೇ OTP ಅಥವಾ PIN ಹೇಳಲಿಲ್ಲ, ಯಾವುದೇ ಹಣ ವರ್ಗಾವಣೆ ಆಗಿಲ್ಲ. '
            'ಕರೆಯ ಪ್ರತಿಲಿಪಿಯನ್ನು ಸಮಯದೊಂದಿಗೆ ಸಾಕ್ಷ್ಯವಾಗಿ ಉಳಿಸಲಾಗಿದೆ. ದಯವಿಟ್ಟು ಈ ಸಂಖ್ಯೆಯನ್ನು ತನಿಖೆ ಮಾಡಿ ನಿರ್ಬಂಧಿಸಿ.',
      ].join('\n');
    default:
      return [
        'To: National Cyber Crime Reporting Portal (cybercrime.gov.in) / Helpline 1930',
        '',
        'Subject: Attempted $scam by phone call',
        '',
        'On $d at $t I received a call from $number. '
            '${arrest ? "The caller claimed to be a CBI officer and said I was under 'digital arrest'. " : ''}'
            '${otp ? 'The caller asked me to share an OTP / PIN. ' : ''}'
            '${secrecy ? 'The caller told me not to tell my family or the police. ' : ''}'
            '${known ? 'This number is already on the shared scam-number list. ' : ''}'
            'I did not share any OTP or PIN and no money was transferred. '
            'The call transcript with timestamps is saved as evidence. '
            'I request that this number be investigated and blocked.',
      ].join('\n');
  }
}

/// The family alert n8n sends (simulated).
String simFamilyAlert({
  required String victimName,
  required String scamType,
  required String number,
  required bool otp,
  required bool secrecy,
  required bool known,
}) {
  final flags = [
    if (known) 'the number is on the shared scam list',
    if (secrecy) 'the caller demanded secrecy',
    if (otp) 'the caller asked for an OTP',
  ];
  return [
    '• $victimName got a ${scamNameIn(scamType, 'en')} call from $number.',
    '• ${flags.isEmpty ? 'Chaukanna flagged high pressure' : _cap(flags.join(' and '))}. '
        'Chaukanna warned $victimName; no OTP was shared.',
    '• Please call $victimName now. The 1930 complaint is drafted and waits for their OK.',
  ].join('\n');
}

String _two(int n) => n.toString().padLeft(2, '0');
String _cap(String s) => s.isEmpty ? s : s[0].toUpperCase() + s.substring(1);
