import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/scam_profile.dart';
import '../services/livekit_service.dart';
import '../state/guardian_controller.dart';
import '../theme.dart';
import '../widgets/guardian_badge.dart';
import '../widgets/phone_protection_card.dart';
import '../widgets/risk_ring.dart';
import '../widgets/transcript_view.dart';
import '../widgets/verdict_chips.dart';

/// Screen 1: Active Call Guardian (also the idle "ready" view).
///
/// The top panel and the watch ring take the colour of the call type once a scam
/// is recognised; the ring fills as the risk climbs. Everything below stays calm
/// and white so the one coloured thing is the thing to worry about.
class CallScreen extends StatelessWidget {
  const CallScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final c = context.watch<GuardianController>();
    if (c.phase == CallPhase.idle) return const _IdleView();
    final alert = (c.scamType != 'none' && c.scamType.isNotEmpty) || c.knownScammer
        ? ScamProfile.resolve(scamType: c.scamType, knownScammer: c.knownScammer)
        : null;
    final accent = alert?.field ?? Pal.brand;
    final panel = alert == null ? Pal.brandSoft : Color.alphaBlend(accent.withValues(alpha: 0.16), Pal.bg);
    return LayoutBuilder(
      builder: (context, box) {
        final compact = box.maxHeight < 720 || MediaQuery.textScalerOf(context).scale(10) > 11.5;
        return Column(
          children: [
            AnimatedContainer(
              duration: const Duration(milliseconds: 450),
              width: double.infinity,
              decoration: BoxDecoration(
                color: panel,
                borderRadius: const BorderRadius.vertical(bottom: Radius.circular(32)),
              ),
              child: SafeArea(
                bottom: false,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(20, 10, 20, 16),
                  child: Column(
                    children: [
                      Row(
                        children: [
                          Container(
                            width: 46,
                            height: 46,
                            decoration: const BoxDecoration(color: Pal.paper, shape: BoxShape.circle),
                            child: const Icon(Icons.person, size: 26, color: Pal.dim),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  c.callerDisplay,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: display(22, color: Pal.ink, letterSpacing: -0.2),
                                ),
                                Text(
                                  c.callerLabel.isNotEmpty ? 'Says: ${c.callerLabel}' : 'Unknown caller',
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: Pal.dim),
                                ),
                              ],
                            ),
                          ),
                          const SizedBox(width: 8),
                          Container(
                            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
                            decoration: BoxDecoration(color: Pal.paper, borderRadius: BorderRadius.circular(20)),
                            child: Text(
                              mmss(c.elapsed),
                              style: display(
                                20,
                                color: Pal.ink,
                                letterSpacing: 0,
                              ).copyWith(fontFeatures: const [FontFeature.tabularFigures()]),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 10),
                      Wrap(
                        spacing: 8,
                        runSpacing: 6,
                        alignment: WrapAlignment.center,
                        children: [
                          GuardianBadge(status: c.guardianStatus),
                          if (c.simulated) const _SimTag(),
                        ],
                      ),
                      SizedBox(height: compact ? 8 : 14),
                      RiskRing(
                        litSegments: c.peakPressure + 1,
                        color: accent,
                        size: compact ? 132 : 176,
                        breathe: c.peakPressure >= 2,
                        semanticsLabel: 'Scam pressure ${Pal.labelFor(c.peakPressure)}, level ${c.peakPressure} of 3',
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Icon(alert?.icon ?? Icons.verified_user, size: compact ? 30 : 40, color: accent),
                            SizedBox(height: compact ? 2 : 6),
                            SizedBox(
                              width: (compact ? 132 : 176) * 0.58,
                              child: FittedBox(
                                fit: BoxFit.scaleDown,
                                child: Text(Pal.labelFor(c.peakPressure), style: display(20, color: Pal.ink)),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
            Expanded(
              child: LayoutBuilder(
                builder: (context, mid) {
                  final banners = [
                    if (c.micPausedForWhisper)
                      const _Banner(Icons.mic_off, 'Your microphone is paused while Chaukanna warns you.'),
                    if (c.incident != null) _ResponseBanner(c: c),
                  ];
                  // The alert block never takes more than ~55% of what is left (it scrolls
                  // inside itself on small phones / large text), so the live
                  // transcript always stays on screen.
                  return Column(
                    children: [
                      ConstrainedBox(
                        constraints: BoxConstraints(maxHeight: mid.maxHeight * 0.55),
                        child: SingleChildScrollView(
                          padding: const EdgeInsets.only(top: 14),
                          child: Column(
                            children: [
                              VerdictChips(
                                scamType: c.scamType,
                                asksOtp: c.sawOtpAsk,
                                secrecy: c.sawSecrecy,
                                knownScammer: c.knownScammer,
                              ),
                              ...banners,
                            ],
                          ),
                        ),
                      ),
                      Expanded(
                        child: Container(
                          margin: const EdgeInsets.fromLTRB(16, 12, 16, 8),
                          decoration: cardDecoration(),
                          child: ClipRRect(
                            borderRadius: BorderRadius.circular(20),
                            child: TranscriptView(lines: c.transcript),
                          ),
                        ),
                      ),
                    ],
                  );
                },
              ),
            ),
            SafeArea(
              top: false,
              child: Container(
                margin: const EdgeInsets.fromLTRB(16, 4, 16, 14),
                padding: const EdgeInsets.fromLTRB(14, 10, 12, 10),
                decoration: cardDecoration(radius: 34),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.center,
                  children: [
                    _RoundAct(
                      icon: c.userMuted ? Icons.mic_off : Icons.mic,
                      label: c.userMuted ? 'Unmute' : 'Mute',
                      active: c.userMuted,
                      onTap: c.toggleMute,
                    ),
                    const SizedBox(width: 6),
                    _RoundAct(
                      icon: c.speaker ? Icons.volume_up : Icons.phone_in_talk,
                      label: c.speaker ? 'Speaker on' : 'Speaker off',
                      active: c.speaker,
                      onTap: c.toggleSpeaker,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Semantics(
                        button: true,
                        label: 'Hang up',
                        excludeSemantics: true,
                        child: SizedBox(
                          height: 60,
                          child: FilledButton.icon(
                            style: FilledButton.styleFrom(backgroundColor: Pal.red, foregroundColor: Colors.white),
                            onPressed: c.endCall,
                            icon: const Icon(Icons.call_end, size: 28),
                            label: const FittedBox(fit: BoxFit.scaleDown, child: Text('Hang up', maxLines: 1)),
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        );
      },
    );
  }
}

class _SimTag extends StatelessWidget {
  const _SimTag();
  @override
  Widget build(BuildContext context) => Container(
    constraints: const BoxConstraints(minHeight: 38),
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
    decoration: BoxDecoration(color: const Color(0xFFFFF1CC), borderRadius: BorderRadius.circular(20)),
    child: const Text(
      'SIMULATED CALL',
      style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, letterSpacing: 0.8, color: Pal.caution),
    ),
  );
}

class _Banner extends StatelessWidget {
  const _Banner(this.icon, this.text);
  final IconData icon;
  final String text;
  @override
  Widget build(BuildContext context) => Container(
    margin: const EdgeInsets.fromLTRB(16, 10, 16, 0),
    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
    decoration: cardDecoration(radius: 16),
    child: Row(
      children: [
        Icon(icon, size: 24, color: Pal.brand),
        const SizedBox(width: 10),
        Expanded(
          child: Text(
            text,
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: Pal.ink),
          ),
        ),
      ],
    ),
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

class _RoundAct extends StatelessWidget {
  const _RoundAct({required this.icon, required this.label, required this.onTap, this.active = false});

  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final bool active;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: label,
      excludeSemantics: true,
      child: SizedBox(
        width: 68,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Material(
              color: active ? Pal.brand : Pal.cardHi,
              shape: const CircleBorder(),
              child: InkWell(
                customBorder: const CircleBorder(),
                onTap: onTap,
                child: SizedBox(
                  width: 52,
                  height: 52,
                  child: Icon(icon, size: 26, color: active ? Colors.white : Pal.ink),
                ),
              ),
            ),
            const SizedBox(height: 3),
            FittedBox(
              fit: BoxFit.scaleDown,
              child: Text(
                label,
                maxLines: 1,
                style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: Pal.dim),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// The landing page is the demo simulator: pick a call to play and watch the app react.
/// Every button feeds the real message parser, so nothing here needs a backend.
class _IdleView extends StatelessWidget {
  const _IdleView();

  @override
  Widget build(BuildContext context) {
    final c = context.watch<GuardianController>();
    final last = c.lastCall;
    final link = switch (c.link) {
      LinkState.off => c.liveKitEnabled ? 'Not connected' : 'No call server set up',
      LinkState.connecting => 'Connecting to the call server…',
      LinkState.connected => 'Ready for calls',
      LinkState.reconnecting => 'Call server lost, reconnecting…',
      LinkState.failed => 'Another phone is using this account',
    };
    final scenarios = <_Scenario>[
      _Scenario('Safe call', Icons.check_circle, Pal.brand, Colors.white, c.simulatePressure0),
      _Scenario.of(ScamProfile.kyc, 'KYC scam', c.simulateKyc),
      _Scenario.of(ScamProfile.bank, 'Fake bank call', c.simulateBank),
      _Scenario.of(ScamProfile.prize, 'Prize scam', c.simulatePrize),
      _Scenario.of(ScamProfile.otp, 'OTP request', c.simulatePressure2Otp),
      _Scenario.of(ScamProfile.digitalArrest, 'Digital arrest', c.simulatePressure3DigitalArrest),
      _Scenario.of(ScamProfile.known, 'Known scammer number', c.simulateKnownScammer),
    ];
    return SafeArea(
      child: ListView(
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 28),
        children: [
          Row(
            children: [
              RiskRing(
                litSegments: 4,
                color: Pal.brand,
                size: 68,
                breathe: true,
                child: const Icon(Icons.verified_user, size: 24, color: Pal.brand),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Chaukanna', style: display(32, color: Pal.ink, letterSpacing: -0.6)),
                    const Wrap(
                      spacing: 10,
                      children: [
                        Text(
                          'चौकन्ना',
                          style: TextStyle(
                            fontFamily: 'NotoSansDevanagari',
                            fontSize: 17,
                            fontWeight: FontWeight.w700,
                            color: Pal.dim,
                          ),
                        ),
                        Text(
                          'ಚೌಕನ್ನ',
                          style: TextStyle(
                            fontFamily: 'NotoSansKannada',
                            fontSize: 17,
                            fontWeight: FontWeight.w700,
                            color: Pal.dim,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          Wrap(
            spacing: 8,
            runSpacing: 6,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              GuardianBadge(status: c.guardianStatus),
              Text(
                link,
                style: const TextStyle(fontSize: 15, color: Pal.grey, fontWeight: FontWeight.w600),
              ),
            ],
          ),
          if (c.phoneLayerAvailable) ...[const SizedBox(height: 18), const PhoneProtectionCard()],
          const SizedBox(height: 26),
          Text('Demo simulator', style: display(24, color: Pal.ink)),
          const SizedBox(height: 4),
          const Text(
            'Play a call and watch how Chaukanna warns you. Works with no internet.',
            style: TextStyle(fontSize: 16, height: 1.4, color: Pal.dim, fontWeight: FontWeight.w500),
          ),
          const SizedBox(height: 14),
          SegmentedButton<String>(
            showSelectedIcon: false,
            segments: const [
              ButtonSegment(value: 'en', label: Text('English')),
              ButtonSegment(value: 'hi', label: Text('हिंदी')),
              ButtonSegment(value: 'kn', label: Text('ಕನ್ನಡ')),
            ],
            selected: {c.simLanguage},
            onSelectionChanged: (s) => c.setSimLanguage(s.first),
          ),
          const SizedBox(height: 14),
          SizedBox(
            height: 64,
            child: FilledButton.icon(
              style: FilledButton.styleFrom(backgroundColor: Pal.brand, foregroundColor: Colors.white),
              onPressed: c.runFullScamCall,
              icon: const Icon(Icons.play_arrow_rounded, size: 32),
              label: const FittedBox(fit: BoxFit.scaleDown, child: Text('Play a full scam call (40 s)')),
            ),
          ),
          if (c.scriptRunning)
            const Padding(
              padding: EdgeInsets.only(top: 8),
              child: Text('A scripted call is running.', style: TextStyle(fontSize: 15, color: Pal.caution)),
            ),
          const SizedBox(height: 22),
          Text('Or try one kind of call', style: display(17, color: Pal.ink, letterSpacing: -0.1)),
          const SizedBox(height: 10),
          LayoutBuilder(
            builder: (context, box) {
              final half = (box.maxWidth - 10) / 2;
              return Wrap(
                spacing: 10,
                runSpacing: 10,
                children: [
                  for (var i = 0; i < scenarios.length; i++)
                    SizedBox(
                      width: i == scenarios.length - 1 ? box.maxWidth : half,
                      child: _ScenarioTile(scenario: scenarios[i]),
                    ),
                ],
              );
            },
          ),
          if (last != null) ...[
            const SizedBox(height: 22),
            Container(
              padding: const EdgeInsets.all(16),
              decoration: cardDecoration(),
              child: Row(
                children: [
                  const Icon(Icons.check_circle, color: Pal.brand, size: 30),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      'Last call from ${last.number} (${mmss(last.duration)}): no scam found.',
                      style: const TextStyle(fontSize: 17, height: 1.35, color: Pal.ink, fontWeight: FontWeight.w600),
                    ),
                  ),
                ],
              ),
            ),
          ],
          const SizedBox(height: 22),
          Center(
            child: TextButton.icon(
              onPressed: () => Scaffold.of(context).openEndDrawer(),
              icon: const Icon(Icons.terminal, size: 20),
              label: const Text('Debug log'),
            ),
          ),
        ],
      ),
    );
  }
}

class _Scenario {
  const _Scenario(this.label, this.icon, this.field, this.onField, this.run);
  factory _Scenario.of(ScamProfile p, String label, VoidCallback run) =>
      _Scenario(label, p.icon, p.field, p.onField, run);
  final String label;
  final IconData icon;
  final Color field;
  final Color onField;
  final VoidCallback run;
}

class _ScenarioTile extends StatelessWidget {
  const _ScenarioTile({required this.scenario});
  final _Scenario scenario;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: Ink(
        decoration: BoxDecoration(color: Pal.paper, borderRadius: BorderRadius.circular(20), boxShadow: kSoftShadow),
        child: InkWell(
          borderRadius: BorderRadius.circular(20),
          onTap: scenario.run,
          child: Container(
            constraints: const BoxConstraints(minHeight: 72),
            padding: const EdgeInsets.fromLTRB(10, 10, 12, 10),
            child: Row(
              children: [
                Container(
                  width: 46,
                  height: 46,
                  decoration: BoxDecoration(color: scenario.field, borderRadius: BorderRadius.circular(15)),
                  child: Icon(scenario.icon, size: 25, color: scenario.onField),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    scenario.label,
                    style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800, height: 1.2, color: Pal.ink),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
