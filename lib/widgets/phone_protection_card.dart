import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/guardian_controller.dart';
import '../theme.dart';

/// Home-screen controls for the phone's ordinary calls: block known scam numbers before they
/// ring (works on its own), and, when a call server is set up, listen to answered calls.
/// Re-reads permissions when the app returns from Settings.
class PhoneProtectionCard extends StatefulWidget {
  const PhoneProtectionCard({super.key});

  @override
  State<PhoneProtectionCard> createState() => _PhoneProtectionCardState();
}

class _PhoneProtectionCardState extends State<PhoneProtectionCard> with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) context.read<GuardianController>().refreshPhonePermissions();
  }

  @override
  Widget build(BuildContext context) {
    final c = context.watch<GuardianController>();
    final listening = c.phoneProtectionOn;
    final extras = c.phonePermissions.missingExtras;
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 14, 8, 14),
      decoration: cardDecoration(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _Row(
            icon: Icons.block,
            on: c.screeningOn,
            title: 'Block known scam numbers',
            subtitle: c.screeningOn ? 'On. Scam numbers never ring.' : 'Off. Known scam numbers will still ring.',
            trailing: c.screeningOn
                ? null
                : Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: FilledButton(
                      style: FilledButton.styleFrom(
                        minimumSize: const Size(0, 44),
                        padding: const EdgeInsets.symmetric(horizontal: 18),
                      ),
                      onPressed: c.turnOnScreening,
                      child: const Text('Turn on'),
                    ),
                  ),
          ),
          if (c.screenedCalls.isNotEmpty) ...[
            const SizedBox(height: 12),
            for (final s in c.screenedCalls.take(3))
              Padding(
                padding: const EdgeInsets.only(bottom: 4, right: 8),
                child: Row(
                  children: [
                    Icon(
                      s.blocked ? Icons.phone_disabled : Icons.warning_amber_rounded,
                      size: 18,
                      color: s.blocked ? Pal.red : Pal.caution,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        '${s.blocked ? 'Blocked' : 'Flagged'} ${s.number}${s.note.isEmpty ? '' : ' (${s.note})'}',
                        style: const TextStyle(fontSize: 15, color: Pal.dim, fontWeight: FontWeight.w600),
                      ),
                    ),
                  ],
                ),
              ),
          ],
          if (c.phoneTapAvailable) ...[
            const SizedBox(height: 12),
            const Divider(height: 1, color: Pal.line),
            const SizedBox(height: 12),
            _Row(
              icon: Icons.phone_in_talk,
              on: listening,
              title: 'Listen to my phone calls',
              subtitle: listening
                  ? 'On. Answer calls on speaker so Chaukanna can hear.'
                  : 'Off. Only calls inside Chaukanna are watched.',
              trailing: Switch(value: listening, onChanged: c.setPhoneProtection),
            ),
            if (listening && extras.isNotEmpty) ...[
              const SizedBox(height: 10),
              Padding(
                padding: const EdgeInsets.only(right: 8),
                child: Text(
                  'Also allow ${extras.join(', ')}.',
                  style: const TextStyle(fontSize: 15, color: Pal.caution, fontWeight: FontWeight.w600),
                ),
              ),
              if (!c.phonePermissions.overlay)
                TextButton(onPressed: c.allowOverDialer, child: const Text('Allow warnings over calls')),
            ],
          ],
        ],
      ),
    );
  }
}

class _Row extends StatelessWidget {
  const _Row({required this.icon, required this.on, required this.title, required this.subtitle, this.trailing});
  final IconData icon;
  final bool on;
  final String title;
  final String subtitle;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Container(
          width: 48,
          height: 48,
          decoration: BoxDecoration(color: on ? Pal.brand : Pal.cardHi, borderRadius: BorderRadius.circular(16)),
          child: Icon(icon, color: on ? Colors.white : Pal.dim, size: 26),
        ),
        const SizedBox(width: 14),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: display(19, color: Pal.ink)),
              const SizedBox(height: 2),
              Text(
                subtitle,
                style: const TextStyle(fontSize: 15, height: 1.3, color: Pal.dim, fontWeight: FontWeight.w500),
              ),
            ],
          ),
        ),
        ?trailing,
      ],
    );
  }
}
