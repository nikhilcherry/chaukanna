import 'package:flutter/material.dart';

import '../models/scam_profile.dart';
import '../services/clip_catalog.dart';
import '../state/guardian_controller.dart';
import '../theme.dart';

/// Screen 2: the warning. The screen takes the call type's colour, rings ripple
/// out of its icon, then the bilingual warning (the words of the whisper being
/// spoken), a card saying why this is a scam and what to do, and two big actions
/// that are always on screen.
class AlarmOverlay extends StatelessWidget {
  const AlarmOverlay({
    super.key,
    required this.alarm,
    required this.warning,
    required this.whisper,
    required this.micPaused,
    required this.onDismiss,
    required this.onHangUp,
  });

  final AlarmInfo alarm;
  final WarningText warning;
  final WhisperState whisper;
  final bool micPaused;
  final VoidCallback onDismiss;
  final VoidCallback onHangUp;

  @override
  Widget build(BuildContext context) {
    final a = alarm;
    final w = warning;
    // The clip names what just happened (an OTP ask, a secrecy demand), so it
    // outranks the call's overall type for the headline and colours.
    final p = switch (a.clip) {
      'warn_otp' => ScamProfile.otp,
      'warn_secrecy' => ScamProfile.secrecy,
      _ => ScamProfile.resolve(scamType: a.scamType, knownScammer: a.knownScammer, clip: a.clip),
    };
    final fg = p.onField;
    final title = a.knownScammer ? 'KNOWN SCAMMER' : p.label.toUpperCase();
    return Container(
      color: p.field,
      child: SafeArea(
        child: Column(
          children: [
            // Warning text scrolls if it must; the two actions are always on screen.
            Expanded(
              child: LayoutBuilder(
                builder: (context, box) => SingleChildScrollView(
                  padding: const EdgeInsets.fromLTRB(24, 8, 24, 8),
                  child: ConstrainedBox(
                    constraints: BoxConstraints(minHeight: box.maxHeight - 16),
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        _RippleIcon(profile: p),
                        const SizedBox(height: 6),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
                          decoration: BoxDecoration(
                            color: fg.withValues(alpha: 0.14),
                            borderRadius: BorderRadius.circular(20),
                          ),
                          child: Text(
                            title,
                            textAlign: TextAlign.center,
                            style: display(14, color: fg, letterSpacing: 1.6),
                          ),
                        ),
                        const SizedBox(height: 14),
                        Semantics(
                          liveRegion: true,
                          child: Text(
                            w.en,
                            textAlign: TextAlign.center,
                            style: display(34, color: fg, height: 1.1, letterSpacing: -0.8),
                          ),
                        ),
                        if (w.local != null) ...[
                          const SizedBox(height: 10),
                          Text(
                            w.local!,
                            textAlign: TextAlign.center,
                            style: TextStyle(fontSize: 26, fontWeight: FontWeight.w800, height: 1.3, color: fg),
                          ),
                        ],
                        const SizedBox(height: 16),
                        _Notice(profile: p),
                        const SizedBox(height: 12),
                        _VoiceStatus(whisper: whisper, fg: fg),
                        if (micPaused) ...[
                          const SizedBox(height: 10),
                          Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(Icons.mic_off, size: 24, color: fg),
                              const SizedBox(width: 8),
                              Flexible(
                                child: Text(
                                  'Your microphone is paused. The caller cannot hear this.',
                                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: fg),
                                ),
                              ),
                            ],
                          ),
                        ],
                      ],
                    ),
                  ),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 8, 20, 16),
              child: Column(
                children: [
                  SizedBox(
                    width: double.infinity,
                    height: 62,
                    child: FilledButton.icon(
                      style: FilledButton.styleFrom(
                        backgroundColor: Pal.paper,
                        foregroundColor: Pal.red,
                        elevation: 0,
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(31)),
                      ),
                      onPressed: onHangUp,
                      icon: const Icon(Icons.call_end, size: 30),
                      label: FittedBox(
                        fit: BoxFit.scaleDown,
                        child: Text('Hang up now', style: display(24, color: Pal.red, letterSpacing: -0.3)),
                      ),
                    ),
                  ),
                  const SizedBox(height: 10),
                  SizedBox(
                    width: double.infinity,
                    height: 52,
                    child: TextButton(
                      style: TextButton.styleFrom(
                        foregroundColor: fg,
                        backgroundColor: fg.withValues(alpha: 0.14),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(26)),
                      ),
                      onPressed: onDismiss,
                      child: FittedBox(
                        fit: BoxFit.scaleDown,
                        child: Text('I understand', style: display(20, color: fg, weight: 700, letterSpacing: -0.2)),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// The call type's icon in a solid disc, with rings spreading out of it. Rings hold
/// still when the phone asks for reduced motion.
class _RippleIcon extends StatefulWidget {
  const _RippleIcon({required this.profile});
  final ScamProfile profile;

  @override
  State<_RippleIcon> createState() => _RippleIconState();
}

class _RippleIconState extends State<_RippleIcon> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 2400));

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (MediaQuery.of(context).disableAnimations) {
      _c.stop();
      _c.value = 0.3;
    } else if (!_c.isAnimating) {
      _c.repeat();
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = widget.profile;
    return ExcludeSemantics(
      child: SizedBox(
        width: 150,
        height: 150,
        child: CustomPaint(
          painter: _RipplePainter(_c, p.onField),
          child: Center(
            child: Container(
              width: 80,
              height: 80,
              decoration: BoxDecoration(color: p.onField, shape: BoxShape.circle),
              child: Icon(p.icon, size: 42, color: p.field),
            ),
          ),
        ),
      ),
    );
  }
}

class _RipplePainter extends CustomPainter {
  _RipplePainter(this.anim, this.color) : super(repaint: anim);
  final Animation<double> anim;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final c = size.center(Offset.zero);
    for (var i = 0; i < 3; i++) {
      final t = (anim.value + i / 3) % 1.0;
      final r = 40 + (size.width / 2 - 40) * t;
      canvas.drawCircle(
        c,
        r,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 3
          ..color = color.withValues(alpha: 0.45 * (1 - t)),
      );
    }
  }

  @override
  bool shouldRepaint(_RipplePainter old) => old.color != color;
}

/// The plain-language card: why this is a scam, what to do.
class _Notice extends StatelessWidget {
  const _Notice({required this.profile});
  final ScamProfile profile;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(18, 14, 18, 16),
      decoration: cardDecoration(radius: 24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            profile.truth,
            style: const TextStyle(fontSize: 16, height: 1.35, color: Pal.dim, fontWeight: FontWeight.w500),
          ),
          const SizedBox(height: 8),
          Text(profile.action, style: display(21, color: Pal.ink, height: 1.2, letterSpacing: -0.3)),
        ],
      ),
    );
  }
}

class _VoiceStatus extends StatelessWidget {
  const _VoiceStatus({required this.whisper, required this.fg});
  final WhisperState whisper;
  final Color fg;

  @override
  Widget build(BuildContext context) {
    final (icon, label) = switch (whisper.status) {
      WhisperStatus.playing => (Icons.record_voice_over, 'Speaking the warning…'),
      WhisperStatus.done => (Icons.check_circle_outline, 'Voice warning played'),
      WhisperStatus.failed => (Icons.volume_off, 'Voice warning could not play. Please read this screen.'),
      WhisperStatus.stopped => (Icons.stop_circle_outlined, 'Voice warning stopped'),
      WhisperStatus.idle => (Icons.volume_up, 'Read the warning above'),
    };
    // The short clip's words are already the headline; caption the longer full clip.
    final caption = whisper.playing && whisper.current?.variant == 'full' ? whisper.current?.text : null;
    final strong = whisper.status == WhisperStatus.playing || whisper.status == WhisperStatus.failed;
    return Column(
      children: [
        Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 26, color: fg),
            const SizedBox(width: 10),
            Flexible(
              child: Text(
                label,
                style: TextStyle(
                  fontSize: 18,
                  fontWeight: strong ? FontWeight.w800 : FontWeight.w600,
                  color: fg.withValues(alpha: strong ? 1 : 0.85),
                ),
              ),
            ),
          ],
        ),
        if (caption != null && caption.isNotEmpty) ...[
          const SizedBox(height: 8),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(color: fg.withValues(alpha: 0.14), borderRadius: BorderRadius.circular(16)),
            child: Text(
              '🔊 $caption',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 18, height: 1.35, color: fg),
            ),
          ),
        ],
      ],
    );
  }
}
