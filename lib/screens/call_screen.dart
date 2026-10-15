import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/guardian_controller.dart';
import '../theme.dart';
import '../widgets/pressure_gauge.dart';
import '../widgets/transcript_view.dart';
import '../widgets/verdict_chips.dart';

/// Screen 1: Active Call Guardian.
class CallScreen extends StatelessWidget {
  const CallScreen({super.key});

  static String _fmt(Duration d) =>
      '${d.inMinutes.toString().padLeft(2, '0')}:${(d.inSeconds % 60).toString().padLeft(2, '0')}';

  @override
  Widget build(BuildContext context) {
    final c = context.watch<GuardianController>();
    if (c.phase == CallPhase.idle) return const _IdleView();
    final v = c.verdict;
    return SafeArea(
      child: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 0),
          child: Row(children: [
            const CircleAvatar(radius: 28, backgroundColor: Pal.card, child: Icon(Icons.person, size: 34)),
            const SizedBox(width: 14),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(c.callerNumber,
                    style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w800), maxLines: 1),
                const Text('Unknown caller · Chaukanna is listening',
                    style: TextStyle(fontSize: 15, color: Pal.dim)),
              ]),
            ),
            Text(_fmt(c.elapsed),
                style: const TextStyle(
                    fontSize: 28, fontWeight: FontWeight.w700, fontFeatures: [FontFeature.tabularFigures()])),
          ]),
        ),
        const SizedBox(height: 12),
        PressureGauge(pressure: v.pressure),
        Padding(padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8), child: VerdictChips(verdict: v)),
        Expanded(
          child: Container(
            margin: const EdgeInsets.fromLTRB(16, 8, 16, 8),
            decoration: BoxDecoration(color: Pal.card, borderRadius: BorderRadius.circular(20)),
            child: ClipRRect(
                borderRadius: BorderRadius.circular(20), child: TranscriptView(lines: c.transcript)),
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 20),
          child: Row(mainAxisAlignment: MainAxisAlignment.spaceEvenly, children: [
            _RoundBtn(
                icon: c.muted ? Icons.mic_off : Icons.mic,
                label: c.muted ? 'Unmute' : 'Mute',
                active: c.muted,
                onTap: c.toggleMute),
            _RoundBtn(
                icon: c.speaker ? Icons.volume_up : Icons.volume_down,
                label: 'Speaker',
                active: c.speaker,
                onTap: c.toggleSpeaker),
            _RoundBtn(
                icon: Icons.call_end, label: 'Hang up', color: Pal.critical, big: true, onTap: c.endCall),
          ]),
        ),
      ]),
    );
  }
}

class _RoundBtn extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final bool active;
  final bool big;
  final Color? color;
  const _RoundBtn(
      {required this.icon,
      required this.label,
      required this.onTap,
      this.active = false,
      this.big = false,
      this.color});

  @override
  Widget build(BuildContext context) {
    final size = big ? 84.0 : 72.0;
    return Semantics(
      button: true,
      label: label,
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        InkResponse(
          onTap: onTap,
          child: Container(
            width: size,
            height: size,
            decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: color ?? (active ? Colors.white : Pal.card),
                border: Border.all(color: Colors.white24, width: 2)),
            child: Icon(icon, size: 36, color: color != null || !active ? Colors.white : Colors.black),
          ),
        ),
        const SizedBox(height: 6),
        Text(label, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
      ]),
    );
  }
}

class _IdleView extends StatelessWidget {
  const _IdleView();

  @override
  Widget build(BuildContext context) {
    return const SafeArea(
      child: Center(
        child: Padding(
          padding: EdgeInsets.all(32),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.shield, size: 96, color: Pal.safe),
            SizedBox(height: 20),
            Text('Chaukanna', style: TextStyle(fontSize: 40, fontWeight: FontWeight.w900)),
            SizedBox(height: 8),
            Text('Your call guardian is ready.\nWe will warn you if a call looks like a scam.',
                textAlign: TextAlign.center, style: TextStyle(fontSize: 20, color: Pal.dim, height: 1.4)),
            SizedBox(height: 40),
            Text('Developer: swipe in from the right edge\nto open the Demo Simulator.',
                textAlign: TextAlign.center, style: TextStyle(fontSize: 14, color: Pal.dim)),
          ]),
        ),
      ),
    );
  }
}
