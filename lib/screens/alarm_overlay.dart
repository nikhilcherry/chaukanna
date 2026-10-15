import 'package:flutter/material.dart';

import '../models/verdict.dart';
import '../services/clip_catalog.dart';
import '../state/guardian_controller.dart';
import '../theme.dart';

/// Screen 2: pulsing crimson border, giant bilingual warning (the words of the
/// whisper the victim is hearing), voice status, and two big actions.
class AlarmOverlay extends StatefulWidget {
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
  State<AlarmOverlay> createState() => _AlarmOverlayState();
}

class _AlarmOverlayState extends State<AlarmOverlay> with SingleTickerProviderStateMixin {
  late final AnimationController _pulse =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 700))..repeat(reverse: true);

  @override
  void dispose() {
    _pulse.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final a = widget.alarm;
    final w = widget.warning;
    final title = a.knownScammer
        ? 'KNOWN SCAMMER'
        : (a.scamType != 'none' ? scamLabelFor(a.scamType).toUpperCase() : 'SCAM WARNING');
    return AnimatedBuilder(
      animation: _pulse,
      builder: (context, child) {
        final t = Curves.easeInOut.transform(_pulse.value);
        return Container(
          decoration: BoxDecoration(
            color: Color.lerp(const Color(0xFF1A0006), const Color(0xFF3A000F), t),
            border: Border.all(color: Color.lerp(const Color(0xFF8B0A1F), Pal.crimson, t)!, width: 10 + 16 * t),
          ),
          child: child,
        );
      },
      child: SafeArea(
        child: Column(children: [
          // Warning text scrolls if it must; the two actions are always on screen.
          Expanded(
            child: LayoutBuilder(
              builder: (context, box) => SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(24, 16, 24, 8),
                child: ConstrainedBox(
                  constraints: BoxConstraints(minHeight: box.maxHeight - 24),
                  child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                    const Icon(Icons.warning_amber_rounded, size: 76, color: Colors.white),
                    const SizedBox(height: 4),
                    Text(title,
                        textAlign: TextAlign.center,
                        style: const TextStyle(
                            fontSize: 20, fontWeight: FontWeight.w900, letterSpacing: 2, color: Color(0xFFFFB3C0))),
                    const SizedBox(height: 12),
                    Semantics(
                      liveRegion: true,
                      child: Text(w.en,
                          textAlign: TextAlign.center,
                          style: const TextStyle(fontSize: 36, fontWeight: FontWeight.w900, height: 1.15)),
                    ),
                    if (w.local != null) ...[
                      const SizedBox(height: 16),
                      Text(w.local!,
                          textAlign: TextAlign.center,
                          style: const TextStyle(
                              fontSize: 34, fontWeight: FontWeight.w900, height: 1.3, color: Color(0xFFFFE0E6))),
                    ],
                    const SizedBox(height: 18),
                    _VoiceStatus(whisper: widget.whisper),
                    if (widget.micPaused) ...[
                      const SizedBox(height: 10),
                      const Row(mainAxisSize: MainAxisSize.min, children: [
                        Icon(Icons.mic_off, size: 24, color: Pal.caution),
                        SizedBox(width: 8),
                        Flexible(
                          child: Text('Your microphone is paused. The caller cannot hear this.',
                              style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
                        ),
                      ]),
                    ],
                  ]),
                ),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 8, 20, 16),
            child: Column(children: [
              SizedBox(
                width: double.infinity,
                height: 72,
                child: FilledButton.icon(
                  style: FilledButton.styleFrom(backgroundColor: Pal.critical, foregroundColor: Colors.white),
                  onPressed: widget.onHangUp,
                  icon: const Icon(Icons.call_end, size: 34),
                  label: const FittedBox(
                    fit: BoxFit.scaleDown,
                    child: Text('Hang up now', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w900)),
                  ),
                ),
              ),
              const SizedBox(height: 12),
              SizedBox(
                width: double.infinity,
                height: 64,
                child: FilledButton(
                  style: FilledButton.styleFrom(backgroundColor: Colors.white, foregroundColor: Colors.black),
                  onPressed: widget.onDismiss,
                  child: const FittedBox(
                    fit: BoxFit.scaleDown,
                    child: Text('I understand', style: TextStyle(fontSize: 24, fontWeight: FontWeight.w900)),
                  ),
                ),
              ),
            ]),
          ),
        ]),
      ),
    );
  }
}

class _VoiceStatus extends StatelessWidget {
  const _VoiceStatus({required this.whisper});
  final WhisperState whisper;

  @override
  Widget build(BuildContext context) {
    final (icon, label, color) = switch (whisper.status) {
      WhisperStatus.playing => (Icons.record_voice_over, 'Speaking the warning…', Colors.white),
      WhisperStatus.done => (Icons.check_circle_outline, 'Voice warning played', Pal.dim),
      WhisperStatus.failed => (Icons.volume_off, 'Voice warning could not play. Please read this screen.', Pal.caution),
      WhisperStatus.stopped => (Icons.stop_circle_outlined, 'Voice warning stopped', Pal.dim),
      WhisperStatus.idle => (Icons.volume_up, 'Read the warning above', Pal.dim),
    };
    final caption = whisper.playing ? whisper.current?.text : null;
    return Column(children: [
      Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(icon, size: 28, color: color),
        const SizedBox(width: 10),
        Flexible(child: Text(label, style: TextStyle(fontSize: 19, fontWeight: FontWeight.w700, color: color))),
      ]),
      if (caption != null && caption.isNotEmpty) ...[
        const SizedBox(height: 8),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(color: Colors.black26, borderRadius: BorderRadius.circular(12)),
          child: Text('🔊 $caption',
              textAlign: TextAlign.center, style: const TextStyle(fontSize: 19, height: 1.35, color: Colors.white)),
        ),
      ],
    ]);
  }
}
