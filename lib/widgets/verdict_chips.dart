import 'package:flutter/material.dart';

import '../models/scam_profile.dart';
import '../theme.dart';

/// The live "what kind of call is this" block. With no scam it is one calm line.
/// Once the call is clearly a scam (pressure 2, when the warnings start) or the number is a
/// known scammer, it becomes a card in that type's colour and icon that says what the scam
/// is and what to do, followed by a small pill for each specific danger (OTP, secrecy, known
/// number). Below pressure 2 the classifier's early guess at a type stays off the screen: a
/// courier saying hello must not be called a scam.
class VerdictChips extends StatelessWidget {
  const VerdictChips({
    super.key,
    required this.scamType,
    required this.asksOtp,
    required this.secrecy,
    required this.knownScammer,
    required this.pressure,
  });

  final String scamType;
  final bool asksOtp;
  final bool secrecy;
  final bool knownScammer;

  /// The call's peak pressure, 0..3.
  final int pressure;

  @override
  Widget build(BuildContext context) {
    final clear = pressure >= 2 || knownScammer;
    final scam = scamType != 'none' && scamType.isNotEmpty && clear;
    final main = scam || knownScammer ? ScamProfile.resolve(scamType: scamType, knownScammer: knownScammer) : null;
    final asksOtp = this.asksOtp && clear;
    final secrecy = this.secrecy && clear;
    final watching = pressure >= 1;
    return AnimatedSize(
      duration: const Duration(milliseconds: 250),
      alignment: Alignment.topCenter,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (main == null && !asksOtp && !secrecy)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 6),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(
                      watching ? Icons.visibility : Icons.check_circle,
                      size: 22,
                      color: watching ? Pal.amber : Pal.brand,
                    ),
                    const SizedBox(width: 8),
                    Flexible(
                      child: Text(
                        watching ? 'Listening closely. No scam so far' : 'No scam signs so far',
                        style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600, color: Pal.dim),
                      ),
                    ),
                  ],
                ),
              ),
            if (main != null) _TypeCard(profile: main),
            if ((main != null && knownScammer && scam) || asksOtp || secrecy) ...[
              const SizedBox(height: 10),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  if (main != null && knownScammer && scam)
                    const _Pill(profile: ScamProfile.known, text: 'This number is a known scammer'),
                  if (asksOtp) const _Pill(profile: ScamProfile.otp, text: 'Asking for your OTP or PIN'),
                  if (secrecy) const _Pill(profile: ScamProfile.secrecy, text: 'Told to keep this secret'),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _TypeCard extends StatelessWidget {
  const _TypeCard({required this.profile});
  final ScamProfile profile;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: cardDecoration(),
      child: Row(
        children: [
          Container(
            width: 56,
            height: 56,
            decoration: BoxDecoration(color: profile.field, borderRadius: BorderRadius.circular(18)),
            child: Icon(profile.icon, size: 30, color: profile.onField),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(profile.label, style: display(21, color: Pal.ink)),
                const SizedBox(height: 3),
                Text(
                  profile.action,
                  style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600, height: 1.3, color: Pal.dim),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _Pill extends StatelessWidget {
  const _Pill({required this.profile, required this.text});
  final ScamProfile profile;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      constraints: const BoxConstraints(minHeight: 40),
      padding: const EdgeInsets.fromLTRB(6, 5, 14, 5),
      decoration: cardDecoration(radius: 24),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 30,
            height: 30,
            decoration: BoxDecoration(color: profile.field, shape: BoxShape.circle),
            child: Icon(profile.icon, size: 17, color: profile.onField),
          ),
          const SizedBox(width: 8),
          Flexible(
            child: Text(
              text,
              style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: Pal.ink),
            ),
          ),
        ],
      ),
    );
  }
}
