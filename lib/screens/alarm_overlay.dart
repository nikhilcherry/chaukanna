import 'package:flutter/material.dart';

import '../models/verdict.dart';
import '../theme.dart';

const _warnings = <String, Map<String, String>>{
  'warn_otp': {
    'en': 'STOP! Do NOT share your OTP or PIN!',
    'hi': 'रुकिए! OTP या PIN किसी को न बताएं!',
    'kn': 'ನಿಲ್ಲಿ! OTP ಅಥವಾ PIN ಯಾರಿಗೂ ಹೇಳಬೇಡಿ!',
  },
  'warn_digital_arrest': {
    'en': 'SCAM! No police arrest over phone. Hang up!',
    'hi': 'धोखा! फोन पर कोई गिरफ्तारी नहीं होती। कॉल काटें!',
    'kn': 'ವಂಚನೆ! ಫೋನ್‌ನಲ್ಲಿ ಯಾವುದೇ ಅರೆಸ್ಟ್ ಇಲ್ಲ. ಕರೆ ಕಟ್ ಮಾಡಿ!',
  },
  'warn_secrecy': {
    'en': 'DANGER! Tell your family right now!',
    'hi': 'खतरा! अभी अपने परिवार को बताएं!',
    'kn': 'ಅಪಾಯ! ಈಗಲೇ ಕುಟುಂಬಕ್ಕೆ ತಿಳಿಸಿ!',
  },
  'warn_known_scammer': {
    'en': 'KNOWN SCAMMER! Call blocked.',
    'hi': 'जाना-पहचाना ठग! कॉल ब्लॉक की गई।',
    'kn': 'ಗೊತ್ತಿರುವ ವಂಚಕ! ಕರೆ ನಿರ್ಬಂಧಿಸಲಾಗಿದೆ.',
  },
};

const _generic = {
  'en': 'DANGER! This call looks like a scam!',
  'hi': 'खतरा! यह कॉल धोखा हो सकती है!',
  'kn': 'ಅಪಾಯ! ಈ ಕರೆ ವಂಚನೆ ಆಗಿರಬಹುದು!',
};

String _warningFor(Verdict v, String lang) {
  final m = _warnings[v.recommendedWhisperClip] ?? _generic;
  return m[lang] ?? m['en']!;
}

/// Screen 2: pulsing crimson border, giant bilingual warning, whisper plays
/// from the controller.
class AlarmOverlay extends StatefulWidget {
  final Verdict verdict;
  final bool whisperPlaying;
  final VoidCallback onDismiss;
  const AlarmOverlay(
      {super.key, required this.verdict, required this.whisperPlaying, required this.onDismiss});

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
    final v = widget.verdict;
    final lang = v.language;
    final english = _warningFor(v, 'en');
    final local = lang == 'en' ? null : _warningFor(v, lang);
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
        child: Padding(
          padding: const EdgeInsets.all(28),
          child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
            const Icon(Icons.warning_amber_rounded, size: 96, color: Colors.white),
            const SizedBox(height: 16),
            Semantics(
              liveRegion: true,
              child: Text(english,
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontSize: 40, fontWeight: FontWeight.w900, height: 1.15)),
            ),
            if (local != null) ...[
              const SizedBox(height: 24),
              Text(local,
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                      fontSize: 38, fontWeight: FontWeight.w900, height: 1.25, color: Color(0xFFFFD6DD))),
            ],
            const SizedBox(height: 28),
            AnimatedOpacity(
              opacity: widget.whisperPlaying ? 1 : 0.4,
              duration: const Duration(milliseconds: 250),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                const Icon(Icons.record_voice_over, size: 28),
                const SizedBox(width: 10),
                Text(widget.whisperPlaying ? 'Playing voice warning…' : 'Voice warning',
                    style: const TextStyle(fontSize: 18, color: Pal.dim)),
              ]),
            ),
            const SizedBox(height: 36),
            SizedBox(
              width: double.infinity,
              height: 72,
              child: FilledButton(
                style: FilledButton.styleFrom(backgroundColor: Colors.white, foregroundColor: Pal.crimson),
                onPressed: widget.onDismiss,
                child: const Text('I understand', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w900)),
              ),
            ),
          ]),
        ),
      ),
    );
  }
}
