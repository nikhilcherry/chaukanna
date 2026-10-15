import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/livekit_service.dart';
import '../state/guardian_controller.dart';
import '../theme.dart';
import '../widgets/guardian_badge.dart';
import '../widgets/pressure_gauge.dart';
import '../widgets/transcript_view.dart';
import '../widgets/verdict_chips.dart';

/// Screen 1: Active Call Guardian (also the idle "ready" view).
class CallScreen extends StatelessWidget {
  const CallScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final c = context.watch<GuardianController>();
    if (c.phase == CallPhase.idle) return const _IdleView();
    return SafeArea(
      child: LayoutBuilder(builder: (context, box) {
        final compact = box.maxHeight < 720 || MediaQuery.textScalerOf(context).scale(10) > 11.5;
        return Column(children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 12, 20, 0),
            child: Row(children: [
              const CircleAvatar(radius: 26, backgroundColor: Pal.card, child: Icon(Icons.person, size: 32)),
              const SizedBox(width: 12),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(c.callerNumber,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w800)),
                  Text(c.callerLabel.isNotEmpty ? 'Says: ${c.callerLabel}' : 'Unknown caller',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontSize: 17, color: Pal.dim)),
                ]),
              ),
              const SizedBox(width: 8),
              Text(mmss(c.elapsed),
                  style: const TextStyle(
                      fontSize: 28, fontWeight: FontWeight.w700, fontFeatures: [FontFeature.tabularFigures()])),
            ]),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 10, 16, 0),
            child: Wrap(spacing: 8, runSpacing: 8, alignment: WrapAlignment.center, children: [
              GuardianBadge(status: c.guardianStatus),
              if (c.simulated) const _Tag('SIMULATED CALL'),
            ]),
          ),
          Expanded(
            child: LayoutBuilder(builder: (context, mid) {
              final gauge = PressureGauge(pressure: c.peakPressure, height: compact ? 112 : 170);
              final chips = Padding(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                child: VerdictChips(
                    scamType: c.scamType, asksOtp: c.sawOtpAsk, secrecy: c.sawSecrecy, knownScammer: c.knownScammer),
              );
              final banners = [
                if (c.micPausedForWhisper)
                  const _Banner(Icons.mic_off, 'Your microphone is paused while Chaukanna warns you.'),
                if (c.incident != null) _ResponseBanner(c: c),
              ];
              Widget transcriptBox() => Container(
                    margin: const EdgeInsets.fromLTRB(16, 8, 16, 8),
                    decoration: BoxDecoration(color: Pal.card, borderRadius: BorderRadius.circular(20)),
                    child: ClipRRect(
                        borderRadius: BorderRadius.circular(20), child: TranscriptView(lines: c.transcript)),
                  );
              // The risk block never takes more than ~58% of the middle (it scrolls
              // inside itself on small phones / large text), so the live
              // transcript always stays on screen.
              return Column(children: [
                ConstrainedBox(
                  constraints: BoxConstraints(maxHeight: mid.maxHeight * 0.58),
                  child: SingleChildScrollView(child: Column(children: [gauge, chips, ...banners])),
                ),
                Expanded(child: transcriptBox()),
              ]);
            }),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
            child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
              Expanded(
                child: _RoundBtn(
                    icon: c.userMuted ? Icons.mic_off : Icons.mic,
                    label: c.userMuted ? 'Unmute' : 'Mute',
                    active: c.userMuted,
                    onTap: c.toggleMute),
              ),
              Expanded(
                child: _RoundBtn(
                    icon: c.speaker ? Icons.volume_up : Icons.phone_in_talk,
                    label: c.speaker ? 'Speaker on' : 'Speaker off',
                    active: c.speaker,
                    onTap: c.toggleSpeaker),
              ),
              Expanded(
                child: _RoundBtn(
                    icon: Icons.call_end, label: 'Hang up', color: Pal.critical, big: true, onTap: c.endCall),
              ),
            ]),
          ),
        ]);
      }),
    );
  }
}

class _Tag extends StatelessWidget {
  const _Tag(this.text);
  final String text;
  @override
  Widget build(BuildContext context) => Container(
        constraints: const BoxConstraints(minHeight: 40),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(borderRadius: BorderRadius.circular(24), border: Border.all(color: Pal.caution, width: 2)),
        child: Text(text, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w900, color: Pal.caution)),
      );
}

class _Banner extends StatelessWidget {
  const _Banner(this.icon, this.text);
  final IconData icon;
  final String text;
  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.fromLTRB(16, 6, 16, 0),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        decoration: BoxDecoration(color: Pal.cardHi, borderRadius: BorderRadius.circular(14)),
        child: Row(children: [
          Icon(icon, size: 24, color: Pal.caution),
          const SizedBox(width: 10),
          Expanded(child: Text(text, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700))),
        ]),
      );
}

/// What n8n has already done, live during the call.
class _ResponseBanner extends StatelessWidget {
  const _ResponseBanner({required this.c});
  final GuardianController c;
  @override
  Widget build(BuildContext context) {
    final i = c.incident!;
    final done = [
      if (i.familyAlerted == true) 'Family alerted',
      if (i.evidenceSaved == true) 'Evidence saved',
      if (i.blocklisted == true) 'Number blocklisted',
    ];
    return _Banner(Icons.task_alt, done.isEmpty ? 'Response team is on it.' : '✓ ${done.join('  ✓ ')}');
  }
}

class _RoundBtn extends StatelessWidget {
  const _RoundBtn({
    required this.icon,
    required this.label,
    required this.onTap,
    this.active = false,
    this.big = false,
    this.color,
  });

  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final bool active;
  final bool big;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final size = big ? 84.0 : 72.0;
    final bg = color ?? (active ? Colors.white : Pal.card);
    return Semantics(
      button: true,
      label: label,
      excludeSemantics: true,
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        Material(
          color: bg,
          shape: const CircleBorder(side: BorderSide(color: Colors.white24, width: 2)),
          child: InkWell(
            customBorder: const CircleBorder(),
            onTap: onTap,
            child: SizedBox(
                width: size,
                height: size,
                child: Icon(icon, size: 38, color: color != null ? Colors.white : (active ? Colors.black : Colors.white))),
          ),
        ),
        const SizedBox(height: 6),
        FittedBox(
          fit: BoxFit.scaleDown,
          child: Text(label, maxLines: 1, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
        ),
      ]),
    );
  }
}

class _IdleView extends StatelessWidget {
  const _IdleView();

  @override
  Widget build(BuildContext context) {
    final c = context.watch<GuardianController>();
    final last = c.lastCall;
    final link = switch (c.link) {
      LinkState.off => c.liveKitEnabled ? 'Not connected' : 'No call server set up: use the Demo Simulator',
      LinkState.connecting => 'Connecting to the call server…',
      LinkState.connected => 'Ready for calls',
      LinkState.reconnecting => 'Call server lost, reconnecting…',
      LinkState.failed => 'Another phone is using this account',
    };
    return SafeArea(
      child: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(28),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const Icon(Icons.shield, size: 96, color: Pal.safe),
            const SizedBox(height: 16),
            const Text('Chaukanna', style: TextStyle(fontSize: 42, fontWeight: FontWeight.w900)),
            const SizedBox(height: 4),
            const Text('चौकन्ना · ಚೌಕನ್ನ', style: TextStyle(fontSize: 22, color: Pal.dim)),
            const SizedBox(height: 18),
            GuardianBadge(status: c.guardianStatus),
            const SizedBox(height: 18),
            const Text('Your call guardian is ready.\nWe will warn you if a call looks like a scam.',
                textAlign: TextAlign.center, style: TextStyle(fontSize: 21, color: Pal.dim, height: 1.4)),
            const SizedBox(height: 10),
            Text(link, textAlign: TextAlign.center, style: const TextStyle(fontSize: 17, color: Pal.dim)),
            if (last != null) ...[
              const SizedBox(height: 22),
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(color: Pal.card, borderRadius: BorderRadius.circular(16)),
                child: Row(children: [
                  const Icon(Icons.check_circle, color: Pal.safe, size: 32),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text('Last call from ${last.number} (${mmss(last.duration)}): no scam found.',
                        style: const TextStyle(fontSize: 18, height: 1.35)),
                  ),
                ]),
              ),
            ],
            const SizedBox(height: 36),
            const Text('Developer: swipe in from the right edge\nto open the Demo Simulator.',
                textAlign: TextAlign.center, style: TextStyle(fontSize: 16, color: Pal.dim)),
          ]),
        ),
      ),
    );
  }
}
