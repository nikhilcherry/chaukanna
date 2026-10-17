import 'package:chaukanna_app/services/phone_layer.dart';
import 'package:chaukanna_app/state/guardian_controller.dart';
import 'package:flutter_test/flutter_test.dart';

import 'fakes.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late FakePhoneLayer phone;
  late FakeCallTap tap;
  late Harness h;
  setUp(() async {
    phone = FakePhoneLayer();
    tap = FakeCallTap();
    h = Harness(phone: phone, tap: tap);
    await h.c.init();
  });
  tearDown(() => h.dispose());

  Future<void> pump() => Future<void>.delayed(Duration.zero);

  test('turns protection on at start when it was left on, and reports it', () {
    expect(h.c.phoneLayerAvailable, isTrue);
    expect(h.c.phoneProtectionOn, isTrue);
    expect(phone.starts, 1);
  });

  test('answering a phone call turns on the speaker and taps the call with the number', () async {
    phone.emit(PhoneCallState.ringing, '+91 98765 43210');
    phone.emit(PhoneCallState.offhook);
    await pump();
    expect(h.c.onPhoneCall, isTrue);
    expect(tap.started, ['+91 98765 43210']);
    expect(phone.speakerCalls, [true]);
  });

  test('the call ending ends the guardian call and stops the tap', () async {
    phone.emit(PhoneCallState.offhook, '+91 98765 43210');
    await pump();
    h.callStarted('room-1');
    expect(h.c.phase, CallPhase.active);
    phone.emit(PhoneCallState.idle);
    await pump();
    expect(h.c.onPhoneCall, isFalse);
    expect(h.c.phase, isNot(CallPhase.active));
    expect(tap.stops, 1);
    expect(phone.endCalls, 0, reason: 'the call was already over; nothing to hang up');
  });

  test('"Hang up" also ends the real phone call', () async {
    phone.emit(PhoneCallState.offhook, '+91 98765 43210');
    await pump();
    h.callStarted('room-1');
    await h.c.endCall();
    expect(phone.endCalls, 1);
  });

  test('a warning brings the app in front of the dialer and the tap mic pauses during the whisper', () async {
    phone.emit(PhoneCallState.offhook, '+91 98765 43210');
    await pump();
    h.callStarted('room-1');
    h.verdict('room-1', scam: 'digital_arrest', pressure: 2, clip: 'warn_digital_arrest', secrecy: true);
    await pump();
    expect(phone.frontCalls, greaterThan(0));
    expect(tap.mic, contains(false), reason: 'mic muted while the warning plays');
  });

  test('without the permissions the switch stays off and says why', () async {
    phone.perms = const PhonePermissions();
    await h.c.setPhoneProtection(true);
    await pump();
    expect(h.c.phoneProtectionOn, isFalse);
    expect(h.notices.any((n) => n.error), isTrue);
  });
}
