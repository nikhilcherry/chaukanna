import 'package:chaukanna_app/services/approval_client.dart';
import 'package:chaukanna_app/services/clip_catalog.dart';
import 'package:chaukanna_app/services/whisper_gate.dart';
import 'package:chaukanna_app/util/otp_mask.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('maskOtp', () {
    test('masks 4-8 digit runs, spaced digits and Indic digits', () {
      expect(maskOtp('The OTP is 482913'), 'The OTP is ••••••');
      expect(maskOtp('it is 4 8 2 9 1 3 ok'), 'it is •••••• ok');
      expect(maskOtp('code 482 913'), 'code ••••••');
      expect(maskOtp('PIN 1234.'), 'PIN ••••.');
      expect(maskOtp('ओटीपी ४८२९१३ है'), 'ओटीपी •••••• है');
      expect(maskOtp('ಒಟಿಪಿ ೪೮೨೯ ಹೇಳಿ'), 'ಒಟಿಪಿ •••• ಹೇಳಿ');
    });

    test('keeps phone numbers, dates, times, 1930, amounts and short numbers', () {
      expect(maskOtp('call +91 98765 41207 now'), 'call +91 98765 41207 now');
      expect(maskOtp('9876543210'), '9876543210');
      expect(maskOtp('on 15-10-2026 at 10:30'), 'on 15-10-2026 at 10:30');
      expect(maskOtp('dial 1930 for help'), 'dial 1930 for help');
      expect(maskOtp('send Rs 50000 now'), 'send Rs 50000 now');
      expect(maskOtp('send ₹25000'), 'send ₹25000');
      expect(maskOtp('pay 50000 rupees'), 'pay 50000 rupees');
      expect(maskOtp('50000 रुपये भेजिए'), '50000 रुपये भेजिए');
      expect(maskOtp('room 42, floor 123'), 'room 42, floor 123');
      expect(maskOtp('vehicle KA01AB1234'), 'vehicle KA01AB1234');
    });
  });

  group('WhisperGate', () {
    test('same clip at most once per 20 s, other clips independent', () {
      final g = WhisperGate();
      final t0 = DateTime(2026, 10, 17, 11);
      expect(g.tryAcquire('warn_otp', t0), isTrue);
      expect(g.tryAcquire('warn_otp', t0.add(const Duration(seconds: 5))), isFalse);
      expect(g.tryAcquire('warn_secrecy', t0.add(const Duration(seconds: 5))), isTrue);
      expect(g.tryAcquire('warn_otp', t0.add(const Duration(seconds: 19, milliseconds: 999))), isFalse);
      expect(g.tryAcquire('warn_otp', t0.add(const Duration(seconds: 20))), isTrue);
      g.reset();
      expect(g.tryAcquire('warn_otp', t0.add(const Duration(seconds: 21))), isTrue);
    });
  });

  group('ClipCatalog (generated metadata)', () {
    test('short clip first, then full, same language', () {
      final seq = ClipCatalog().sequence('warn_otp', 'hi');
      expect(seq.map((r) => r.asset), ['assets/audio/warn_otp_short_hi.wav', 'assets/audio/warn_otp_hi.wav']);
      expect(seq.first.durationMs, lessThan(3000));
      expect(seq.every((r) => r.text.isNotEmpty), isTrue);
    });

    test('every warning has short + full audio in hi, kn and en', () {
      final cat = ClipCatalog();
      for (final clip in ClipCatalog.clipIds) {
        for (final lang in ClipCatalog.languages) {
          final seq = cat.sequence(clip, lang);
          expect(seq.map((r) => r.variant), ['short', 'full'], reason: '$clip/$lang');
          expect(seq.every((r) => r.lang == lang), isTrue, reason: '$clip/$lang');
        }
      }
    });

    test('unsupported language falls back to English for both clips', () {
      final seq = ClipCatalog().sequence('warn_secrecy', 'ta');
      expect(seq.map((r) => r.lang).toSet(), {'en'});
    });

    test('assets missing from the bundle are skipped, nothing bundled means empty', () {
      final onlyFull = ClipCatalog(bundledAssets: {'assets/audio/warn_otp_kn.wav'});
      expect(onlyFull.sequence('warn_otp', 'kn').map((r) => r.variant), ['full']);
      expect(onlyFull.sequence('warn_secrecy', 'kn'), isEmpty);
      expect(onlyFull.missingAudio('kn'), contains('warn_secrecy/kn'));
      expect(ClipCatalog().sequence('none', 'hi'), isEmpty);
    });

    test('on-screen warning text is the short clip text in English + call language', () {
      final w = ClipCatalog().warningText('warn_otp', 'kn');
      expect(w.en, contains('OTP'));
      expect(w.local, isNotNull);
      expect(w.local, isNot(w.en));
      expect(ClipCatalog().warningText('warn_otp', 'en').local, isNull);
      expect(ClipCatalog().warningText('none', 'hi').en, contains('scam'));
    });
  });

  group('ApprovalClient routes', () {
    const hook = 'https://n8n.premortem.tech/webhook/chaukanna-approve';
    test('approve_url first, then the webhook', () {
      final r = ApprovalClient(webhook: hook).routes('https://n8n.premortem.tech/webhook-waiting/9');
      expect(r.map((e) => e.$1), ['approve_url', 'webhook']);
    });
    test('no approve_url -> webhook only', () {
      expect(ApprovalClient(webhook: hook).routes(null).map((e) => e.$1), ['webhook']);
      expect(ApprovalClient(webhook: hook).routes('').map((e) => e.$1), ['webhook']);
    });
    test('a localhost resume URL is unreachable from a phone and skipped', () {
      expect(ApprovalClient(webhook: hook).routes('http://localhost:5678/webhook-waiting/9').map((e) => e.$1),
          ['webhook']);
      expect(ApprovalClient.isReachableUrl('http://127.0.0.1:5678/x'), isFalse);
      expect(ApprovalClient.isReachableUrl('ftp://n8n.premortem.tech/x'), isFalse);
    });
    test('nothing configured -> no routes', () {
      expect(ApprovalClient(webhook: '').routes(null), isEmpty);
    });
  });
}
