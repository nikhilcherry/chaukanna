import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/guardian_controller.dart';
import '../theme.dart';

/// Screen 3: what n8n already did + human-in-the-loop 1930 approval.
class PostCallScreen extends StatelessWidget {
  const PostCallScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final c = context.watch<GuardianController>();
    final high = c.highRiskCall;
    return SafeArea(
      child: ListView(padding: const EdgeInsets.all(20), children: [
        Row(children: [
          Icon(high ? Icons.shield : Icons.check_circle, size: 44, color: high ? Pal.high : Pal.safe),
          const SizedBox(width: 12),
          Expanded(
              child: Text(high ? 'Call ended. You were protected.' : 'Call ended. No scam found.',
                  style: const TextStyle(fontSize: 28, fontWeight: FontWeight.w900, height: 1.15))),
        ]),
        const SizedBox(height: 6),
        Text('${c.callerNumber}${c.knownScammerBlocked ? ' · auto-blocked' : ''}',
            style: const TextStyle(fontSize: 18, color: Pal.dim)),
        if (high) ...[
          const SizedBox(height: 22),
          const _Header('Already done for you'),
          _Done('Family Alerted', c.familySummary),
          _Done('Call Evidence & Timestamps Saved',
              '${c.evidenceTimestamps.length} flagged moments recorded.\n${c.evidenceTimestamps.take(3).join('\n')}'),
          _Done('Number Added to Shared Blocklist',
              '${c.callerNumber} will now be flagged for everyone using Chaukanna.'),
          const SizedBox(height: 22),
          const _Header('Complaint to 1930 / cybercrime.gov.in'),
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(color: Pal.card, borderRadius: BorderRadius.circular(16)),
            child: SelectableText(c.complaintDraft, style: const TextStyle(fontSize: 17, height: 1.45)),
          ),
          const SizedBox(height: 8),
          const Text('Drafted by AI. Nothing is sent until you confirm.',
              style: TextStyle(fontSize: 15, color: Pal.dim)),
          const SizedBox(height: 16),
          _SubmitArea(c: c),
        ] else
          const Padding(
            padding: EdgeInsets.only(top: 24),
            child: Text('Nothing suspicious happened, so no action is needed.',
                style: TextStyle(fontSize: 20, color: Pal.dim)),
          ),
        const SizedBox(height: 24),
        OutlinedButton(
          onPressed: c.resetToIdle,
          style: OutlinedButton.styleFrom(
              minimumSize: const Size.fromHeight(60), side: const BorderSide(color: Colors.white38)),
          child: const Text('Done', style: TextStyle(fontSize: 22, color: Colors.white)),
        ),
      ]),
    );
  }
}

class _Header extends StatelessWidget {
  final String text;
  const _Header(this.text);
  @override
  Widget build(BuildContext context) => Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Text(text.toUpperCase(),
          style: const TextStyle(fontSize: 15, letterSpacing: 1.5, fontWeight: FontWeight.w800, color: Pal.dim)));
}

class _Done extends StatelessWidget {
  final String title;
  final String detail;
  const _Done(this.title, this.detail);
  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
            color: Pal.card,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: Pal.safe.withValues(alpha: 0.5))),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('✅', style: TextStyle(fontSize: 24)),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(title, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
              const SizedBox(height: 4),
              Text(detail, style: const TextStyle(fontSize: 16, color: Pal.dim, height: 1.35)),
            ]),
          ),
        ]),
      );
}

class _SubmitArea extends StatelessWidget {
  final GuardianController c;
  const _SubmitArea({required this.c});

  Future<void> _confirm(BuildContext context) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: Pal.card,
        title: const Text('Send this report?', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w800)),
        content: const Text('This files an official complaint and cannot be undone.',
            style: TextStyle(fontSize: 19)),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel', style: TextStyle(fontSize: 20))),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Yes, send', style: TextStyle(fontSize: 20))),
        ],
      ),
    );
    if (ok == true) c.submit1930();
  }

  @override
  Widget build(BuildContext context) {
    final s = c.submitState;
    return Column(children: [
      SizedBox(
        width: double.infinity,
        height: 76,
        child: FilledButton.icon(
          style: FilledButton.styleFrom(
              backgroundColor: s == SubmitState.done ? Pal.safe : Pal.critical,
              disabledBackgroundColor: s == SubmitState.done ? Pal.safe : Colors.grey.shade800),
          onPressed: s == SubmitState.idle || s == SubmitState.failed ? () => _confirm(context) : null,
          icon: s == SubmitState.submitting
              ? const SizedBox(width: 26, height: 26, child: CircularProgressIndicator(strokeWidth: 3, color: Colors.white))
              : Icon(s == SubmitState.done ? Icons.check_circle : Icons.gavel, size: 30),
          label: Text(
              s == SubmitState.done
                  ? 'Report Submitted'
                  : s == SubmitState.submitting
                      ? 'Sending…'
                      : 'Confirm & Submit 1930 Report',
              style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w900)),
        ),
      ),
      if (c.submitMessage.isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(top: 10),
          child: Text(c.submitMessage,
              textAlign: TextAlign.center,
              style: TextStyle(
                  fontSize: 17, color: s == SubmitState.failed ? Pal.high : Pal.dim, fontWeight: FontWeight.w600)),
        ),
    ]);
  }
}
