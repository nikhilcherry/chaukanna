import 'package:flutter/material.dart';

import '../models/verdict.dart';
import '../theme.dart';

class VerdictChips extends StatelessWidget {
  final Verdict verdict;
  const VerdictChips({super.key, required this.verdict});

  @override
  Widget build(BuildContext context) {
    return Wrap(spacing: 10, runSpacing: 10, alignment: WrapAlignment.center, children: [
      _Chip(
          on: verdict.isScam,
          text: verdict.isScam ? '🚨 ${verdict.scamLabel}' : '🛡️ No scam detected',
          color: Pal.critical,
          offColor: Pal.safe),
      _Chip(on: verdict.asksOtpOrPin, text: '⚠️ Asking for OTP/PIN', color: Pal.high),
      _Chip(on: verdict.demandsSecrecy, text: '🔒 Isolation Attempt Detected', color: Pal.critical),
    ]);
  }
}

class _Chip extends StatelessWidget {
  final bool on;
  final String text;
  final Color color;
  final Color? offColor;
  const _Chip({required this.on, required this.text, required this.color, this.offColor});

  @override
  Widget build(BuildContext context) {
    // Inactive attention chips stay hidden-ish (dim) so lit ones pop.
    final c = on ? color : (offColor ?? Pal.dim);
    final lit = on || offColor != null;
    return AnimatedContainer(
      duration: const Duration(milliseconds: 350),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(
        color: on ? color : Colors.transparent,
        border: Border.all(color: lit ? c : Pal.dim.withValues(alpha: 0.3), width: 2),
        borderRadius: BorderRadius.circular(30),
        boxShadow: on ? [BoxShadow(color: color.withValues(alpha: 0.6), blurRadius: 16)] : null,
      ),
      child: Text(text,
          style: TextStyle(
              fontSize: 17,
              fontWeight: FontWeight.w800,
              color: on ? Colors.white : (lit ? c : Pal.dim.withValues(alpha: 0.5)))),
    );
  }
}
