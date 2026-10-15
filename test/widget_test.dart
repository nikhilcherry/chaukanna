import 'package:chaukanna_app/models/verdict.dart';
import 'package:chaukanna_app/services/whisper_player.dart';
import 'package:chaukanna_app/state/guardian_controller.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('Verdict parses the contract', () {
    final v = Verdict.fromJson({
      'transcript': 'tell me the OTP',
      'scam_type': 'bank_impersonation',
      'pressure': 2,
      'asks_otp_or_pin': true,
      'demands_secrecy': false,
      'language': 'hi',
      'recommended_whisper_clip': 'warn_otp',
    });
    expect(v.pressure, 2);
    expect(v.isScam, isTrue);
    expect(WhisperPlayer.assetFor(v.recommendedWhisperClip, v.language), 'assets/audio/warn_otp_hi.wav');
  });

  test('pressure is clamped and bad bytes are ignored', () {
    expect(Verdict.fromJson({'pressure': 9}).pressure, 3);
    expect(Verdict.tryParse([1, 2, 3]), isNull);
  });

  test('simulated pressure 3 call ends as high-risk with a draft', () async {
    final c = GuardianController();
    c.simulatePressure3DigitalArrest();
    expect(c.alarmActive, isTrue);
    expect(c.highRiskCall, isTrue);
    await c.endCall();
    expect(c.phase, CallPhase.ended);
    expect(c.complaintDraft, contains('digital arrest'));
    c.dispose();
  });
}
