import 'dart:async';

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
  runApp(ChangeNotifierProvider(create: (_) => GuardianController()..init(), child: const ChaukannaApp()));
}

class ChaukannaApp extends StatelessWidget {
  const ChaukannaApp({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'Chaukanna',
    debugShowCheckedModeBanner: false,
    theme: buildTheme(),
    // Elders often run large system font sizes; our type is already big, so
    // cap the multiplier to keep every screen free of overflow.
    builder: (context, child) =>
        MediaQuery.withClampedTextScaling(minScaleFactor: 1.0, maxScaleFactor: 1.3, child: child!),
    home: const Shell(),
  );
}

class Shell extends StatefulWidget {
  const Shell({super.key});

  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  StreamSubscription<Notice>? _sub;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _sub ??= context.read<GuardianController>().notices.listen((n) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
        ..hideCurrentSnackBar()
        ..showSnackBar(
          SnackBar(
            content: Text(n.text),
            backgroundColor: n.error ? const Color(0xFF7A4B00) : Pal.ink,
            duration: const Duration(seconds: 5),
          ),
        );
    });
  }

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = context.watch<GuardianController>();
    final alarm = c.alarm;
    return Scaffold(
      endDrawer: const SimulatorDrawer(),
      endDrawerEnableOpenDragGesture: true,
      drawerEdgeDragWidth: 32,
      body: Builder(
        builder: (ctx) => Stack(
          children: [
            Positioned.fill(child: c.phase == CallPhase.ended ? const PostCallScreen() : const CallScreen()),
            // Near-invisible dev handle (32 x 72 hit area); swiping from the right edge also works.
            Positioned(
              right: 0,
              top: 120,
              child: Semantics(
                button: true,
                label: 'Open demo simulator',
                child: GestureDetector(
                  behavior: HitTestBehavior.opaque,
                  onTap: () => Scaffold.of(ctx).openEndDrawer(),
                  child: SizedBox(
                    width: 32,
                    height: 72,
                    child: Align(
                      alignment: Alignment.centerRight,
                      child: Container(
                        width: 10,
                        height: 56,
                        decoration: BoxDecoration(
                          color: Colors.black.withValues(alpha: 0.28),
                          borderRadius: const BorderRadius.horizontal(left: Radius.circular(8)),
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            ),
            if (c.alarmActive && alarm != null && c.phase == CallPhase.active)
              Positioned.fill(
                child: AlarmOverlay(
                  key: ValueKey(alarm.serial),
                  alarm: alarm,
                  warning: c.catalog.warningText(alarm.clip, alarm.language),
                  whisper: c.whisper,
                  micPaused: c.micPausedForWhisper,
                  onDismiss: c.dismissAlarm,
                  onHangUp: c.endCall,
                ),
              ),
          ],
        ),
      ),
    );
  }
}
