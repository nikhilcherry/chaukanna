import 'dart:convert';

/// The Verdict JSON contract sent by the Python guardian agent over the
/// LiveKit data channel.
class Verdict {
  final String transcript;
  final String scamType; // digital_arrest | kyc_update | bank_impersonation | prize_lottery | other | none
  final int pressure; // 0..3
  final bool asksOtpOrPin;
  final bool demandsSecrecy;
  final String language; // hi | kn | en
  final String recommendedWhisperClip; // warn_otp | warn_digital_arrest | warn_secrecy | warn_known_scammer | none

  // Optional extras the backend may include.
  final String callerNumber;
  final String summaryForFamily;
  final bool knownScammer;

  const Verdict({
    this.transcript = '',
    this.scamType = 'none',
    this.pressure = 0,
    this.asksOtpOrPin = false,
    this.demandsSecrecy = false,
    this.language = 'en',
    this.recommendedWhisperClip = 'none',
    this.callerNumber = '',
    this.summaryForFamily = '',
    this.knownScammer = false,
  });

  bool get isScam => scamType != 'none';

  factory Verdict.fromJson(Map<String, dynamic> j) => Verdict(
        transcript: (j['transcript'] ?? j['chunk_text'] ?? '') as String,
        scamType: (j['scam_type'] ?? 'none') as String,
        pressure: ((j['pressure'] ?? 0) as num).toInt().clamp(0, 3),
        asksOtpOrPin: j['asks_otp_or_pin'] == true,
        demandsSecrecy: j['demands_secrecy'] == true,
        language: (j['language'] ?? 'en') as String,
        recommendedWhisperClip: (j['recommended_whisper_clip'] ?? 'none') as String,
        callerNumber: (j['caller_number'] ?? '') as String,
        summaryForFamily: (j['summary_for_family'] ?? '') as String,
        knownScammer: j['known_scammer'] == true,
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
        'transcript': transcript,
        'scam_type': scamType,
        'pressure': pressure,
        'asks_otp_or_pin': asksOtpOrPin,
        'demands_secrecy': demandsSecrecy,
        'language': language,
        'recommended_whisper_clip': recommendedWhisperClip,
        if (callerNumber.isNotEmpty) 'caller_number': callerNumber,
        if (summaryForFamily.isNotEmpty) 'summary_for_family': summaryForFamily,
        if (knownScammer) 'known_scammer': true,
      };

  String get scamLabel => const {
        'digital_arrest': 'Digital Arrest Scam',
        'kyc_update': 'KYC Update Scam',
        'bank_impersonation': 'Bank Impersonation',
        'prize_lottery': 'Prize / Lottery Scam',
        'other': 'Suspected Scam',
      }[scamType] ??
      'Suspected Scam';
}

class TranscriptLine {
  final String text;
  final DateTime at;
  final int pressure;
  const TranscriptLine(this.text, this.at, this.pressure);
}
