import 'package:flutter/material.dart';

import '../models/verdict.dart';
import '../theme.dart';

/// Phrases highlighted in the caller's words (English + Hindi + Kannada), plus masked OTPs.
final _suspicious = RegExp(
  r'(otp|pin|cvv|password|arrest|warrant|cbi|police|court|narcotics|customs|kyc|aadhaar|money laundering|'
  r'blocked|block|do not tell|don.t tell|tell anyone|do not disconnect|transfer|urgent|immediately|fine|penalty|'
  r'ओटीपी|वारंट|अरेस्ट|गिरफ्तार|किसी को मत|कॉल मत काटिए|खाता|बंद|तुरंत|ट्रांसफर|आधार|मनी लॉन्ड्रिंग|'
  r'ಅರೆಸ್ಟ್|ವಾರಂಟ್|ಬ್ಲಾಕ್|ಯಾರಿಗೂ ಹೇಳಬೇಡಿ|ಕಟ್ ಮಾಡಬೇಡಿ|ತಕ್ಷಣ|ವರ್ಗಾವಣೆ|ಆಧಾರ್|ಮನಿ ಲಾಂಡರಿಂಗ್|•{4,8})',
  caseSensitive: false,
  unicode: true,
);

class TranscriptView extends StatefulWidget {
  const TranscriptView({super.key, required this.lines});
  final List<TranscriptLine> lines;

  @override
  State<TranscriptView> createState() => _TranscriptViewState();
}

class _TranscriptViewState extends State<TranscriptView> {
  final _scroll = ScrollController();
  int _seen = 0;

  @override
  void didUpdateWidget(covariant TranscriptView old) {
    super.didUpdateWidget(old);
    if (widget.lines.length == _seen) return;
    _seen = widget.lines.length;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(
          _scroll.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  List<TextSpan> _spans(String text) {
    final out = <TextSpan>[];
    var i = 0;
    for (final m in _suspicious.allMatches(text)) {
      if (m.start > i) out.add(TextSpan(text: text.substring(i, m.start)));
      out.add(
        TextSpan(
          text: m.group(0),
          style: const TextStyle(
            backgroundColor: Pal.critical,
            fontWeight: FontWeight.w900,
            color: Colors.white,
            decoration: TextDecoration.underline,
            decorationColor: Colors.white,
          ),
        ),
      );
      i = m.end;
    }
    if (i < text.length) out.add(TextSpan(text: text.substring(i)));
    return out;
  }

  @override
  Widget build(BuildContext context) {
    if (widget.lines.isEmpty) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(16),
          child: Text('Listening to the caller…', style: TextStyle(fontSize: 20, color: Pal.dim)),
        ),
      );
    }
    return ListView.separated(
      controller: _scroll,
      padding: const EdgeInsets.all(16),
      itemCount: widget.lines.length,
      separatorBuilder: (_, _) => const SizedBox(height: 14),
      itemBuilder: (_, i) {
        final l = widget.lines[i];
        final last = i == widget.lines.length - 1;
        final you = l.fromVictim;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              you ? 'YOU' : 'CALLER',
              style: TextStyle(
                fontSize: 14,
                letterSpacing: 1.5,
                fontWeight: FontWeight.w900,
                color: you ? Pal.safe : Pal.forPressure(l.pressure),
              ),
            ),
            const SizedBox(height: 2),
            Text.rich(
              TextSpan(children: you ? [TextSpan(text: l.text)] : _spans(l.text)),
              style: TextStyle(fontSize: 21, height: 1.4, color: last ? Pal.text : Pal.dim),
            ),
          ],
        );
      },
    );
  }
}
