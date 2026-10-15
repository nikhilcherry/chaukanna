import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config.dart';
import '../state/guardian_controller.dart';
import '../theme.dart';

/// Hidden developer panel. Every button injects JSON packets through the same
/// parser as LiveKit, so the whole demo runs with no backend.
class SimulatorDrawer extends StatelessWidget {
  const SimulatorDrawer({super.key});

  @override
  Widget build(BuildContext context) {
    final c = context.watch<GuardianController>();
    void run(VoidCallback f) {
      Navigator.of(context).pop(); // close the drawer, then inject
      f();
    }

    return Drawer(
      width: 340,
      backgroundColor: const Color(0xFF10151C),
      child: SafeArea(
        child: ListView(padding: const EdgeInsets.all(16), children: [
          const Text('🛠 Demo Simulator', style: TextStyle(fontSize: 22, fontWeight: FontWeight.w900)),
          const Text('Fake guardian packets through the real parser. No backend needed.',
              style: TextStyle(color: Pal.dim, fontSize: 15)),
          const SizedBox(height: 14),
          const Text('Call language', style: TextStyle(color: Pal.dim, fontSize: 15)),
          const SizedBox(height: 6),
          SegmentedButton<String>(
            style: SegmentedButton.styleFrom(minimumSize: const Size(0, 48)),
            segments: const [
              ButtonSegment(value: 'en', label: Text('EN')),
              ButtonSegment(value: 'hi', label: Text('हिंदी')),
              ButtonSegment(value: 'kn', label: Text('ಕನ್ನಡ')),
            ],
            selected: {c.simLanguage},
            onSelectionChanged: (s) => c.setSimLanguage(s.first),
          ),
          const SizedBox(height: 16),
          _Sim('▶ Full scripted scam call (~40 s)', Pal.critical, () => run(c.runFullScamCall), big: true),
          if (c.scriptRunning)
            const Padding(
              padding: EdgeInsets.only(bottom: 10),
              child: Text('Scripted call running. "Reset" stops it.', style: TextStyle(color: Pal.caution, fontSize: 15)),
            ),
          const Divider(height: 24),
          _Sim('Simulate Pressure 0', Pal.safe, () => run(c.simulatePressure0)),
          _Sim('Simulate Pressure 2 (OTP Ask)', Pal.high, () => run(c.simulatePressure2Otp)),
          _Sim('Simulate Pressure 3 (Digital Arrest + Whisper)', Pal.critical,
              () => run(c.simulatePressure3DigitalArrest)),
          _Sim('Simulate Known Scammer Auto-Block', Pal.crimson, () => run(c.simulateKnownScammer)),
          const Divider(height: 24),
          _Sim('End call', Colors.blueGrey, () => run(c.simulateCallEnded), enabled: c.phase == CallPhase.active),
          _Sim('Reset to idle', Colors.blueGrey, () => run(c.resetToIdle)),
          const Divider(height: 24),
          _Status(c: c),
          const SizedBox(height: 12),
          const Text('Debug log', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
          const SizedBox(height: 6),
          for (final e in c.log.entries.take(40))
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Text('${e.clock}  ${e.message}',
                  style: TextStyle(
                      fontSize: 13,
                      fontFamily: 'monospace',
                      color: e.important ? Pal.caution : Pal.dim,
                      fontWeight: e.important ? FontWeight.w700 : FontWeight.w400)),
            ),
        ]),
      ),
    );
  }
}

class _Status extends StatelessWidget {
  const _Status({required this.c});
  final GuardianController c;
  @override
  Widget build(BuildContext context) {
    final lines = [
      'LiveKit: ${c.liveKitEnabled ? c.link.name : 'not configured'}',
      'Guardian: ${c.guardianStatus.name}',
      'Call: ${c.phase.name}${c.callId == null ? '' : ' ${c.callId}'}',
      'Whisper clips: ${c.catalog.bundledAudioCount ?? '?'} WAVs, mic pause ${AppConfig.muteMicDuringWhisper ? 'on' : 'off'}, '
          'route ${AppConfig.whisperRoute}',
      'Approval webhook: ${Uri.tryParse(AppConfig.n8nApprovalWebhook)?.host ?? '-'}',
    ];
    return Text(lines.join('\n'), style: const TextStyle(fontSize: 14, color: Pal.dim, height: 1.4));
  }
}

class _Sim extends StatelessWidget {
  const _Sim(this.label, this.color, this.onTap, {this.enabled = true, this.big = false});
  final String label;
  final Color color;
  final VoidCallback onTap;
  final bool enabled;
  final bool big;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: FilledButton(
          style: FilledButton.styleFrom(
            backgroundColor: color,
            foregroundColor: Pal.onColor(color),
            minimumSize: Size.fromHeight(big ? 64 : 56),
            alignment: Alignment.centerLeft,
          ),
          onPressed: enabled ? onTap : null,
          child: Text(label, style: TextStyle(fontSize: big ? 18 : 16, fontWeight: FontWeight.w800)),
        ),
      );
}
