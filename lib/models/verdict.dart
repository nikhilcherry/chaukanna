import 'dart:convert';

/// The classifier's Verdict (CONTRACTS §1). Parsing is forgiving: wrong types
/// or missing fields fall back to safe defaults instead of throwing.
class Verdict {
  final String callId;
  final String transcript;
  final String scamType; // see CONTRACTS.md §1 (digital_arrest | ... | sextortion | other | none)
  final int pressure; // 0..3
  final bool asksOtpOrPin;
  final bool demandsSecrecy;
  final double confidence;
  final String language; // hi | kn | en
  final String recommendedWhisperClip; // warn_otp | warn_digital_arrest | warn_secrecy | warn_known_scammer | none
  final String callerNumber;
  final String summaryForFamily;
  final bool knownScammer;
  final String whisperReason;
  final bool degraded;

  const Verdict({
    this.callId = '',
    this.transcript = '',
    this.scamType = 'none',
    this.pressure = 0,
    this.asksOtpOrPin = false,
    this.demandsSecrecy = false,
    this.confidence = 0,
    this.language = 'en',
    this.recommendedWhisperClip = 'none',
    this.callerNumber = '',
    this.summaryForFamily = '',
    this.knownScammer = false,
    this.whisperReason = '',
    this.degraded = false,
  });

  bool get isScam => scamType != 'none' && scamType.isNotEmpty;

  factory Verdict.fromJson(Map<String, dynamic> j) => Verdict(
    callId: jStr(j['call_id']),
    transcript: jStr(j['transcript'] ?? j['chunk_text']),
    scamType: jStr(j['scam_type'], 'none'),
    pressure: jInt(j['pressure']).clamp(0, 3),
    asksOtpOrPin: jBool(j['asks_otp_or_pin']),
    demandsSecrecy: jBool(j['demands_secrecy']),
    confidence: jDouble(j['confidence']).clamp(0.0, 1.0),
    language: normLang(jStr(j['language'], 'en')),
    recommendedWhisperClip: jStr(j['recommended_whisper_clip'], 'none'),
    callerNumber: jStr(j['caller_number']),
    summaryForFamily: jStr(j['summary_for_family']),
    knownScammer: jBool(j['known_scammer']),
    whisperReason: jStr(j['whisper_reason']),
    degraded: jBool(j['degraded']),
  );

  static Verdict? tryParse(List<int> bytes) {
    try {
      final d = jsonDecode(utf8.decode(bytes));
      return d is Map<String, dynamic> ? Verdict.fromJson(d) : null;
    } catch (_) {
      return null;
    }
  }

  Map<String, dynamic> toJson() => {
    if (callId.isNotEmpty) 'call_id': callId,
    'transcript': transcript,
    'scam_type': scamType,
    'pressure': pressure,
    'asks_otp_or_pin': asksOtpOrPin,
    'demands_secrecy': demandsSecrecy,
    'confidence': confidence,
    'language': language,
    'recommended_whisper_clip': recommendedWhisperClip,
    if (callerNumber.isNotEmpty) 'caller_number': callerNumber,
    if (summaryForFamily.isNotEmpty) 'summary_for_family': summaryForFamily,
    if (knownScammer) 'known_scammer': true,
  };

  String get scamLabel => scamLabelFor(scamType);
}

String scamLabelFor(String scamType) =>
    const {
      'digital_arrest': 'Digital Arrest Scam',
      'kyc_update': 'KYC Update Scam',
      'bank_impersonation': 'Bank Impersonation',
      'prize_lottery': 'Prize / Lottery Scam',
      'pension_scam': 'Pension / Life Certificate Scam',
      'relative_emergency': 'Fake Family Emergency',
      'utility_disconnection': 'Electricity Disconnection Scam',
      'insurance_bonus': 'Fake Insurance Bonus',
      'upi_collect': 'UPI "Receive Money" Trap',
      'investment_tip': 'Investment / Stock Tips Scam',
      'sextortion': 'Sextortion Threat',
      'other': 'Suspected Scam',
    }[scamType] ??
    'Suspected Scam';

/// One line of the live transcript. [text] is already OTP-masked.
class TranscriptLine {
  final String text;
  final DateTime at;
  final int pressure;
  final String speaker; // caller | victim | ''
  const TranscriptLine(this.text, this.at, this.pressure, {this.speaker = 'caller'});

  bool get fromVictim => speaker == 'victim';
}

// ---- forgiving JSON helpers ------------------------------------------------

String jStr(Object? v, [String fallback = '']) {
  if (v == null) return fallback;
  final s = v is String ? v : v.toString();
  return s.isEmpty ? fallback : s;
}

int jInt(Object? v) {
  if (v is num) return v.toInt();
  if (v is String) return int.tryParse(v.trim()) ?? double.tryParse(v.trim())?.toInt() ?? 0;
  return 0;
}

double jDouble(Object? v) {
  if (v is num) return v.toDouble();
  if (v is String) return double.tryParse(v.trim()) ?? 0;
  return 0;
}

bool jBool(Object? v) => v == true || v == 1 || (v is String && v.toLowerCase() == 'true');

bool? jBoolOrNull(Object? v) => v == null ? null : jBool(v);

/// 'hi-IN' -> 'hi', 'KN' -> 'kn'.
String normLang(String lang) {
  final l = lang.trim().toLowerCase();
  if (l.isEmpty) return 'en';
  return l.split(RegExp('[-_]')).first;
}
