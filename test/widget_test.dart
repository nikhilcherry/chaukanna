import 'package:chaukanna_app/main.dart';
import 'package:chaukanna_app/screens/post_call_screen.dart';
import 'package:chaukanna_app/services/clip_catalog.dart';
import 'package:chaukanna_app/state/guardian_controller.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import 'fakes.dart';

void main() {
  for (final lang in ['hi', 'kn']) {
    testWidgets('scripted scam call through the UI on a small phone at 1.3x text ($lang)', (tester) async {
      // 360 x 690 dp phone, large system font. Any overflow fails the test.
      tester.view.physicalSize = const Size(1080, 2070);
      tester.view.devicePixelRatio = 3.0;
      tester.platformDispatcher.textScaleFactorTestValue = 1.6; // clamped to 1.3 by the app
      addTearDown(tester.view.reset);
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);

      var now = DateTime(2026, 10, 17, 11);
      final h = Harness(clock: () => now);
      Future<void> wait(Duration d) async {
        // Step in 500 ms slices so timers see a roughly current clock.
        var left = d;
        while (left > Duration.zero) {
          final step = left > const Duration(milliseconds: 500) ? const Duration(milliseconds: 500) : left;
          now = now.add(step);
          await tester.pump(step);
          left -= step;
        }
      }

      await tester.pumpWidget(ChangeNotifierProvider.value(value: h.c, child: const ChaukannaApp()));
      expect(find.text('Chaukanna'), findsOneWidget);
      expect(find.text('Offline demo mode'), findsOneWidget);
      await expectLater(tester, meetsGuideline(androidTapTargetGuideline));

      h.c.setSimLanguage(lang);
      h.c.runFullScamCall();
      await wait(const Duration(seconds: 2));
      expect(find.text('Protected'), findsOneWidget);
      expect(find.text('SIMULATED CALL'), findsOneWidget);
      expect(find.text('Says: CBI Officer'), findsOneWidget);
      await expectLater(tester, meetsGuideline(androidTapTargetGuideline));

      await wait(const Duration(seconds: 11)); // t = 13 s: digital-arrest alarm
      final w = ClipCatalog().warningText('warn_digital_arrest', lang);
      expect(find.text(w.en), findsOneWidget);
      expect(find.text(w.local!), findsOneWidget);
      expect(find.text('Hang up now'), findsOneWidget);
      expect(find.text('Speaking the warning…'), findsOneWidget);
      expect(find.textContaining('🔊'), findsNothing, reason: 'short clip = the headline, no duplicate caption');
      h.engine.nextClip();
      await tester.pump();
      expect(find.textContaining('🔊'), findsOneWidget, reason: 'caption of the full clip being spoken');
      await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
      await tester.tap(find.text('I understand'));
      await tester.pump();
      expect(find.text('I understand'), findsNothing);
      expect(find.text('Told to keep this secret'), findsOneWidget);

      await wait(const Duration(seconds: 15)); // t = 28 s: OTP alarm
      expect(find.text(ClipCatalog().warningText('warn_otp', lang).en), findsOneWidget);
      await tester.tap(find.text('I understand'));
      await tester.pump();
      expect(find.textContaining('••••••'), findsOneWidget);
      expect(find.textContaining('482913'), findsNothing);

      await wait(const Duration(seconds: 13)); // t = 41 s: call_ended -> post-call
      final postCallList = find.descendant(of: find.byType(PostCallScreen), matching: find.byType(Scrollable)).first;
      expect(find.text('Call ended. You were protected.'), findsOneWidget);
      expect(find.text('Family alerted: Done'), findsOneWidget);
      for (final t in [
        'Call evidence and timestamps saved: Done',
        'Number added to shared blocklist: Done',
        'English',
        'Drafted by Chaukanna AI. Nothing is sent until you confirm.',
      ]) {
        await tester.scrollUntilVisible(find.text(t), 200, scrollable: postCallList);
        expect(find.text(t), findsOneWidget);
      }
      await expectLater(tester, meetsGuideline(androidTapTargetGuideline));

      final submit = find.text('Confirm & Submit 1930 Report');
      await tester.scrollUntilVisible(submit, 300, scrollable: postCallList);
      await tester.tap(submit);
      await tester.pump();
      expect(find.text('Send this report to 1930?'), findsOneWidget, reason: 'explicit confirmation');
      await tester.tap(find.text('Yes, send it'));
      await wait(const Duration(seconds: 2));
      expect(find.text('Report Submitted'), findsOneWidget);
      expect(find.text('Demo call: the report was not really sent.'), findsOneWidget);
      expect(h.sent, isEmpty);

      await tester.scrollUntilVisible(find.text('Done'), 300, scrollable: postCallList);
      await tester.tap(find.text('Done'));
      await tester.pump();
      expect(h.c.phase, CallPhase.idle);
      expect(find.text('Chaukanna'), findsOneWidget);

      await tester.pumpWidget(const SizedBox());
      h.dispose();
    });
  }

  testWidgets('known scammer auto-block and a failed voice warning stay readable', (tester) async {
    tester.view.physicalSize = const Size(1080, 2070);
    tester.view.devicePixelRatio = 3.0;
    addTearDown(tester.view.reset);
    var now = DateTime(2026, 10, 17, 11);
    final h = Harness(clock: () => now);
    h.engine.failWith = 'asset missing';
    await tester.pumpWidget(ChangeNotifierProvider.value(value: h.c, child: const ChaukannaApp()));
    h.c.simulateKnownScammer();
    await tester.pump(const Duration(milliseconds: 100));
    await tester.pump();
    expect(find.text('KNOWN SCAMMER'), findsOneWidget);
    expect(find.text('Voice warning could not play. Please read this screen.'), findsOneWidget);
    expect(find.textContaining('Voice warning could not play ('), findsOneWidget, reason: 'snackbar');
    for (var i = 0; i < 30; i++) {
      now = now.add(const Duration(milliseconds: 500));
      await tester.pump(const Duration(milliseconds: 500));
    }
    expect(find.text('Scam call blocked.'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    h.dispose();
  });
}
