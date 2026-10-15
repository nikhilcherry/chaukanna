import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:vibration/vibration.dart';

import '../config.dart';
import '../models/verdict.dart';
import '../services/livekit_service.dart';
import '../services/whisper_player.dart';

enum CallPhase { idle, active, ended }

enum SubmitState { idle, submitting, done, failed }

/// Single source of truth. Real LiveKit packets and the offline simulator
/// both flow through [ingest].
class GuardianController extends ChangeNotifier {
  final _livekit = LiveKitService();
  final _whisper = WhisperPlayer();

  CallPhase phase = CallPhase.idle;
  String callerNumber = '+91 98XXX 41207';
  Verdict verdict = const Verdict();
  final List<TranscriptLine> transcript = [];
  Duration elapsed = Duration.zero;
  Timer? _ticker;
  DateTime? _callStart;
  bool muted = false;
  bool speaker = true;

  // Intervention
  bool alarmActive = false;
  Verdict? alarmVerdict;
  String? whisperPlaying;
  int _alarmedPressure = 0;
  String _alarmedClip = 'none';

  // Whole-call record, for the post-call screen.
  int peakPressure = 0;
  bool sawOtpAsk = false;
  bool sawSecrecy = false;
  bool knownScammerBlocked = false;
  String scamType = 'none';
  String summaryForFamily = '';
  final List<String> evidenceTimestamps = [];
  Timer? _autoHangup;

  SubmitState submitState = SubmitState.idle;
  String submitMessage = '';

  bool get highRiskCall => peakPressure >= 2;

  // ---- lifecycle -----------------------------------------------------------

  Future<void> connectLive() async {
    if (!AppConfig.liveKitConfigured) return;
    try {
      await _livekit.connect(
        url: AppConfig.livekitUrl,
        token: AppConfig.livekitToken,
        onVerdict: ingest,
        onDisconnected: endCall,
      );
      startCall();
    } catch (e) {
      debugPrint('LiveKit connect failed: $e');
    }
  }

  void startCall({String? number}) {
    if (phase == CallPhase.active) return;
    _resetRecord();
    if (number != null) callerNumber = number;
    phase = CallPhase.active;
    _callStart = DateTime.now();
    _ticker = Timer.periodic(const Duration(seconds: 1), (_) {
      elapsed = DateTime.now().difference(_callStart!);
      notifyListeners();
    });
    notifyListeners();
  }

  Future<void> endCall() async {
    if (phase != CallPhase.active) return;
    _ticker?.cancel();
    _autoHangup?.cancel();
    alarmActive = false;
    await _whisper.stop();
    whisperPlaying = null;
    phase = CallPhase.ended;
    await _livekit.disconnect();
    notifyListeners();
  }

  void resetToIdle() {
    _resetRecord();
    phase = CallPhase.idle;
    notifyListeners();
  }

  void _resetRecord() {
    _ticker?.cancel();
    _autoHangup?.cancel();
    verdict = const Verdict();
    transcript.clear();
    elapsed = Duration.zero;
    alarmActive = false;
    alarmVerdict = null;
    whisperPlaying = null;
    _alarmedPressure = 0;
    _alarmedClip = 'none';
    peakPressure = 0;
    sawOtpAsk = false;
    sawSecrecy = false;
    knownScammerBlocked = false;
    scamType = 'none';
    summaryForFamily = '';
    evidenceTimestamps.clear();
    submitState = SubmitState.idle;
    submitMessage = '';
    muted = false;
    speaker = true;
  }

  // ---- call controls -------------------------------------------------------

  void toggleMute() {
    muted = !muted;
    _livekit.setMuted(muted);
    notifyListeners();
  }

  void toggleSpeaker() {
    speaker = !speaker;
    _livekit.setSpeaker(speaker);
    notifyListeners();
  }

  // ---- verdict ingest ------------------------------------------------------

  void ingest(Verdict v) {
    if (phase == CallPhase.idle) startCall(number: v.callerNumber.isEmpty ? null : v.callerNumber);
    if (phase != CallPhase.active) return;
    if (v.callerNumber.isNotEmpty) callerNumber = v.callerNumber;
    verdict = v;
    final now = DateTime.now();
    if (v.transcript.trim().isNotEmpty) {
      transcript.add(TranscriptLine(v.transcript.trim(), now, v.pressure));
    }
    if (v.pressure > peakPressure) peakPressure = v.pressure;
    sawOtpAsk |= v.asksOtpOrPin;
    sawSecrecy |= v.demandsSecrecy;
    if (v.isScam) scamType = v.scamType;
    if (v.summaryForFamily.isNotEmpty) summaryForFamily = v.summaryForFamily;
    if (v.pressure >= 2 || v.knownScammer) {
      evidenceTimestamps.add('${_clock(now)} (+${_dur(elapsed)}) — pressure ${v.pressure}'
          '${v.scamType != 'none' ? ', ${v.scamType}' : ''}');
    }
    if (v.knownScammer) knownScammerBlocked = true;

    if (v.pressure >= 2) _maybeTriggerAlarm(v);
    notifyListeners();
  }

  void _maybeTriggerAlarm(Verdict v) {
    final escalated = v.pressure > _alarmedPressure || v.recommendedWhisperClip != _alarmedClip;
    if (alarmActive || !escalated) return;
    _alarmedPressure = v.pressure;
    _alarmedClip = v.recommendedWhisperClip;
    alarmActive = true;
    alarmVerdict = v;
    _heavyHaptics();
    _whisper.play(v.recommendedWhisperClip, v.language).then((asset) {
      whisperPlaying = asset;
      notifyListeners();
    });
    if (v.knownScammer) {
      _autoHangup = Timer(const Duration(seconds: 4), endCall);
    }
  }

  void dismissAlarm() {
    alarmActive = false;
    _whisper.stop();
    whisperPlaying = null;
    notifyListeners();
  }

  Future<void> _heavyHaptics() async {
    HapticFeedback.heavyImpact();
    try {
      if (await Vibration.hasVibrator()) {
        Vibration.vibrate(pattern: [0, 600, 150, 600, 150, 900], intensities: [0, 255, 0, 255, 0, 255]);
      }
    } catch (_) {}
  }

  // ---- 1930 submission -----------------------------------------------------

  String get complaintDraft {
    final b = StringBuffer()
      ..writeln('To: National Cyber Crime Reporting Portal (cybercrime.gov.in) / Helpline 1930')
      ..writeln()
      ..writeln('Subject: Report of attempted ${_scamName(scamType)} via phone call')
      ..writeln()
      ..writeln('I wish to report a fraudulent phone call received on ${_date(_callStart ?? DateTime.now())} '
          'from the number $callerNumber, lasting ${_dur(elapsed)}.')
      ..writeln()
      ..writeln('The caller attempted a ${_scamName(scamType)}, with a peak pressure level of $peakPressure/3.');
    if (sawOtpAsk) b.writeln('The caller asked me to share an OTP / PIN.');
    if (sawSecrecy) b.writeln('The caller demanded secrecy and told me not to inform family or police.');
    b
      ..writeln('No money was transferred and no OTP/PIN was shared (call ended by me / by Chaukanna).')
      ..writeln()
      ..writeln('Call evidence with timestamps is saved and available on request. '
          'I request that the number $callerNumber be investigated and blocked.');
    return b.toString().trim();
  }

  String get familySummary => summaryForFamily.isNotEmpty
      ? summaryForFamily
      : 'A ${_scamName(scamType)} call from $callerNumber was detected'
          '${sawOtpAsk ? ' — the caller asked for an OTP/PIN' : ''}'
          '${sawSecrecy ? ' and demanded secrecy' : ''}. No money moved.';

  Future<void> submit1930() async {
    if (submitState == SubmitState.submitting || submitState == SubmitState.done) return;
    submitState = SubmitState.submitting;
    notifyListeners();
    final payload = {
      'action': 'confirm_1930_report',
      'confirmed_by_human': true,
      'caller_number': callerNumber,
      'scam_type': scamType,
      'peak_pressure': peakPressure,
      'asks_otp_or_pin': sawOtpAsk,
      'demands_secrecy': sawSecrecy,
      'duration_seconds': elapsed.inSeconds,
      'evidence': evidenceTimestamps,
      'complaint_text': complaintDraft,
      'submitted_at': DateTime.now().toUtc().toIso8601String(),
    };
    try {
      if (AppConfig.webhookConfigured) {
        final res = await http
            .post(Uri.parse(AppConfig.n8nApprovalWebhook),
                headers: {'Content-Type': 'application/json'}, body: jsonEncode(payload))
            .timeout(const Duration(seconds: 15));
        if (res.statusCode < 200 || res.statusCode >= 300) {
          throw Exception('Server replied ${res.statusCode}');
        }
        submitMessage = 'Report sent to the 1930 cybercrime team.';
      } else {
        await Future<void>.delayed(const Duration(milliseconds: 900));
        submitMessage = 'Demo mode: no webhook configured, report not actually sent.';
      }
      submitState = SubmitState.done;
    } catch (e) {
      submitState = SubmitState.failed;
      submitMessage = 'Could not send the report. Check internet and try again.';
    }
    notifyListeners();
  }

  // ---- offline simulator ---------------------------------------------------

  String simLanguage = 'hi';
  void setSimLanguage(String l) {
    simLanguage = l;
    notifyListeners();
  }

  static const _lines = {
    'safe': {
      'en': 'Hello sir, this is a courtesy call about your electricity bill for this month.',
      'hi': 'नमस्ते सर, यह इस महीने के आपके बिजली बिल के बारे में एक सामान्य कॉल है।',
      'kn': 'ನಮಸ್ಕಾರ ಸರ್, ಇದು ಈ ತಿಂಗಳ ನಿಮ್ಮ ವಿದ್ಯುತ್ ಬಿಲ್ ಬಗ್ಗೆ ಕರೆ.',
    },
    'otp': {
      'en': 'Your account will be blocked today. Please tell me the OTP you just received on your phone.',
      'hi': 'आपका खाता आज बंद हो जाएगा। आपके फोन पर जो OTP आया है वह अभी बताइए।',
      'kn': 'ನಿಮ್ಮ ಖಾತೆ ಇಂದೇ ಬ್ಲಾಕ್ ಆಗುತ್ತದೆ. ನಿಮ್ಮ ಫೋನ್‌ಗೆ ಬಂದ OTP ಈಗಲೇ ಹೇಳಿ.',
    },
    'arrest': {
      'en': 'This is CBI officer Sharma. A warrant is issued against you. You are under digital arrest, do not tell anyone and do not disconnect the call.',
      'hi': 'मैं CBI अधिकारी शर्मा बोल रहा हूँ। आपके खिलाफ वारंट जारी है। आप डिजिटल अरेस्ट में हैं, किसी को मत बताइए और कॉल मत काटिए।',
      'kn': 'ನಾನು CBI ಅಧಿಕಾರಿ ಶರ್ಮಾ. ನಿಮ್ಮ ವಿರುದ್ಧ ವಾರಂಟ್ ಹೊರಡಿಸಲಾಗಿದೆ. ನೀವು ಡಿಜಿಟಲ್ ಅರೆಸ್ಟ್‌ನಲ್ಲಿದ್ದೀರಿ, ಯಾರಿಗೂ ಹೇಳಬೇಡಿ, ಕರೆ ಕಟ್ ಮಾಡಬೇಡಿ.',
    },
    'known': {
      'en': 'Hello, I am calling from your bank, please verify your KYC details.',
      'hi': 'नमस्ते, मैं आपके बैंक से बोल रहा हूँ, कृपया अपनी KYC जानकारी बताइए।',
      'kn': 'ನಮಸ್ಕಾರ, ನಾನು ನಿಮ್ಮ ಬ್ಯಾಂಕ್‌ನಿಂದ ಕರೆ ಮಾಡುತ್ತಿದ್ದೇನೆ, ದಯವಿಟ್ಟು KYC ವಿವರ ನೀಡಿ.',
    },
  };

  void simulatePressure0() {
    startCall(number: '+91 80 4012 3456');
    ingest(Verdict(transcript: _lines['safe']![simLanguage]!, language: simLanguage));
  }

  void simulatePressure2Otp() {
    startCall(number: '+91 98765 41207');
    ingest(Verdict(
      transcript: _lines['otp']![simLanguage]!,
      scamType: 'bank_impersonation',
      pressure: 2,
      asksOtpOrPin: true,
      language: simLanguage,
      recommendedWhisperClip: 'warn_otp',
    ));
  }

  void simulatePressure3DigitalArrest() {
    startCall(number: '+91 70012 99881');
    ingest(Verdict(
      transcript: _lines['arrest']![simLanguage]!,
      scamType: 'digital_arrest',
      pressure: 3,
      demandsSecrecy: true,
      language: simLanguage,
      recommendedWhisperClip: 'warn_digital_arrest',
    ));
  }

  void simulateKnownScammer() {
    startCall(number: '+91 99887 76655');
    ingest(Verdict(
      transcript: _lines['known']![simLanguage]!,
      scamType: 'kyc_update',
      pressure: 3,
      language: simLanguage,
      recommendedWhisperClip: 'warn_known_scammer',
      knownScammer: true,
      summaryForFamily: 'A number already on the shared scammer blocklist called Papa. '
          'Chaukanna warned him and auto-blocked the call.',
    ));
  }

  // ---- helpers -------------------------------------------------------------

  static String _scamName(String t) => const {
        'digital_arrest': 'digital arrest scam',
        'kyc_update': 'KYC update scam',
        'bank_impersonation': 'bank impersonation scam',
        'prize_lottery': 'prize/lottery scam',
      }[t] ??
      'suspected scam';

  static String _two(int n) => n.toString().padLeft(2, '0');
  static String _clock(DateTime d) => '${_two(d.hour)}:${_two(d.minute)}:${_two(d.second)}';
  static String _date(DateTime d) => '${_two(d.day)}-${_two(d.month)}-${d.year} at ${_clock(d)}';
  static String _dur(Duration d) => '${_two(d.inMinutes)}:${_two(d.inSeconds % 60)}';

  @override
  void dispose() {
    _ticker?.cancel();
    _autoHangup?.cancel();
    _whisper.dispose();
    _livekit.disconnect();
    super.dispose();
  }
}
