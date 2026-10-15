import 'dart:convert';

import 'package:chaukanna_app/models/messages.dart';
import 'package:chaukanna_app/models/verdict.dart';
import 'package:flutter_test/flutter_test.dart';

GuardianMessage? parse(Object json) => parseGuardianMessage(utf8.encode(jsonEncode(json)));

void main() {
  group('parseGuardianMessage', () {
    test('call_started', () {
      final m = parse({'type': 'call_started', 'call_id': 'room-ab12cd34', 'caller_number': '+92 300 1234567', 'known_scammer': true, 'ts': 1760000000.5});
      expect(m, isA<CallStartedMessage>());
      final s = m as CallStartedMessage;
      expect(s.callId, 'room-ab12cd34');
      expect(s.callerNumber, '+92 300 1234567');
      expect(s.knownScammer, isTrue);
      expect(s.ts, 1760000000.5);
    });

    test('verdict (current bridge format with nested Verdict)', () {
      final m = parse({
        'type': 'verdict',
        'call_id': 'room-1',
        'speaker': 'caller',
        'chunk_text': 'tell me the OTP',
        'language': 'hi-IN',
        'verdict': {
          'call_id': 'room-1',
          'scam_type': 'bank_impersonation',
          'pressure': 2,
          'asks_otp_or_pin': true,
          'demands_secrecy': false,
          'confidence': 0.8,
          'language': 'hi',
          'recommended_whisper_clip': 'warn_otp',
          'summary_for_family': 'x',
          'known_scammer': false,
          'whisper_reason': 'first OTP ask',
        },
        'pressure': 2,
        'whisper': true,
        'whisper_clip': 'warn_otp',
        'ts': 1,
        'latency_ms': 1840,
      }) as VerdictMessage;
      expect(m.callId, 'room-1');
      expect(m.language, 'hi');
      expect(m.pressure, 2);
      expect(m.clipToPlay, 'warn_otp');
      expect(m.latencyMs, 1840);
      expect(m.verdict.asksOtpOrPin, isTrue);
      expect(m.verdict.whisperReason, 'first OTP ask');
      expect(m.legacy, isFalse);
    });

    test('verdict with whisper=false does not play even if the classifier recommends a clip', () {
      final m = parse({
        'type': 'verdict',
        'call_id': 'c',
        'verdict': {'scam_type': 'digital_arrest', 'pressure': 3, 'recommended_whisper_clip': 'warn_digital_arrest'},
        'whisper': false,
      }) as VerdictMessage;
      expect(m.clipToPlay, 'none');
      expect(m.pressure, 3);
    });

    test('verdict from the older bridge (no whisper_clip field) uses the verdict clip', () {
      final m = parse({
        'type': 'verdict',
        'call_id': 'chaukanna',
        'chunk_text': 'x',
        'verdict': {'scam_type': 'other', 'pressure': 2, 'recommended_whisper_clip': 'warn_secrecy'},
        'whisper': true,
      }) as VerdictMessage;
      expect(m.clipToPlay, 'warn_secrecy');
    });

    test('bare Verdict with no type is accepted (old format / simulator)', () {
      final m = parse({
        'transcript': 'You are under digital arrest',
        'scam_type': 'digital_arrest',
        'pressure': 9,
        'asks_otp_or_pin': false,
        'demands_secrecy': true,
        'language': 'kn',
        'recommended_whisper_clip': 'warn_digital_arrest',
      }) as VerdictMessage;
      expect(m.legacy, isTrue);
      expect(m.pressure, 3, reason: 'clamped');
      expect(m.chunkText, 'You are under digital arrest');
      expect(m.clipToPlay, 'warn_digital_arrest');
      expect(m.language, 'kn');
    });

    test('incident carries the n8n reply, nested or flat', () {
      final flat = parse({
        'type': 'incident',
        'call_id': 'room-1',
        'ok': true,
        'incident_id': 'u-1',
        'known_scammer': false,
        'family_alerted': true,
        'evidence_saved': true,
        'blocklisted': false,
        'complaint_draft': {'en': 'EN', 'local': 'ಕನ್ನಡ', 'language': 'kn'},
        'family_alert': '• a\n• b',
        'approve_url': 'https://n8n.premortem.tech/webhook-waiting/77',
      }) as IncidentMessage;
      final i = flat.incident;
      expect(flat.callId, 'room-1');
      expect(i.incidentId, 'u-1');
      expect(i.familyAlerted, isTrue);
      expect(i.blocklisted, isFalse);
      expect(i.complaintEn, 'EN');
      expect(i.complaintLocal, 'ಕನ್ನಡ');
      expect(i.hasLocalDraft, isTrue);
      expect(i.approveUrl, endsWith('/77'));

      final nested = parse({
        'type': 'incident',
        'incident': {'call_id': 'room-2', 'complaint_draft': 'plain text draft', 'family_alert': ['• x', '• y']},
      }) as IncidentMessage;
      expect(nested.callId, 'room-2');
      expect(nested.incident.complaintEn, 'plain text draft');
      expect(nested.incident.familyAlert, '• x\n• y');
      expect(nested.incident.familyAlerted, isNull, reason: 'missing = unknown, not false');
    });

    test('heartbeat and call_ended', () {
      expect(parse({'type': 'heartbeat', 'call_id': 'c', 'ts': 5}), isA<HeartbeatMessage>());
      final e = parse({'type': 'call_ended', 'call_id': 'c', 'ts': 6});
      expect(e, isA<CallEndedMessage>());
      expect(e!.callId, 'c');
    });

    test('unknown types, non-objects and garbage are ignored', () {
      expect(parse({'type': 'telemetry', 'call_id': 'c'}), isNull);
      expect(parse({'type': 42}), isNull);
      expect(parse({'hello': 'world'}), isNull);
      expect(parse([1, 2, 3]), isNull);
      expect(parse('just a string'), isNull);
      expect(parseGuardianMessage([0xff, 0xfe, 0x00]), isNull);
      expect(parseGuardianMessage(utf8.encode('{"type": "verdict"')), isNull);
    });

    test('wrongly typed fields fall back instead of throwing', () {
      final m = parse({
        'type': 'verdict',
        'verdict': {'pressure': '2', 'asks_otp_or_pin': 'true', 'scam_type': null, 'confidence': 'high'},
        'speaker': null,
      }) as VerdictMessage;
      expect(m.pressure, 2);
      expect(m.verdict.asksOtpOrPin, isTrue);
      expect(m.verdict.scamType, 'none');
      expect(m.speaker, 'caller');
    });
  });

  test('topic filter accepts the guardian topic and untagged packets only', () {
    expect(acceptsTopic('chaukanna.verdict'), isTrue);
    expect(acceptsTopic(null), isTrue);
    expect(acceptsTopic(''), isTrue);
    expect(acceptsTopic('lk.chat'), isFalse);
  });

  test('normLang', () {
    expect(normLang('hi-IN'), 'hi');
    expect(normLang('KN'), 'kn');
    expect(normLang(''), 'en');
  });
}
