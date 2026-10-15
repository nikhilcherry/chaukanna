import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import 'screens/alarm_overlay.dart';
import 'screens/call_screen.dart';
import 'screens/post_call_screen.dart';
import 'screens/simulator_drawer.dart';
import 'state/guardian_controller.dart';
import 'theme.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setPreferredOrientations([DeviceOrientation.portraitUp]);
  runApp(ChangeNotifierProvider(
    create: (_) => GuardianController()..connectLive(),
    child: const ChaukannaApp(),
  ));
}

class ChaukannaApp extends StatelessWidget {
  const ChaukannaApp({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'Chaukanna',
        debugShowCheckedModeBanner: false,
        theme: buildTheme(),
        home: const Shell(),
      );
}

class Shell extends StatelessWidget {
  const Shell({super.key});

  @override
  Widget build(BuildContext context) {
    final c = context.watch<GuardianController>();
    return Scaffold(
      endDrawer: const SimulatorDrawer(),
      endDrawerEnableOpenDragGesture: true,
      drawerEdgeDragWidth: 28,
      body: Builder(
        builder: (ctx) => Stack(children: [
          Positioned.fill(
            child: c.phase == CallPhase.ended ? const PostCallScreen() : const CallScreen(),
          ),
          // Tiny, near-invisible dev handle; swiping from the right edge also works.
          Positioned(
            right: 0,
            top: 120,
            child: GestureDetector(
              onTap: () => Scaffold.of(ctx).openEndDrawer(),
              child: Container(
                width: 14,
                height: 56,
                decoration: BoxDecoration(
                    color: Colors.white.withValues(alpha: 0.12),
                    borderRadius: const BorderRadius.horizontal(left: Radius.circular(8))),
              ),
            ),
          ),
          if (c.alarmActive && c.alarmVerdict != null)
            Positioned.fill(
              child: AlarmOverlay(
                key: ValueKey('${c.alarmVerdict.hashCode}'),
                verdict: c.alarmVerdict!,
                whisperPlaying: c.whisperPlaying != null,
                onDismiss: c.dismissAlarm,
              ),
            ),
        ]),
      ),
    );
  }
}
