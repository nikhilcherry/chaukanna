import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:vibration/vibration.dart';

import '../config.dart';
import '../models/messages.dart';
import '../models/verdict.dart';
import '../services/approval_client.dart';
import '../services/clip_catalog.dart';
import '../services/livekit_service.dart';
import '../services/whisper_gate.dart';
import '../services/whisper_player.dart';
import '../util/otp_mask.dart';
import 'debug_log.dart';
import 'demo_content.dart';

enum CallPhase { idle, active, ended }

enum SubmitState { idle, submitting, done, failed }

/// The "Protected" badge (CONTRACTS §4d).
enum GuardianStatus { protected, stale, waiting, offline }

enum WhisperStatus { idle, playing, done, stopped, failed }

class WhisperState {
  const WhisperState(this.status, {this.clip = 'none', this.current, this.error = ''});
  static const idle = WhisperState(WhisperStatus.idle);

  final WhisperStatus status;
  final String clip;
  final ClipRef? current;
  final String error;

  bool get playing => status == WhisperStatus.playing;
}

class AlarmInfo {
  const AlarmInfo({
    required this.serial,
    required this.clip,
    required this.language,
    required this.pressure,
    required this.scamType,
    this.knownScammer = false,
  });

  final int serial;
  final String clip; // 'none' = generic warning
  final String language;
  final int pressure;
  final String scamType;
  final bool knownScammer;
}

class EvidenceEntry {
  const EvidenceEntry(this.offset, this.at, this.text);
  final Duration offset;
  final DateTime at;
  final String text;

  String format() => '[${mmss(offset)}] $text';
}

/// Shown on the idle screen after a call that needed no follow-up.
class LastCall {
  const LastCall(this.number, this.duration, this.reason);
  final String number;
  final Duration duration;
  final String reason;
}

class Notice {
  const Notice(this.text, {this.error = false});
  final String text;
  final bool error;
}

typedef Haptics = Future<void> Function();

/// '+919876543210' / '9876543210' -> '+91 98765 43210'; anything else unchanged.
String formatIndianNumber(String n) {
  final digits = n.replaceAll(RegExp(r'[\s-]'), '');
  final m = RegExp(r'^(?:\+?91)?([6-9]\d{9})$').firstMatch(digits);
  if (m == null) return n;
  final d = m.group(1)!;
  return '+91 ${d.substring(0, 5)} ${d.substring(5)}';
}

String mmss(Duration d) => '${d.inMinutes.toString().padLeft(2, '0')}:${(d.inSeconds % 60).toString().padLeft(2, '0')}';

/// Single source of truth. LiveKit packets and the Demo Simulator both go
/// through [handleData] -> [parseGuardianMessage] -> [handleMessage].
class GuardianController extends ChangeNotifier {
  GuardianController({
    WhisperEngine? whisper,
    ApprovalClient? approval,
    ClipCatalog? catalog,
    DateTime Function()? clock,
    Haptics? haptics,
    bool useLiveKit = true,
  }) : _engine = whisper ?? JustAudioWhisperEngine(),
       _approval = approval ?? ApprovalClient(webhook: AppConfig.n8nApprovalWebhook),
       catalog = catalog ?? ClipCatalog(),
       _catalogInjected = catalog != null,
       _now = clock ?? DateTime.now,
       _haptics = haptics ?? _defaultHaptics {
    if (useLiveKit && AppConfig.liveKitConfigured) {
      final t = LiveKitTransport(
        onData: (d, topic) => handleData(d, topic: topic),
        onCallerJoined: _onCallerJoined,
        onCallerLeft: _onCallerLeft,
        log: (m, {important = false}) => _log(m, important: important),
      );
      t.state.addListener(_notify);
      _transport = t;
    }
    _clockTimer = Timer.periodic(const Duration(seconds: 1), (_) => _tick());
  }

  static const heartbeatTimeout = Duration(seconds: 15);
  static const incidentWait = Duration(seconds: 50);

  final WhisperEngine _engine;
  final ApprovalClient _approval;
  final DateTime Function() _now;
  final Haptics _haptics;
  final bool _catalogInjected;
  LiveKitTransport? _transport;
  ClipCatalog catalog;
  Timer? _clockTimer;
  bool _disposed = false;

  final DebugLog log = DebugLog();
  final _notices = StreamController<Notice>.broadcast();
  Stream<Notice> get notices => _notices.stream;

  // ---- per-call record (cleared by _resetCall) ------------------------------
  CallPhase phase = CallPhase.idle;
  String? callId;
  bool simulated = false;
  String callerNumber = '';
  String callerLabel = '';
  String? _callerIdentity;
  DateTime? callStartedAt;
  Duration elapsed = Duration.zero;
  String callLanguage = normLang(AppConfig.preferredLanguage);
  final List<TranscriptLine> transcript = [];
  Verdict verdict = const Verdict();
  int peakPressure = 0;
  bool sawOtpAsk = false;
  bool sawSecrecy = false;
  bool knownScammer = false;
  String scamType = 'none';
  String summaryForFamily = '';
  final List<EvidenceEntry> evidence = [];
  DateTime? firstHighRiskAt;
  IncidentInfo? incident;
  String endReason = '';
  bool userMuted = false;
  bool speaker = AppConfig.speakerByDefault;

  bool alarmActive = false;
  AlarmInfo? alarm;
  int _alarmSerial = 0;
  int _alarmedPressure = 0;
  final Set<String> _alarmedClips = {};

  WhisperState whisper = WhisperState.idle;
  int _whisperToken = 0;
  bool _micPausedForWhisper = false;
  bool _callerDucked = false;
  bool? _micApplied;
  final WhisperGate _gate = WhisperGate();
  Timer? _autoHangup;

  SubmitState submitState = SubmitState.idle;
  String submitMessage = '';
  String submitRoute = '';

  // ---- survives calls -------------------------------------------------------
  DateTime? lastHeartbeatAt;
  bool _lastHeartbeatSimulated = false;
  GuardianStatus? _lastStatus;
  String? lastEndedCallId;
  LastCall? lastCall;
  String simLanguage = normLang(AppConfig.preferredLanguage);

  // ---- derived --------------------------------------------------------------
  bool get highRiskCall => peakPressure >= 2 || knownScammer;
  bool get micPausedForWhisper => _micPausedForWhisper;
  bool get liveKitEnabled => _transport != null;
  LinkState get link => _transport?.state.value ?? LinkState.off;

  GuardianStatus get guardianStatus {
    final hb = lastHeartbeatAt;
    if (hb != null && _now().difference(hb) <= heartbeatTimeout) return GuardianStatus.protected;
    if (hb != null && !_lastHeartbeatSimulated) return GuardianStatus.stale;
    if (_transport == null) return GuardianStatus.offline;
    return GuardianStatus.waiting;
  }

  bool get incidentTimedOut =>
      incident == null && firstHighRiskAt != null && _now().difference(firstHighRiskAt!) > incidentWait;
  bool get waitingForIncident => incident == null && firstHighRiskAt != null && !incidentTimedOut;

  // ---- lifecycle ------------------------------------------------------------

  Future<void> init({AssetBundle? bundle}) async {
    if (!_catalogInjected) catalog = await ClipCatalog.load(bundle ?? rootBundle);
    final n = catalog.bundledAudioCount;
    _log('Whisper clips: ${n ?? 'unknown number of'} WAVs bundled');
    for (final l in ClipCatalog.languages) {
      final missing = catalog.missingAudio(l);
      if (missing.isNotEmpty) _log('Missing whisper audio: ${missing.join(', ')}', important: true);
    }
    _preload(callLanguage);
    if (_transport == null) {
      _log(AppConfig.liveKitConfigured ? 'LiveKit disabled' : 'No LiveKit config: offline demo mode');
    }
    await _transport?.start();
    _notify();
  }

  void _tick() {
    if (_disposed) return;
    var changed = false;
    if (phase == CallPhase.active && callStartedAt != null) {
      elapsed = _now().difference(callStartedAt!);
      changed = true;
    }
    final s = guardianStatus;
    if (s != _lastStatus) {
      _lastStatus = s;
      changed = true;
    }
    if (phase == CallPhase.ended && incident == null && firstHighRiskAt != null) changed = true;
    if (changed) notifyListeners();
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  void _log(String message, {bool important = false}) {
    log.add(message, important: important, at: _now());
  }

  void _emit(String text, {bool error = false}) {
    if (!_notices.isClosed) _notices.add(Notice(text, error: error));
  }

  // ---- inbound messages -----------------------------------------------------

  void handleData(List<int> data, {String? topic}) {
    if (_disposed) return;
    if (!acceptsTopic(topic)) {
      _log('Ignored data on topic "$topic"');
      return;
    }
    final m = parseGuardianMessage(data);
    if (m == null) {
      _log('Ignored message: unknown type or bad JSON (${data.length} bytes)');
      return;
    }
    handleMessage(m);
  }

  void handleMessage(GuardianMessage m) {
    if (_disposed) return;
    lastHeartbeatAt = _now();
    _lastHeartbeatSimulated = _isSim(m.callId);
    switch (m) {
      case HeartbeatMessage():
        break;
      case CallStartedMessage():
        _onCallStarted(m);
      case VerdictMessage():
        _onVerdict(m);
      case IncidentMessage():
        _onIncident(m);
      case CallEndedMessage():
        _onCallEnded(m);
    }
    _notify();
  }

  static bool _isSim(String id) => id.startsWith('sim-');

  void _onCallStarted(CallStartedMessage m) {
    if (phase != CallPhase.active && m.callId.isNotEmpty && m.callId == lastEndedCallId) {
      // The bridge re-sends call_started when this phone rejoins mid-call; the
      // user already hung up on this one.
      _log('Ignored call_started for ended call ${m.callId}');
      return;
    }
    if (phase == CallPhase.active) {
      final sameCall = callId == null || m.callId.isEmpty || m.callId == callId;
      final simToReal = simulated && !_isSim(m.callId);
      if (sameCall && !simToReal) {
        if (m.callId.isNotEmpty) callId = m.callId;
        if (m.callerNumber.isNotEmpty) _setCaller(m.callerNumber, label: m.callerLabel);
        if (m.knownScammer) _onKnownScammer();
        return;
      }
    }
    _beginCall(id: m.callId, number: m.callerNumber, label: m.callerLabel);
    if (m.knownScammer) _onKnownScammer();
  }

  void _onVerdict(VerdictMessage m) {
    final id = m.callId;
    if (phase != CallPhase.active) {
      if (id.isNotEmpty && id == lastEndedCallId) {
        _log('Ignored late verdict for ended call $id');
        return;
      }
      if (phase == CallPhase.ended && id.isEmpty) {
        _log('Ignored verdict with no call_id after the call ended');
        return;
      }
      _beginCall(id: id, number: m.verdict.callerNumber);
    } else if (id.isNotEmpty && callId != null && id != callId) {
      _log('Verdict for a new call $id (call_started was missed)');
      _beginCall(id: id, number: m.verdict.callerNumber);
    } else if (id.isNotEmpty && callId == null) {
      callId = id;
    }

    final v = m.verdict;
    final now = _now();
    if (v.callerNumber.isNotEmpty && callerNumber == _unknown) _setCaller(v.callerNumber);
    verdict = v;
    final lang = normLang(m.language);
    if (lang != callLanguage && ClipCatalog.languages.contains(lang)) {
      callLanguage = lang;
      _preload(lang);
    }
    final pressure = math.max(m.pressure, v.pressure);
    final text = maskOtp(m.chunkText.trim());
    if (text.isNotEmpty) transcript.add(TranscriptLine(text, now, pressure, speaker: m.speaker));

    peakPressure = math.max(peakPressure, pressure);
    sawOtpAsk |= v.asksOtpOrPin;
    sawSecrecy |= v.demandsSecrecy;
    if (v.isScam) scamType = v.scamType;
    if (v.summaryForFamily.isNotEmpty) summaryForFamily = v.summaryForFamily;
    if (peakPressure >= 2) firstHighRiskAt ??= now;
    if (pressure >= 2 || v.asksOtpOrPin || v.demandsSecrecy) {
      _addEvidence(now, '${_flagSummary(pressure, v)}${text.isEmpty ? '' : ' - ${m.speaker}: "${_snippet(text)}"'}');
    }
    if (m.latencyMs != null) _log('Verdict p$pressure ${v.scamType} from ${m.speaker} (${m.latencyMs} ms)');
    if (v.knownScammer) _onKnownScammer();

    final clip = m.clipToPlay;
    if (clip != 'none') unawaited(_playWhisper(clip, lang));
    final newClip = clip != 'none' && !_alarmedClips.contains(clip);
    if (peakPressure >= 2 && (peakPressure > _alarmedPressure || newClip)) {
      _raiseAlarm(clip != 'none' ? clip : _clipFromFlags(), lang);
    }
  }

  void _onIncident(IncidentMessage m) {
    final id = m.callId;
    final matches = id.isEmpty || id == callId || (callId == null && phase == CallPhase.active);
    if (phase == CallPhase.idle || !matches) {
      _log('Ignored incident for ${id.isEmpty ? 'unknown call' : id} (current: ${callId ?? 'none'})');
      return;
    }
    if (callId == null && id.isNotEmpty) callId = id;
    final i = m.incident;
    incident = i;
    if (i.knownScammer == true) {
      if (phase == CallPhase.active) {
        _onKnownScammer();
      } else {
        knownScammer = true;
      }
    }
    String yn(bool? b) => b == null ? '?' : (b ? 'yes' : 'no');
    _log(
      'n8n incident ${i.incidentId.isEmpty ? '(no id)' : i.incidentId}: family ${yn(i.familyAlerted)}, '
      'evidence ${yn(i.evidenceSaved)}, blocklist ${yn(i.blocklisted)}, '
      'approve_url ${i.approveUrl.isEmpty ? 'none' : (ApprovalClient.isReachableUrl(i.approveUrl) ? 'ok' : 'UNREACHABLE (${i.approveUrl})')}',
    );
  }

  void _onCallEnded(CallEndedMessage m) {
    if (phase != CallPhase.active) return;
    if (m.callId.isEmpty || callId == null || m.callId == callId) unawaited(endCall(reason: 'The caller hung up'));
  }

  void _onCallerJoined(CallerInfo info) {
    if (_disposed) return;
    if (phase == CallPhase.active && !simulated) {
      _callerIdentity ??= info.identity;
      if (callerNumber == _unknown) _setCaller(info.number);
      _notify();
      return;
    }
    _beginCall(number: info.number, identity: info.identity);
    _notify();
  }

  void _onCallerLeft(String identity) {
    if (phase != CallPhase.active || simulated) return;
    if (_callerIdentity == null || _callerIdentity == identity) unawaited(endCall(reason: 'The caller hung up'));
  }

  // ---- call lifecycle -------------------------------------------------------

  static const _unknown = 'Unknown number';

  void _beginCall({String? id, String number = '', String label = '', String? identity}) {
    final sim = _isSim(id ?? '');
    if (!sim) _cancelSim();
    _resetCall();
    callId = (id == null || id.isEmpty) ? null : id;
    simulated = sim;
    _callerIdentity = identity;
    _setCaller(number, label: label);
    phase = CallPhase.active;
    callStartedAt = _now();
    lastCall = null;
    callLanguage = sim ? simLanguage : normLang(AppConfig.preferredLanguage);
    final route = (sim || _transport == null || AppConfig.whisperRoute == 'media')
        ? WhisperRoute.media
        : WhisperRoute.call;
    unawaited(_engine.setRoute(route));
    _preload(callLanguage);
    unawaited(_transport?.setRemoteAudio(true));
    unawaited(_transport?.setSpeaker(speaker));
    _applyMic();
    if (sim) {
      _startSimHeartbeat();
    } else {
      _stopSimHeartbeat();
    }
    _log('Call started${callId == null ? '' : ' ($callId)'} from $callerNumber');
  }

  /// [raw] may be "+91 98765 43210 - CBI Officer" (dialer text) or a bare
  /// number; [label] is the bridge's caller_label, which may repeat the number.
  void _setCaller(String raw, {String label = ''}) {
    final s = raw.trim();
    final i = s.indexOf(' - ');
    callerNumber = s.isEmpty ? _unknown : (i > 0 ? s.substring(0, i).trim() : s);
    var l = i > 0 ? s.substring(i + 3).trim() : '';
    final given = label.trim();
    if (given.isNotEmpty) {
      final j = given.indexOf(' - ');
      final candidate = j >= 0 ? given.substring(j + 3).trim() : given;
      final digits = RegExp(r'\d').allMatches(candidate).length;
      if (candidate.isNotEmpty && digits < 6) l = candidate; // not just the number again
    }
    callerLabel = l;
  }

  /// The caller's number grouped for reading aloud: +91 98765 43210.
  String get callerDisplay => formatIndianNumber(callerNumber);

  void _resetCall() {
    _whisperToken++;
    unawaited(_engine.stop());
    _autoHangup?.cancel();
    _autoHangup = null;
    _simIncidentTimer?.cancel();
    _simIncidentTimer = null;
    callId = null;
    simulated = false;
    _callerIdentity = null;
    callerNumber = '';
    callerLabel = '';
    callStartedAt = null;
    elapsed = Duration.zero;
    transcript.clear();
    verdict = const Verdict();
    peakPressure = 0;
    sawOtpAsk = false;
    sawSecrecy = false;
    knownScammer = false;
    scamType = 'none';
    summaryForFamily = '';
    evidence.clear();
    firstHighRiskAt = null;
    incident = null;
    endReason = '';
    alarmActive = false;
    alarm = null;
    _alarmedPressure = 0;
    _alarmedClips.clear();
    whisper = WhisperState.idle;
    _micPausedForWhisper = false;
    _callerDucked = false;
    _gate.reset();
    submitState = SubmitState.idle;
    submitMessage = '';
    submitRoute = '';
    userMuted = false;
    speaker = AppConfig.speakerByDefault;
  }

  /// Hang up (button), or the remote side ended. High-risk calls go to the
  /// post-call screen; anything else resets to idle.
  Future<void> endCall({String reason = 'You hung up'}) async {
    if (phase != CallPhase.active) return;
    _autoHangup?.cancel();
    if (callStartedAt != null) elapsed = _now().difference(callStartedAt!);
    _whisperToken++;
    if (whisper.playing) whisper = WhisperState(WhisperStatus.stopped, clip: whisper.clip);
    _micPausedForWhisper = false;
    _callerDucked = false;
    alarmActive = false;
    lastEndedCallId = callId;
    endReason = reason;
    final high = highRiskCall;
    phase = high ? CallPhase.ended : CallPhase.idle;
    _applyMic();
    unawaited(_transport?.setRemoteAudio(false));
    unawaited(_engine.stop());
    _log('Call ended: $reason (${high ? 'high risk' : 'no scam found'})');
    if (!high) {
      final note = LastCall(callerDisplay, elapsed, reason);
      _resetCall();
      lastCall = note;
    }
    _notify();
  }

  /// "Done" on the post-call screen.
  void finishPostCall() {
    _resetCall();
    phase = CallPhase.idle;
    _notify();
  }

  // ---- call controls --------------------------------------------------------

  void toggleMute() {
    userMuted = !userMuted;
    _applyMic();
    _notify();
  }

  void toggleSpeaker() {
    speaker = !speaker;
    unawaited(_transport?.setSpeaker(speaker));
    _notify();
  }

  void _applyMic() {
    final on = phase == CallPhase.active && !userMuted && !_micPausedForWhisper;
    if (_micApplied == on) return;
    _micApplied = on;
    unawaited(_transport?.setMicEnabled(on));
  }

  void _duckCaller(bool duck) {
    if (_callerDucked == duck) return;
    _callerDucked = duck;
    if (phase == CallPhase.active) unawaited(_transport?.setRemoteAudio(!duck));
  }

  // ---- alarm + whisper ------------------------------------------------------

  void _raiseAlarm(String clip, String lang, {int? pressure}) {
    final p = math.max(peakPressure, pressure ?? 0);
    _alarmedPressure = math.max(_alarmedPressure, p);
    if (clip != 'none') _alarmedClips.add(clip);
    alarm = AlarmInfo(
      serial: ++_alarmSerial,
      clip: clip,
      language: lang,
      pressure: p,
      scamType: scamType,
      knownScammer: knownScammer,
    );
    alarmActive = true;
    unawaited(_haptics().catchError((Object _) {}));
    _log('ALARM ${clip == 'none' ? 'generic' : clip} at pressure $p');
  }

  /// Mirrors the classifier's clip priority (OTP > digital arrest > secrecy).
  String _clipFromFlags() {
    if (sawOtpAsk) return 'warn_otp';
    if (scamType == 'digital_arrest') return 'warn_digital_arrest';
    if (sawSecrecy) return 'warn_secrecy';
    if (knownScammer) return 'warn_known_scammer';
    return 'none';
  }

  void _onKnownScammer() {
    if (knownScammer) return;
    knownScammer = true;
    peakPressure = 3;
    if (scamType == 'none') scamType = 'other';
    final now = _now();
    firstHighRiskAt ??= now;
    _addEvidence(now, 'Caller number is on the shared scam-number list');
    unawaited(_playWhisper('warn_known_scammer', callLanguage));
    _raiseAlarm('warn_known_scammer', callLanguage, pressure: 3);
    if (AppConfig.autoBlockKnownScammers) {
      // Hang up once the warning (short + full) has had time to play.
      final ms = catalog
          .sequence('warn_known_scammer', callLanguage)
          .fold<int>(0, (sum, r) => sum + (r.durationMs ?? 3000));
      _autoHangup?.cancel();
      _autoHangup = Timer(
        Duration(milliseconds: math.max(ms, 3000) + 1500),
        () => unawaited(endCall(reason: 'Blocked: known scammer number')),
      );
    }
  }

  Future<void> _playWhisper(String clip, String lang) async {
    if (!_gate.tryAcquire(clip, _now())) {
      _log('Whisper $clip skipped: already played in the last ${_gate.window.inSeconds} s');
      return;
    }
    final seq = catalog.sequence(clip, lang);
    final token = ++_whisperToken;
    if (seq.isEmpty) {
      _whisperFailed(clip, 'no audio bundled for $clip ($lang)');
      return;
    }
    whisper = WhisperState(WhisperStatus.playing, clip: clip, current: seq.first);
    _micPausedForWhisper = AppConfig.muteMicDuringWhisper;
    _applyMic();
    _duckCaller(seq.first.variant == 'short');
    _log('Whisper $clip: ${seq.map((r) => r.asset.split('/').last).join(' then ')}');
    _notify();
    try {
      final out = await _engine.play(
        clip,
        seq,
        onClip: (ref) {
          if (token != _whisperToken || _disposed) return;
          whisper = WhisperState(WhisperStatus.playing, clip: clip, current: ref);
          if (ref.variant == 'full') _duckCaller(false);
          _notify();
        },
      );
      if (token != _whisperToken) return;
      whisper = WhisperState(
        out == WhisperOutcome.completed ? WhisperStatus.done : WhisperStatus.stopped,
        clip: clip,
        current: whisper.current,
      );
    } catch (e) {
      if (token != _whisperToken) return;
      _whisperFailed(clip, '$e');
    } finally {
      if (token == _whisperToken && !_disposed) {
        _micPausedForWhisper = false;
        _applyMic();
        _duckCaller(false);
        _notify();
      }
    }
  }

  void _whisperFailed(String clip, String why) {
    whisper = WhisperState(WhisperStatus.failed, clip: clip, error: why);
    _log('Whisper FAILED: $why', important: true);
    _emit('Voice warning could not play ($why). The warning is on screen.', error: true);
    _notify();
  }

  void _preload(String lang) {
    final seqs = {for (final c in ClipCatalog.clipIds) c: catalog.sequence(c, lang)};
    _engine
        .preload(seqs)
        .then((failed) {
          for (final f in failed) {
            _log('Preload failed: $f', important: true);
          }
          if (failed.isNotEmpty) _emit('Some voice warnings could not load. Open the simulator log.', error: true);
        })
        .catchError((Object e) {
          _log('Preload error: $e', important: true);
        });
  }

  /// "I understand" on the alarm: hide it and stop the voice.
  void dismissAlarm() {
    alarmActive = false;
    _whisperToken++;
    unawaited(_engine.stop());
    if (whisper.playing) whisper = WhisperState(WhisperStatus.stopped, clip: whisper.clip, current: whisper.current);
    _micPausedForWhisper = false;
    _applyMic();
    _duckCaller(false);
    _notify();
  }

  static Future<void> _defaultHaptics() async {
    try {
      await HapticFeedback.heavyImpact();
    } catch (_) {}
    try {
      if (await Vibration.hasVibrator()) {
        await Vibration.vibrate(pattern: [0, 600, 150, 600, 150, 900], intensities: [0, 255, 0, 255, 0, 255]);
      }
    } catch (_) {}
  }

  // ---- evidence + 1930 ------------------------------------------------------

  void _addEvidence(DateTime at, String text) {
    final start = callStartedAt ?? at;
    evidence.add(EvidenceEntry(at.difference(start), at, text));
  }

  String _flagSummary(int pressure, Verdict v) => [
    'pressure $pressure',
    if (v.isScam) _scamName(v.scamType),
    if (v.asksOtpOrPin) 'OTP/PIN ask',
    if (v.demandsSecrecy) 'secrecy demand',
  ].join(', ');

  static String _snippet(String s) => s.length <= 90 ? s : '${s.substring(0, 87)}...';

  String get localComplaintDraft {
    final when = callStartedAt ?? _now();
    final b = StringBuffer()
      ..writeln('To: National Cyber Crime Reporting Portal (cybercrime.gov.in) / Helpline 1930')
      ..writeln()
      ..writeln('Subject: Report of attempted ${_scamName(scamType)} via phone call')
      ..writeln()
      ..writeln(
        'I wish to report a fraudulent phone call received on ${_date(when)} '
        'from the number $callerNumber, lasting ${mmss(elapsed)}.',
      )
      ..writeln()
      ..writeln('The caller attempted a ${_scamName(scamType)}, with a peak pressure level of $peakPressure/3.');
    if (knownScammer) b.writeln('This number is already on the shared scam-number list.');
    if (sawOtpAsk) b.writeln('The caller asked me to share an OTP / PIN.');
    if (sawSecrecy) b.writeln('The caller demanded secrecy and told me not to inform family or police.');
    b
      ..writeln('No money was transferred and no OTP/PIN was shared.')
      ..writeln()
      ..writeln(
        'Call evidence with timestamps is saved and available on request. '
        'I request that the number $callerNumber be investigated and blocked.',
      );
    return b.toString().trim();
  }

  /// The English complaint the human confirms: n8n's AI draft, else the local template.
  String get complaintEnglish {
    final en = incident?.complaintEn.trim() ?? '';
    return en.isNotEmpty ? en : localComplaintDraft;
  }

  String? get complaintLocal => incident?.hasLocalDraft == true ? incident!.complaintLocal.trim() : null;
  String get complaintLocalLang => incident?.complaintLanguage ?? 'en';
  bool get complaintFromN8n => (incident?.complaintEn.trim().isNotEmpty ?? false) || complaintLocal != null;

  String get familySummary {
    final fromN8n = incident?.familyAlert.trim() ?? '';
    if (fromN8n.isNotEmpty) return fromN8n;
    if (summaryForFamily.isNotEmpty) return summaryForFamily;
    return 'A ${_scamName(scamType)} call from $callerNumber was detected'
        '${sawOtpAsk ? '; the caller asked for an OTP/PIN' : ''}'
        '${sawSecrecy ? '; the caller demanded secrecy' : ''}. No money moved.';
  }

  /// CONTRACTS §3 body (plus additive complaint_text_local / complaint_language / known_scammer).
  Map<String, dynamic> approvalPayload() => {
    'action': 'confirm_1930_report',
    'confirmed_by_human': true,
    'call_id': callId ?? lastEndedCallId ?? '',
    'victim_id': AppConfig.victimId,
    if (incident?.incidentId.isNotEmpty == true) 'incident_id': incident!.incidentId,
    'caller_number': callerNumber,
    'scam_type': scamType,
    'peak_pressure': peakPressure,
    'asks_otp_or_pin': sawOtpAsk,
    'demands_secrecy': sawSecrecy,
    'known_scammer': knownScammer,
    'duration_seconds': elapsed.inSeconds,
    'evidence': [for (final e in evidence) e.format()],
    'complaint_text': complaintEnglish,
    'complaint_text_local': ?complaintLocal,
    'complaint_language': complaintLocal != null ? complaintLocalLang : 'en',
    'submitted_at': _now().toUtc().toIso8601String(),
  };

  /// The one irreversible action; the screen asks for explicit confirmation first.
  Future<void> submit1930() async {
    if (phase != CallPhase.ended) return;
    if (submitState == SubmitState.submitting || submitState == SubmitState.done) return;
    submitState = SubmitState.submitting;
    _notify();
    final payload = approvalPayload();
    if (simulated) {
      await Future<void>.delayed(const Duration(milliseconds: 900));
      if (_disposed) return;
      submitState = SubmitState.done;
      submitRoute = 'demo';
      submitMessage = 'Demo call: the report was not really sent.';
      _log('Approval for simulated call ${payload['call_id']} not sent (demo)');
      _notify();
      return;
    }
    final out = await _approval.submit(payload, approveUrl: incident?.approveUrl, log: (m) => _log(m));
    if (_disposed) return;
    submitRoute = out.route;
    if (out.ok) {
      submitState = SubmitState.done;
      submitMessage = 'Report sent. The response team will file it with 1930 and send you a receipt.';
    } else {
      submitState = SubmitState.failed;
      submitMessage = out.route == 'none'
          ? 'No reporting link is set up on this phone.'
          : 'Could not send the report. Check the internet and try again.';
      _emit('Report not sent: ${out.detail}', error: true);
    }
    _notify();
  }

  // ---- offline Demo Simulator ----------------------------------------------
  // Everything goes through handleData() as JSON bytes, exactly like LiveKit.

  final List<Timer> _scriptTimers = [];
  Timer? _simHeartbeat;
  Timer? _simIncidentTimer;
  int _simSeq = 0;

  bool get scriptRunning => _scriptTimers.any((t) => t.isActive);

  void setSimLanguage(String l) {
    simLanguage = normLang(l);
    _notify();
  }

  double get _ts => _now().millisecondsSinceEpoch / 1000;
  String _newSimId() => 'sim-${(_now().millisecondsSinceEpoch % 0xFFFFFF).toRadixString(16)}${++_simSeq}';

  void _inject(Map<String, dynamic> msg) => handleData(utf8.encode(jsonEncode(msg)), topic: kGuardianTopic);

  Map<String, dynamic> _verdictJson(String id, String speaker, String text, Map<String, Object> v, String lang) {
    final clip = (v['whisper_clip'] as String?) ?? 'none';
    return {
      'type': 'verdict',
      'call_id': id,
      'speaker': speaker,
      'chunk_text': text,
      'language': lang,
      'verdict': {
        'call_id': id,
        'scam_type': v['scam_type'] ?? 'none',
        'pressure': v['pressure'] ?? 0,
        'asks_otp_or_pin': v['asks_otp_or_pin'] ?? false,
        'demands_secrecy': v['demands_secrecy'] ?? false,
        'confidence': 0.92,
        'language': lang,
        'recommended_whisper_clip': clip,
        'known_scammer': v['known_scammer'] ?? false,
        'summary_for_family': '',
      },
      'pressure': v['pressure'] ?? 0,
      'whisper': clip != 'none',
      'whisper_clip': clip,
      'ts': _ts,
      'latency_ms': 850,
    };
  }

  Map<String, dynamic> _simIncidentJson() {
    final lang = callLanguage;
    final when = callStartedAt ?? _now();
    final type = scamType == 'none' ? 'other' : scamType;
    String draft(String l) => simComplaint(
      l,
      scamType: type,
      number: callerNumber,
      when: when,
      otp: sawOtpAsk,
      secrecy: sawSecrecy,
      known: knownScammer,
    );
    return {
      'type': 'incident',
      'call_id': callId,
      'ok': true,
      'incident_id': 'sim-inc-${_simSeq.toString().padLeft(4, '0')}',
      'known_scammer': knownScammer,
      'family_alerted': true,
      'evidence_saved': true,
      'blocklisted': true,
      'complaint_draft': {'en': draft('en'), 'local': lang == 'en' ? '' : draft(lang), 'language': lang},
      'family_alert': simFamilyAlert(
        victimName: AppConfig.victimName,
        scamType: type,
        number: callerNumber,
        otp: sawOtpAsk,
        secrecy: sawSecrecy,
        known: knownScammer,
      ),
      'approve_url': '',
      'ts': _ts,
    };
  }

  String _ensureSimCall(String number, {bool known = false}) {
    if (phase == CallPhase.active) return callId ?? '';
    _cancelSim();
    final id = _newSimId();
    _inject({'type': 'call_started', 'call_id': id, 'caller_number': number, 'known_scammer': known, 'ts': _ts});
    return id;
  }

  /// Fakes n8n's incident reply a few seconds after a simulated high-risk verdict.
  void _scheduleSimIncident({Duration after = const Duration(seconds: 3)}) {
    if (!simulated || incident != null || _simIncidentTimer?.isActive == true) return;
    _simIncidentTimer = Timer(after, () {
      if (simulated && incident == null && phase != CallPhase.idle) _inject(_simIncidentJson());
    });
  }

  void _startSimHeartbeat() {
    _simHeartbeat?.cancel();
    void beat() {
      if (phase == CallPhase.active && simulated) {
        _inject({'type': 'heartbeat', 'call_id': callId, 'ts': _ts});
      } else {
        _stopSimHeartbeat();
      }
    }

    _simHeartbeat = Timer.periodic(const Duration(seconds: 5), (_) => beat());
    scheduleMicrotask(beat);
  }

  void _stopSimHeartbeat() {
    _simHeartbeat?.cancel();
    _simHeartbeat = null;
  }

  void _cancelSim() {
    for (final t in _scriptTimers) {
      t.cancel();
    }
    _scriptTimers.clear();
    _simIncidentTimer?.cancel();
    _simIncidentTimer = null;
  }

  void simulatePressure0() {
    final id = _ensureSimCall('+91 80 4012 3456');
    _inject(
      _verdictJson(id, 'caller', pickLine(simSafeLine, simLanguage), const {
        'scam_type': 'none',
        'pressure': 0,
      }, simLanguage),
    );
  }

  void simulatePressure2Otp() {
    final id = _ensureSimCall('+91 98765 41207');
    _inject(
      _verdictJson(id, 'caller', pickLine(simOtpLine, simLanguage), const {
        'scam_type': 'bank_impersonation',
        'pressure': 2,
        'asks_otp_or_pin': true,
        'whisper_clip': 'warn_otp',
      }, simLanguage),
    );
    _scheduleSimIncident();
  }

  void simulatePressure3DigitalArrest() {
    final id = _ensureSimCall('+91 70012 99881');
    _inject(
      _verdictJson(id, 'caller', pickLine(simArrestLine, simLanguage), const {
        'scam_type': 'digital_arrest',
        'pressure': 3,
        'demands_secrecy': true,
        'whisper_clip': 'warn_digital_arrest',
      }, simLanguage),
    );
    _scheduleSimIncident();
  }

  void simulateKnownScammer() {
    final id = _ensureSimCall('+91 99887 76655', known: true);
    _inject(
      _verdictJson(id, 'caller', pickLine(simKnownLine, simLanguage), const {
        'scam_type': 'kyc_update',
        'pressure': 3,
        'known_scammer': true,
      }, simLanguage),
    );
    _scheduleSimIncident(after: const Duration(seconds: 2));
  }

  /// The whole demo offline: call_started -> rising verdicts -> whispers ->
  /// n8n incident -> call_ended (post-call screen). About 40 s.
  void runFullScamCall() {
    _cancelSim();
    if (phase != CallPhase.idle) {
      _resetCall();
      phase = CallPhase.idle;
    }
    final lang = simLanguage;
    final id = _newSimId();
    const lineAt = [1500, 4500, 8000, 12000, 18000, 27000, 31000];
    final steps = <(int, Map<String, dynamic> Function())>[
      (0, () => {'type': 'call_started', 'call_id': id, 'caller_number': '+91 98765 43210 - CBI Officer', 'ts': _ts}),
      for (var i = 0; i < fullScamScript.length; i++)
        (
          lineAt[i],
          () => _verdictJson(
            id,
            fullScamScript[i].speaker,
            fullScamScript[i].textFor(lang),
            fullScamScript[i].verdict,
            lang,
          ),
        ),
      (34000, _simIncidentJson),
      (40000, () => {'type': 'call_ended', 'call_id': id, 'ts': _ts}),
    ];
    for (final (ms, build) in steps) {
      _scriptTimers.add(
        Timer(Duration(milliseconds: ms), () {
          if (ms > 0 && callId != id) return; // the user reset or another call took over
          _inject(build());
        }),
      );
    }
    _log('Scripted scam call started ($lang)');
    _notify();
  }

  /// Drawer "End call": a simulated call ends the way the bridge would end it.
  void simulateCallEnded() {
    if (phase != CallPhase.active) return;
    if (simulated) {
      _inject({'type': 'call_ended', 'call_id': callId, 'ts': _ts});
    } else {
      unawaited(endCall());
    }
  }

  void resetToIdle() {
    _cancelSim();
    _stopSimHeartbeat();
    _resetCall();
    phase = CallPhase.idle;
    lastCall = null;
    _notify();
  }

  // ---- helpers --------------------------------------------------------------

  static String _scamName(String t) =>
      const {
        'digital_arrest': 'digital arrest scam',
        'kyc_update': 'KYC update scam',
        'bank_impersonation': 'bank impersonation scam',
        'prize_lottery': 'prize/lottery scam',
      }[t] ??
      'suspected scam';

  static String _two(int n) => n.toString().padLeft(2, '0');
  static String _date(DateTime d) =>
      '${_two(d.day)}-${_two(d.month)}-${d.year} at ${_two(d.hour)}:${_two(d.minute)}:${_two(d.second)}';

  @override
  void dispose() {
    _disposed = true;
    _clockTimer?.cancel();
    _autoHangup?.cancel();
    _cancelSim();
    _stopSimHeartbeat();
    _engine.dispose();
    unawaited(_transport?.dispose());
    _notices.close();
    super.dispose();
  }
}
