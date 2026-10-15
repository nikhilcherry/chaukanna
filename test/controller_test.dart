import 'package:chaukanna_app/config.dart';
import 'package:chaukanna_app/state/guardian_controller.dart';
import 'package:fake_async/fake_async.dart';
import 'package:flutter_test/flutter_test.dart';

import 'fakes.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Harness h;
  setUp(() => h = Harness());
  tearDown(() => h.dispose());

  group('call lifecycle', () {
    test('call_started -> verdicts -> incident -> call_ended lands on the post-call screen', () async {
      h.callStarted('room-1', number: '+91 98765 43210 - CBI Officer');
      expect(h.c.phase, CallPhase.active);
      expect(h.c.callId, 'room-1');
      expect(h.c.callerNumber, '+91 98765 43210');
      expect(h.c.callerLabel, 'CBI Officer');

      h.verdict('room-1', text: 'Hello sir', pressure: 0);
      expect(h.c.alarmActive, isFalse);
      h.verdict('room-1', text: 'You are under digital arrest, tell no one', scam: 'digital_arrest', pressure: 2, secrecy: true, clip: 'warn_digital_arrest');
      expect(h.c.alarmActive, isTrue);
      expect(h.c.alarm!.clip, 'warn_digital_arrest');
      expect(h.engine.played, ['warn_digital_arrest']);

      h.incident('room-1');
      expect(h.c.incident!.incidentId, 'inc-42');
      expect(h.c.complaintEnglish, 'EN draft from n8n');
      expect(h.c.complaintLocal, 'हिंदी ड्राफ्ट');
      expect(h.c.familySummary, startsWith('• one'));

      h.ended('room-1');
      await pumpEventQueue();
      expect(h.c.phase, CallPhase.ended);
      expect(h.c.alarmActive, isFalse);
      expect(h.c.endReason, contains('caller hung up'));
    });

    test('a low-risk call_ended resets straight to idle with a note', () async {
      h.callStarted('room-1');
      h.verdict('room-1', text: 'electricity bill', pressure: 1, scam: 'other');
      h.ended('room-1');
      await pumpEventQueue();
      expect(h.c.phase, CallPhase.idle);
      expect(h.c.lastCall, isNotNull);
      expect(h.c.transcript, isEmpty);
      expect(h.c.peakPressure, 0);
    });

    test('everything resets between calls, so call 2 does not start at full alarm', () async {
      h.callStarted('room-1');
      h.verdict('room-1', text: 'OTP 482913 now', scam: 'bank_impersonation', pressure: 3, otp: true, clip: 'warn_otp');
      h.incident('room-1');
      h.ended('room-1');
      await pumpEventQueue();
      expect(h.c.phase, CallPhase.ended);

      h.advance(const Duration(seconds: 5));
      h.callStarted('room-2', number: '+91 80 1111 2222');
      expect(h.c.phase, CallPhase.active);
      expect(h.c.callId, 'room-2');
      expect(h.c.peakPressure, 0);
      expect(h.c.sawOtpAsk, isFalse);
      expect(h.c.scamType, 'none');
      expect(h.c.transcript, isEmpty);
      expect(h.c.evidence, isEmpty);
      expect(h.c.incident, isNull);
      expect(h.c.alarmActive, isFalse);
      expect(h.c.alarm, isNull);
      expect(h.c.whisper.status, WhisperStatus.idle);
      expect(h.c.submitState, SubmitState.idle);
      expect(h.c.firstHighRiskAt, isNull);

      // Dedupe is per call: the same warning may play again 5 s later in a new call.
      h.verdict('room-2', pressure: 2, otp: true, clip: 'warn_otp');
      expect(h.engine.played, ['warn_otp', 'warn_otp']);
      expect(h.c.alarmActive, isTrue);
    });

    test('late verdicts for an ended call are ignored', () async {
      h.callStarted('room-1');
      h.verdict('room-1', pressure: 3, scam: 'digital_arrest', clip: 'warn_digital_arrest');
      h.ended('room-1');
      await pumpEventQueue();
      final lines = h.c.transcript.length;
      h.verdict('room-1', text: 'straggler', pressure: 3);
      expect(h.c.phase, CallPhase.ended);
      expect(h.c.transcript.length, lines);
    });

    test('a verdict with a new call_id starts a fresh call even if call_started was lost', () {
      h.callStarted('room-1');
      h.verdict('room-1', pressure: 2, scam: 'other');
      h.verdict('room-9', text: 'new caller', pressure: 0);
      expect(h.c.callId, 'room-9');
      expect(h.c.peakPressure, 0);
      expect(h.c.transcript.single.text, 'new caller');
    });

    test('a verdict while idle starts a call (bridge without call_started)', () {
      h.verdict('room-3', text: 'hi', pressure: 1);
      expect(h.c.phase, CallPhase.active);
      expect(h.c.callId, 'room-3');
    });

    test('unknown message types and other topics change nothing', () {
      h.send({'type': 'telemetry', 'call_id': 'x'});
      h.send({'type': 'verdict', 'call_id': 'x', 'pressure': 3}, topic: 'lk.chat');
      expect(h.c.phase, CallPhase.idle);
      expect(h.c.log.entries.where((e) => e.message.startsWith('Ignored')).length, 2);
    });
  });

  group('heartbeat badge', () {
    test('Protected within 15 s of a heartbeat, then greys out', () {
      expect(h.c.guardianStatus, GuardianStatus.offline);
      h.heartbeat('room-1');
      expect(h.c.guardianStatus, GuardianStatus.protected);
      h.advance(const Duration(seconds: 14));
      expect(h.c.guardianStatus, GuardianStatus.protected);
      h.advance(const Duration(seconds: 2));
      expect(h.c.guardianStatus, GuardianStatus.stale);
      h.heartbeat('room-1');
      expect(h.c.guardianStatus, GuardianStatus.protected);
      expect(h.c.phase, CallPhase.idle, reason: 'a heartbeat alone does not start a call');
    });
  });

  group('whisper', () {
    test('same clip at most once per 20 s; a different clip still plays', () {
      h.callStarted('room-1');
      h.verdict('room-1', pressure: 2, otp: true, clip: 'warn_otp');
      h.advance(const Duration(seconds: 5));
      h.verdict('room-1', pressure: 2, otp: true, clip: 'warn_otp');
      expect(h.engine.played, ['warn_otp']);
      h.verdict('room-1', pressure: 3, otp: true, secrecy: true, clip: 'warn_secrecy');
      expect(h.engine.played, ['warn_otp', 'warn_secrecy']);
      h.advance(const Duration(seconds: 16));
      h.verdict('room-1', pressure: 3, otp: true, clip: 'warn_otp');
      expect(h.engine.played, ['warn_otp', 'warn_secrecy', 'warn_otp']);
    });

    test('plays the short clip then the full clip in the call language', () {
      h.callStarted('room-1');
      h.verdict('room-1', pressure: 2, otp: true, clip: 'warn_otp', lang: 'kn');
      expect(h.engine.sequences.single.map((r) => r.asset),
          ['assets/audio/warn_otp_short_kn.wav', 'assets/audio/warn_otp_kn.wav']);
      expect(h.c.callLanguage, 'kn');
      expect(h.engine.preloads.last.keys, containsAll(['warn_otp', 'warn_digital_arrest']));
    });

    test('whisper=false from the bridge means no audio, but the alarm still shows', () {
      h.callStarted('room-1');
      h.verdict('room-1', pressure: 2, scam: 'digital_arrest', clip: 'warn_digital_arrest', whisper: false);
      expect(h.engine.played, isEmpty);
      expect(h.c.alarmActive, isTrue);
      expect(h.c.alarm!.clip, 'warn_digital_arrest');
    });

    test('mic is paused while the whisper plays and restored after', () async {
      h.callStarted('room-1');
      h.verdict('room-1', pressure: 2, otp: true, clip: 'warn_otp');
      expect(h.c.whisper.playing, isTrue);
      expect(h.c.micPausedForWhisper, AppConfig.muteMicDuringWhisper);
      h.engine.finish();
      await pumpEventQueue();
      expect(h.c.whisper.status, WhisperStatus.done);
      expect(h.c.micPausedForWhisper, isFalse);
    });

    test('"I understand" stops the voice', () async {
      h.callStarted('room-1');
      h.verdict('room-1', pressure: 2, otp: true, clip: 'warn_otp');
      h.c.dismissAlarm();
      await pumpEventQueue();
      expect(h.c.alarmActive, isFalse);
      expect(h.engine.stops, greaterThan(0));
      expect(h.c.micPausedForWhisper, isFalse);
    });

    test('a playback failure is visible, not swallowed', () async {
      h.engine.failWith = 'asset not found';
      h.callStarted('room-1');
      h.verdict('room-1', pressure: 2, otp: true, clip: 'warn_otp');
      await pumpEventQueue();
      expect(h.c.whisper.status, WhisperStatus.failed);
      expect(h.c.whisper.error, contains('asset not found'));
      expect(h.notices.single.error, isTrue);
      expect(h.c.log.entries.any((e) => e.important && e.message.contains('Whisper FAILED')), isTrue);
      expect(h.c.alarmActive, isTrue, reason: 'the on-screen warning still shows');
    });

    test('a known scammer at call start warns at once', () {
      h.callStarted('room-1', known: true);
      expect(h.c.knownScammer, isTrue);
      expect(h.c.peakPressure, 3);
      expect(h.engine.played, ['warn_known_scammer']);
      expect(h.c.alarm!.knownScammer, isTrue);
    });
  });

  test('OTP digits are masked in the transcript and the evidence', () {
    h.callStarted('room-1');
    h.verdict('room-1', text: 'Is the OTP 482913?', pressure: 3, otp: true, clip: 'warn_otp');
    expect(h.c.transcript.single.text, 'Is the OTP ••••••?');
    expect(h.c.evidence.single.text, contains('••••••'));
    expect(h.c.approvalPayload().toString(), isNot(contains('482913')));
  });

  group('1930 approval', () {
    Future<void> highRiskCall({String approveUrl = 'https://n8n.example.org/webhook-waiting/123'}) async {
      h.callStarted('room-1');
      h.verdict('room-1', pressure: 3, scam: 'digital_arrest', secrecy: true, clip: 'warn_digital_arrest');
      h.incident('room-1', approveUrl: approveUrl);
      h.ended('room-1');
      await pumpEventQueue();
    }

    test('posts the CONTRACTS §3 body to approve_url', () async {
      await highRiskCall();
      await h.c.submit1930();
      expect(h.c.submitState, SubmitState.done);
      expect(h.c.submitRoute, 'approve_url');
      final r = h.sent.single;
      expect(r.url.toString(), 'https://n8n.example.org/webhook-waiting/123');
      expect(r.body['action'], 'confirm_1930_report');
      expect(r.body['confirmed_by_human'], isTrue);
      expect(r.body['call_id'], 'room-1');
      expect(r.body['victim_id'], AppConfig.victimId);
      expect(r.body['incident_id'], 'inc-42');
      expect(r.body['peak_pressure'], 3);
      expect(r.body['complaint_text'], 'EN draft from n8n');
      expect(r.body['complaint_text_local'], 'हिंदी ड्राफ्ट');
      expect(r.body['complaint_language'], 'hi');
      for (final k in ['caller_number', 'scam_type', 'asks_otp_or_pin', 'demands_secrecy', 'duration_seconds', 'evidence', 'submitted_at']) {
        expect(r.body.containsKey(k), isTrue, reason: k);
      }
    });

    test('falls back to the webhook when approve_url fails', () async {
      h.dispose();
      h = Harness(status: (u) => u.path.contains('webhook-waiting') ? 404 : 200);
      await highRiskCall();
      await h.c.submit1930();
      expect(h.sent.map((r) => r.url.toString()), ['https://n8n.example.org/webhook-waiting/123', Harness.webhook]);
      expect(h.c.submitState, SubmitState.done);
      expect(h.c.submitRoute, 'webhook');
    });

    test('no incident (n8n silent) -> webhook with call_id and the local draft', () async {
      h.callStarted('room-7');
      h.verdict('room-7', pressure: 2, otp: true, scam: 'kyc_update', clip: 'warn_otp');
      h.ended('room-7');
      await pumpEventQueue();
      await h.c.submit1930();
      final r = h.sent.single;
      expect(r.url.toString(), Harness.webhook);
      expect(r.body['call_id'], 'room-7');
      expect(r.body.containsKey('incident_id'), isFalse);
      expect(r.body['complaint_text'], contains('cybercrime.gov.in'));
    });

    test('a localhost approve_url goes straight to the webhook', () async {
      await highRiskCall(approveUrl: 'http://localhost:5678/webhook-waiting/5');
      await h.c.submit1930();
      expect(h.sent.single.url.toString(), Harness.webhook);
    });

    test('both endpoints failing shows a retry, then a retry can succeed', () async {
      h.dispose();
      var fail = true;
      h = Harness(status: (_) => fail ? 500 : 200);
      await highRiskCall();
      await h.c.submit1930();
      expect(h.c.submitState, SubmitState.failed);
      await pumpEventQueue();
      expect(h.notices.last.error, isTrue);
      fail = false;
      await h.c.submit1930();
      expect(h.c.submitState, SubmitState.done);
    });
  });

  test('scripted scam call runs end to end offline and sends nothing on approval', () {
    fakeAsync((async) {
      final start = DateTime(2026, 10, 17, 11);
      final x = Harness(clock: () => start.add(async.elapsed));
      void tick(Duration d) => async.elapse(d);

      x.c.setSimLanguage('kn');
      x.c.runFullScamCall();
      tick(const Duration(milliseconds: 100));
      expect(x.c.phase, CallPhase.active);
      expect(x.c.simulated, isTrue);
      expect(x.c.guardianStatus, GuardianStatus.protected);

      tick(const Duration(seconds: 13));
      expect(x.c.alarmActive, isTrue);
      expect(x.engine.played, ['warn_digital_arrest']);
      x.c.dismissAlarm();

      tick(const Duration(seconds: 15)); // t = 28 s
      expect(x.engine.played, ['warn_digital_arrest', 'warn_otp']);
      expect(x.c.transcript.any((l) => l.text.contains('••••••')), isTrue);
      expect(x.c.transcript.any((l) => l.text.contains('482913')), isFalse);

      tick(const Duration(seconds: 13)); // t = 41 s
      expect(x.c.phase, CallPhase.ended);
      expect(x.c.incident, isNotNull);
      expect(x.c.complaintLocalLang, 'kn');
      expect(x.c.complaintLocal, contains('1930'));
      expect(x.c.transcript.length, 7);

      x.c.submit1930();
      tick(const Duration(seconds: 2));
      expect(x.c.submitState, SubmitState.done);
      expect(x.c.submitRoute, 'demo');
      expect(x.sent, isEmpty);

      // A second scripted call starts clean.
      x.c.finishPostCall();
      x.c.runFullScamCall();
      tick(const Duration(seconds: 5));
      expect(x.c.peakPressure, 0);
      expect(x.c.alarmActive, isFalse);
      x.c.resetToIdle();
      x.dispose();
      async.flushTimers(flushPeriodicTimers: false);
    });
  });

  test('simulator buttons: P0 -> P2 stack into one call; known scammer auto-blocks', () {
    fakeAsync((async) {
      final start = DateTime(2026, 10, 17, 11);
      final x = Harness(clock: () => start.add(async.elapsed));
      void tick(Duration d) => async.elapse(d);

      x.c.simulatePressure0();
      tick(const Duration(milliseconds: 10));
      final id = x.c.callId;
      x.c.simulatePressure2Otp();
      tick(const Duration(milliseconds: 10));
      expect(x.c.callId, id);
      expect(x.c.transcript.length, 2);
      expect(x.c.alarmActive, isTrue);
      tick(const Duration(seconds: 4));
      expect(x.c.incident, isNotNull, reason: 'simulated n8n reply');
      x.c.simulateCallEnded();
      tick(const Duration(milliseconds: 10));
      expect(x.c.phase, CallPhase.ended);
      x.c.resetToIdle();

      x.c.simulateKnownScammer();
      tick(const Duration(milliseconds: 10));
      expect(x.c.knownScammer, isTrue);
      expect(x.engine.played.last, 'warn_known_scammer');
      tick(const Duration(seconds: 15));
      expect(x.c.phase, CallPhase.ended, reason: 'auto-blocked');
      expect(x.c.endReason, contains('known scammer'));
      x.c.resetToIdle();
      x.dispose();
      async.flushTimers(flushPeriodicTimers: false);
    });
  });
}
