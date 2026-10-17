import 'package:flutter/material.dart';

import '../state/guardian_controller.dart';
import '../theme.dart';

/// Status pill from the bridge heartbeat (greys out after 15 s of silence).
/// The state is spelled out in words, never only in colour.
class GuardianBadge extends StatelessWidget {
  const GuardianBadge({super.key, required this.status});
  final GuardianStatus status;

  @override
  Widget build(BuildContext context) {
    final (icon, text) = switch (status) {
      GuardianStatus.protected => (Icons.verified_user, 'Protected'),
      GuardianStatus.stale => (Icons.shield_outlined, 'Guardian not responding'),
      GuardianStatus.waiting => (Icons.hourglass_top, 'Connecting to guardian…'),
      GuardianStatus.offline => (Icons.cloud_off, 'Offline demo mode'),
    };
    final on = status == GuardianStatus.protected;
    final fg = on ? Pal.brand : Pal.dim;
    return Semantics(
      liveRegion: true,
      label: 'Guardian status: $text',
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 300),
        constraints: const BoxConstraints(minHeight: 38),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          color: on ? Pal.paper : Pal.cardHi,
          borderRadius: BorderRadius.circular(20),
          boxShadow: on ? kSoftShadow : null,
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 20, color: fg),
            const SizedBox(width: 7),
            Flexible(
              child: Text(
                text,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: fg),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
