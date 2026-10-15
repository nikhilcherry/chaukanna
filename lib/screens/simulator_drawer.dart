import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/guardian_controller.dart';
import '../theme.dart';

/// Hidden developer panel: injects fake Verdict packets so the UI runs with
/// no backend.
class SimulatorDrawer extends StatelessWidget {
  const SimulatorDrawer({super.key});

  @override
  Widget build(BuildContext context) {
    final c = context.watch<GuardianController>();
    void run(VoidCallback f) {
      Navigator.of(context).pop(); // close drawer, then inject
      f();
    }

    return Drawer(
      backgroundColor: const Color(0xFF10151C),
      child: SafeArea(
        child: ListView(padding: const EdgeInsets.all(16), children: [
          const Text('🛠 Demo Simulator', style: TextStyle(fontSize: 22, fontWeight: FontWeight.w900)),
          const Text('Injects fake guardian packets. No backend needed.',
              style: TextStyle(color: Pal.dim, fontSize: 13)),
          const SizedBox(height: 14),
          const Text('Language', style: TextStyle(color: Pal.dim)),
          const SizedBox(height: 6),
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: 'en', label: Text('EN')),
              ButtonSegment(value: 'hi', label: Text('हिं')),
              ButtonSegment(value: 'kn', label: Text('ಕನ್')),
            ],
            selected: {c.simLanguage},
            onSelectionChanged: (s) => c.setSimLanguage(s.first),
          ),
          const SizedBox(height: 16),
          _Sim('Simulate Pressure 0', Pal.safe, () => run(c.simulatePressure0)),
          _Sim('Simulate Pressure 2 (OTP Ask)', Pal.high, () => run(c.simulatePressure2Otp)),
          _Sim('Simulate Pressure 3 (Digital Arrest + Whisper)', Pal.critical,
              () => run(c.simulatePressure3DigitalArrest)),
          _Sim('Simulate Known Scammer Auto-Block', Pal.crimson, () => run(c.simulateKnownScammer)),
          const Divider(height: 32),
          _Sim('End call → post-call screen', Colors.blueGrey, () => run(c.endCall),
              enabled: c.phase == CallPhase.active),
          _Sim('Reset to idle', Colors.blueGrey, () => run(c.resetToIdle)),
        ]),
      ),
    );
  }
}

class _Sim extends StatelessWidget {
  final String label;
  final Color color;
  final VoidCallback onTap;
  final bool enabled;
  const _Sim(this.label, this.color, this.onTap, {this.enabled = true});

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: FilledButton(
          style: FilledButton.styleFrom(
              backgroundColor: color,
              minimumSize: const Size.fromHeight(56),
              alignment: Alignment.centerLeft),
          onPressed: enabled ? onTap : null,
          child: Text(label, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
        ),
      );
}
