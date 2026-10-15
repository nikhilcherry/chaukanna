import 'package:flutter/material.dart';

import '../models/verdict.dart';
import '../theme.dart';

/// Live verdict chips. The scam chip changes its words and icon when it lights
/// up, so the meaning never depends on colour alone.
class VerdictChips extends StatelessWidget {
  const VerdictChips({
    super.key,
    required this.scamType,
    required this.asksOtp,
    required this.secrecy,
    required this.knownScammer,
  });

  final String scamType;
  final bool asksOtp;
  final bool secrecy;
  final bool knownScammer;

  @override
  Widget build(BuildContext context) {
    final scam = scamType != 'none' && scamType.isNotEmpty;
    return Wrap(spacing: 10, runSpacing: 10, alignment: WrapAlignment.center, children: [
      if (knownScammer) const _Chip(on: true, text: '⛔ Known scammer number', color: Pal.crimson),
      _Chip(
        on: scam,
        text: scam ? '🚨 ${scamLabelFor(scamType)}' : '✓ No scam detected',
        color: Pal.critical,
      ),
      // Warning chips appear only when they light up: less to read for an elder,
      // and the appearance itself is the signal (with words, not just colour).
      if (asksOtp) const _Chip(on: true, text: '⚠️ Asking for OTP/PIN', color: Pal.high),
      if (secrecy) const _Chip(on: true, text: '🔒 Isolation attempt', color: Pal.critical),
    ]);
  }
}

class _Chip extends StatelessWidget {
  const _Chip({required this.on, required this.text, required this.color});
  final bool on;
  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return AnimatedContainer(
      duration: const Duration(milliseconds: 350),
      constraints: const BoxConstraints(minHeight: 48),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      decoration: BoxDecoration(
        color: on ? color : Colors.transparent,
        border: Border.all(color: on ? color : Pal.grey.withValues(alpha: 0.6), width: 2),
        borderRadius: BorderRadius.circular(30),
        boxShadow: on ? [BoxShadow(color: color.withValues(alpha: 0.55), blurRadius: 16)] : null,
      ),
      child: Text(text,
          style: TextStyle(
            fontSize: on ? 19 : 17,
            fontWeight: on ? FontWeight.w900 : FontWeight.w600,
            color: on ? Pal.onColor(color) : Pal.dim,
          )),
    );
  }
}
