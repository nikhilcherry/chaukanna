// Renders the app's screens to docs/screenshots/*.png through the same scripted scam call the
// widget tests use (offline simulator, fake whisper engine), with the real fonts loaded.
//
//   flutter test --update-goldens tool/screenshots_test.dart
//
// Lives outside test/ on purpose: these are pictures for the README, not assertions, and
// font rendering differs between machines.
import 'dart:io';

import 'package:chaukanna_app/main.dart';
import 'package:chaukanna_app/screens/post_call_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import '../test/fakes.dart';

Future<void> _load(String family, List<String> paths) async {
  final loader = FontLoader(family);
  for (final p in paths.where((p) => File(p).existsSync())) {
    final bytes = File(p).readAsBytesSync();
    loader.addFont(Future.value(ByteData.view(bytes.buffer)));
  }
  await loader.load();
}

Future<void> _loadFonts() async {
  final root = Platform.environment['FLUTTER_ROOT'] ?? '${Platform.environment['HOME']}/flutter';
  final mf = '$root/bin/cache/artifacts/material_fonts';
  await _load('Roboto', [
    for (final w in ['Regular', 'Medium', 'Bold', 'Black', 'Light']) '$mf/Roboto-$w.ttf',
  ]);
  await _load('MaterialIcons', ['$mf/MaterialIcons-Regular.otf']);
  await _load('Manrope', ['assets/fonts/Manrope-Variable.ttf']);
  await _load('NotoSansDevanagari', [
    'assets/fonts/NotoSansDevanagari-Regular.ttf',
    'assets/fonts/NotoSansDevanagari-Bold.ttf',
  ]);
  await _load('NotoSansKannada', ['assets/fonts/NotoSansKannada-Regular.ttf', 'assets/fonts/NotoSansKannada-Bold.ttf']);
  await _load('NotoColorEmoji', ['/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf']);
}

void main() {
  setUpAll(_loadFonts);

  for (final lang in ['hi', 'kn']) {
    testWidgets('screenshots ($lang)', (tester) async {
      tester.view.physicalSize = const Size(1080, 2340); // 360 x 780 dp
      tester.view.devicePixelRatio = 3.0;
      addTearDown(tester.view.reset);

      var now = DateTime(2026, 10, 17, 11);
      final h = Harness(clock: () => now);
      Future<void> wait(Duration d) async {
        var left = d;
        while (left > Duration.zero) {
          final step = left > const Duration(milliseconds: 500) ? const Duration(milliseconds: 500) : left;
          now = now.add(step);
          await tester.pump(step);
          left -= step;
        }
      }

      Future<void> shot(String name) async {
        await tester.pump();
        await expectLater(find.byType(ChaukannaApp), matchesGoldenFile('../docs/screenshots/app-$name.png'));
      }

      await tester.pumpWidget(ChangeNotifierProvider.value(value: h.c, child: const ChaukannaApp()));
      await tester.pump();
      if (lang == 'hi') {
        await shot('1-idle');
        final state = tester.state<ScaffoldState>(find.byType(Scaffold).first);
        state.openEndDrawer();
        await tester.pump(const Duration(milliseconds: 500));
        await shot('2-demo-simulator');
        state.closeEndDrawer();
        await tester.pump(const Duration(milliseconds: 500));
      }

      h.c.setSimLanguage(lang);
      h.c.runFullScamCall();
      await wait(const Duration(seconds: 9));
      if (lang == 'hi') await shot('3-call-rising-pressure');

      await wait(const Duration(seconds: 4)); // t = 13 s: digital-arrest alarm
      h.engine.nextClip();
      await tester.pump();
      await shot('4-alarm-digital-arrest-$lang');
      await tester.tap(find.text('I understand'));
      await tester.pump();

      await wait(const Duration(seconds: 15)); // t = 28 s: OTP alarm
      if (lang == 'hi') await shot('5-alarm-otp');
      await tester.tap(find.text('I understand'));
      await tester.pump();
      if (lang == 'hi') {
        await wait(const Duration(seconds: 2));
        await shot('6-call-after-otp-ask');
      }

      await wait(Duration(seconds: lang == 'hi' ? 11 : 13)); // t = 41 s: call ended
      if (lang == 'hi') {
        await shot('7-post-call');
        final list = find.descendant(of: find.byType(PostCallScreen), matching: find.byType(Scrollable)).first;
        await tester.scrollUntilVisible(
          find.text('Drafted by Chaukanna AI. Nothing is sent until you confirm.'),
          300,
          scrollable: list,
        );
        await tester.pump();
        await shot('8-post-call-complaint');
      }

      await tester.pumpWidget(const SizedBox());
      h.dispose();
    });
  }
}
