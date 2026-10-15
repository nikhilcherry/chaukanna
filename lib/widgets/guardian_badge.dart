import 'package:flutter/material.dart';

import '../state/guardian_controller.dart';
import '../theme.dart';

/// "Protected" pill driven by bridge heartbeats (greys out after 15 s of silence).
/// The state is spelled out in words, never only in colour.
class GuardianBadge extends StatelessWidget {
  const GuardianBadge({super.key, required this.status});
  final GuardianStatus status;

  @override
  Widget build(BuildContext context) {
    final (icon, text, color, filled) = switch (status) {
      GuardianStatus.protected => (Icons.verified_user, 'Protected', Pal.safe, true),
      GuardianStatus.stale => (Icons.shield_outlined, 'Guardian not responding', Pal.grey, false),
      GuardianStatus.waiting => (Icons.hourglass_top, 'Connecting to guardian…', Pal.grey, false),
      GuardianStatus.offline => (Icons.cloud_off, 'Offline demo mode', Pal.grey, false),
    };
    final fg = filled ? Pal.onColor(color) : Pal.dim;
    return Semantics(
      liveRegion: true,
      label: 'Guardian status: $text',
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 300),
        constraints: const BoxConstraints(minHeight: 40),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
        decoration: BoxDecoration(
          color: filled ? color : Colors.transparent,
          borderRadius: BorderRadius.circular(24),
          border: Border.all(color: filled ? color : Pal.grey, width: 2),
        ),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(icon, size: 22, color: fg),
          const SizedBox(width: 8),
          Flexible(
            child: Text(text,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: fg)),
          ),
        ]),
      ),
    );
  }
}
