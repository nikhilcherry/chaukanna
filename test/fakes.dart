import 'dart:async';
import 'dart:convert';

import 'package:chaukanna_app/models/messages.dart';
import 'package:chaukanna_app/services/approval_client.dart';
import 'package:chaukanna_app/services/call_tap.dart';
import 'package:chaukanna_app/services/phone_layer.dart';
import 'package:chaukanna_app/services/clip_catalog.dart';
import 'package:chaukanna_app/services/whisper_player.dart';
import 'package:chaukanna_app/state/guardian_controller.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

/// Records what would have played. A play stays "in progress" until
/// [finish] or [stop], like real audio.
class FakeWhisperEngine implements WhisperEngine {
  final played = <String>[];
  final sequences = <List<ClipRef>>[];
  final preloads = <Map<String, List<ClipRef>>>[];
  WhisperRoute? route;
  Object? failWith;
  int stops = 0;
  Completer<WhisperOutcome>? _current;

  bool get playing => _current != null && !_current!.isCompleted;

  @override
  Future<WhisperOutcome> play(String clip, List<ClipRef> sequence, {void Function(ClipRef ref)? onClip}) {
    if (failWith != null) return Future.error(WhisperFailure('$failWith'));
    _current?.complete(WhisperOutcome.stopped);
    played.add(clip);
    sequences.add(sequence);
    _onClip = onClip;
    _index = 0;
    onClip?.call(sequence.first);
    final c = Completer<WhisperOutcome>();
    _current = c;
    return c.future;
  }

  void Function(ClipRef ref)? _onClip;
  int _index = 0;

  /// The short clip ended and the next one (the full clip) started.
  void nextClip() {
    final seq = sequences.last;
    if (playing && _index + 1 < seq.length) _onClip?.call(seq[++_index]);
  }

  /// The sequence played to the end.
  void finish() {
    final c = _current;
    _current = null;
    if (c != null && !c.isCompleted) c.complete(WhisperOutcome.completed);
  }

  @override
  Future<void> stop() async {
    stops++;
    final c = _current;
    _current = null;
    if (c != null && !c.isCompleted) c.complete(WhisperOutcome.stopped);
  }

  @override
  Future<List<String>> preload(Map<String, List<ClipRef>> sequences) async {
    preloads.add(sequences);
    return const [];
  }

  @override
  Future<void> setRoute(WhisperRoute r) async => route = r;

  @override
  void dispose() {}
}

class SentRequest {
  SentRequest(this.url, this.body);
  final Uri url;
  final Map<String, dynamic> body;
}

/// Builds a controller with no platform plugins, a controllable clock and a
/// recording HTTP client.
class Harness {
  Harness({
    DateTime? start,
    int Function(Uri url)? status,
    String Function(Uri url)? body,
    DateTime Function()? clock,
    PhoneLayer? phone,
    CallTap? tap,
  }) : now = start ?? DateTime(2026, 10, 17, 11, 0, 0) {
    final client = MockClient((req) async {
      sent.add(SentRequest(req.url, jsonDecode(req.body) as Map<String, dynamic>));
      return http.Response(body?.call(req.url) ?? '{"ok":true}', status?.call(req.url) ?? 200);
    });
    c = GuardianController(
      whisper: engine,
      approval: ApprovalClient(client: client, webhook: webhook),
      catalog: ClipCatalog(),
      clock: clock ?? () => now,
      haptics: () async {},
      useLiveKit: false,
      phoneLayer: phone,
      callTap: tap,
    );
    c.notices.listen(notices.add);
  }

  static const webhook = 'https://n8n.example.org/webhook/chaukanna-approve';

  DateTime now;
  final engine = FakeWhisperEngine();
  final sent = <SentRequest>[];
  final notices = <Notice>[];
  late final GuardianController c;

  void advance(Duration d) => now = now.add(d);

  void send(Map<String, dynamic> msg, {String? topic = kGuardianTopic}) =>
      c.handleData(utf8.encode(jsonEncode(msg)), topic: topic);

  void callStarted(String id, {String number = '+91 98765 43210', bool known = false}) =>
      send({'type': 'call_started', 'call_id': id, 'caller_number': number, 'known_scammer': known, 'ts': 1});

  void verdict(
    String id, {
    String text = 'hello',
    String speaker = 'caller',
    String scam = 'none',
    int pressure = 0,
    bool otp = false,
    bool secrecy = false,
    String clip = 'none',
    bool? whisper,
    String lang = 'hi',
  }) => send({
    'type': 'verdict',
    'call_id': id,
    'speaker': speaker,
    'chunk_text': text,
    'language': lang,
    'verdict': {
      'call_id': id,
      'scam_type': scam,
      'pressure': pressure,
      'asks_otp_or_pin': otp,
      'demands_secrecy': secrecy,
      'confidence': 0.9,
      'language': lang,
      'recommended_whisper_clip': clip,
      'summary_for_family': '',
    },
    'pressure': pressure,
    'whisper': whisper ?? clip != 'none',
    'whisper_clip': clip,
    'ts': 2,
  });

  void incident(String id, {String approveUrl = 'https://n8n.example.org/webhook-waiting/123', String lang = 'hi'}) =>
      send({
        'type': 'incident',
        'call_id': id,
        'ok': true,
        'incident_id': 'inc-42',
        'known_scammer': false,
        'family_alerted': true,
        'evidence_saved': true,
        'blocklisted': true,
        'complaint_draft': {'en': 'EN draft from n8n', 'local': 'हिंदी ड्राफ्ट', 'language': lang},
        'family_alert': '• one\n• two\n• three',
        'approve_url': approveUrl,
      });

  void ended(String id) => send({'type': 'call_ended', 'call_id': id, 'ts': 3});

  void heartbeat(String id) => send({'type': 'heartbeat', 'call_id': id, 'ts': 4});

  void dispose() => c.dispose();
}

/// Records what the app asked of the phone, and lets a test play out call states.
class FakePhoneLayer implements PhoneLayer {
  final _events = StreamController<PhoneEvent>.broadcast();
  PhonePermissions perms = const PhonePermissions(microphone: true, phone: true, enabled: true);
  final speakerCalls = <bool>[];
  int endCalls = 0;
  int frontCalls = 0;
  int starts = 0;

  void emit(PhoneCallState s, [String number = '']) => _events.add(PhoneEvent(s, number));

  @override
  Stream<PhoneEvent> get events => _events.stream;
  @override
  Future<PhonePermissions> status() async => perms;
  @override
  Future<PhonePermissions> requestPermissions() async => perms;
  @override
  Future<void> openOverlaySettings() async {}
  @override
  Future<bool> start() async {
    starts++;
    return true;
  }

  @override
  Future<void> stop() async {}
  @override
  Future<bool> endCall() async {
    endCalls++;
    return true;
  }

  @override
  Future<bool> setSpeaker(bool on) async {
    speakerCalls.add(on);
    return true;
  }

  @override
  Future<bool> bringToFront() async {
    frontCalls++;
    return true;
  }

  bool screening = false;
  List<ScreenedCall> screened = const [];
  @override
  Future<bool> screeningHeld() async => screening;
  @override
  Future<bool> requestScreening() async => screening = true;
  @override
  Future<List<ScreenedCall>> screenedCalls() async => screened;
}

class FakeCallTap extends CallTap {
  FakeCallTap() : super(log: (m, {important = false}) {});
  final started = <String>[];
  final mic = <bool>[];
  int stops = 0;

  @override
  Future<void> start(String number) async => started.add(number);
  @override
  Future<void> setMicEnabled(bool on) async => mic.add(on);
  @override
  Future<void> stop() async => stops++;
}
