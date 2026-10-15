import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/guardian_controller.dart';
import '../theme.dart';

const _langNames = {'hi': 'हिन्दी', 'kn': 'ಕನ್ನಡ', 'en': 'English'};

/// Screen 3: what n8n already did + human-in-the-loop 1930 approval.
/// Only reached after a high-risk call; low-risk calls reset to idle.
class PostCallScreen extends StatelessWidget {
  const PostCallScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final c = context.watch<GuardianController>();
    final i = c.incident;
    final waiting = c.waitingForIncident;
    _Status st(bool? done) => i == null
        ? (waiting ? _Status.waiting : _Status.unconfirmed)
        : (done == true ? _Status.done : _Status.unconfirmed);

    return SafeArea(
      child: ListView(padding: const EdgeInsets.fromLTRB(20, 20, 20, 28), children: [
        Row(children: [
          Icon(c.knownScammer ? Icons.block : Icons.shield, size: 46, color: Pal.high),
          const SizedBox(width: 12),
          Expanded(
            child: Text(c.knownScammer ? 'Scam call blocked.' : 'Call ended. You were protected.',
                style: const TextStyle(fontSize: 29, fontWeight: FontWeight.w900, height: 1.15)),
          ),
        ]),
        const SizedBox(height: 8),
        Text(
            '${c.callerNumber}${c.callerLabel.isNotEmpty ? ' (said: ${c.callerLabel})' : ''} · ${mmss(c.elapsed)}'
            '${c.endReason.isNotEmpty ? '\n${c.endReason}' : ''}',
            style: const TextStyle(fontSize: 18, color: Pal.dim, height: 1.35)),
        if (c.simulated)
          const Padding(
            padding: EdgeInsets.only(top: 6),
            child: Text('SIMULATED CALL', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w900, color: Pal.caution)),
          ),
        const SizedBox(height: 22),
        const _Header('Already done for you'),
        if (waiting)
          const Padding(
            padding: EdgeInsets.only(bottom: 10),
            child: Row(children: [
              SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 3)),
              SizedBox(width: 12),
              Expanded(child: Text('Waiting for the response team…', style: TextStyle(fontSize: 18, color: Pal.dim))),
            ]),
          ),
        _StepRow(st(i?.familyAlerted), 'Family alerted', c.familySummary),
        _StepRow(
          st(i?.evidenceSaved),
          'Call evidence and timestamps saved',
          '${c.evidence.length} flagged moments recorded.'
              '${c.evidence.isEmpty ? '' : '\n${c.evidence.take(3).map((e) => e.format()).join('\n')}'}',
        ),
        _StepRow(st(i?.blocklisted), 'Number added to shared blocklist',
            '${c.callerNumber} will be flagged for everyone using Chaukanna.'),
        const SizedBox(height: 22),
        const _Header('Complaint to 1930 / cybercrime.gov.in'),
        _Complaint(c: c),
        const SizedBox(height: 8),
        Text(
          c.complaintFromN8n
              ? 'Drafted by Chaukanna AI. Nothing is sent until you confirm.'
              : (waiting
                  ? 'Draft made on this phone. The AI draft will replace it when it arrives.'
                  : 'Draft made on this phone. Nothing is sent until you confirm.'),
          style: const TextStyle(fontSize: 17, color: Pal.dim),
        ),
        const SizedBox(height: 16),
        _SubmitArea(c: c),
        const SizedBox(height: 24),
        OutlinedButton(
          onPressed: c.finishPostCall,
          style: OutlinedButton.styleFrom(
              minimumSize: const Size.fromHeight(64), side: const BorderSide(color: Colors.white54, width: 2)),
          child: const Text('Done', style: TextStyle(fontSize: 22, color: Colors.white)),
        ),
      ]),
    );
  }
}

enum _Status { done, waiting, unconfirmed }

class _Header extends StatelessWidget {
  const _Header(this.text);
  final String text;
  @override
  Widget build(BuildContext context) => Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Text(text.toUpperCase(),
          style: const TextStyle(fontSize: 16, letterSpacing: 1.5, fontWeight: FontWeight.w800, color: Pal.dim)));
}

class _StepRow extends StatelessWidget {
  const _StepRow(this.status, this.title, this.detail);
  final _Status status;
  final String title;
  final String detail;

  @override
  Widget build(BuildContext context) {
    final (icon, word, color) = switch (status) {
      _Status.done => (Icons.check_circle, 'Done', Pal.safe),
      _Status.waiting => (Icons.hourglass_top, 'Waiting', Pal.caution),
      _Status.unconfirmed => (Icons.help_outline, 'Not confirmed', Pal.caution),
    };
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
          color: Pal.card, borderRadius: BorderRadius.circular(16), border: Border.all(color: color.withValues(alpha: 0.6), width: 2)),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Icon(icon, size: 30, color: color),
        const SizedBox(width: 12),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('$title: $word', style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
            const SizedBox(height: 4),
            Text(detail, style: const TextStyle(fontSize: 17, color: Pal.dim, height: 1.35)),
          ]),
        ),
      ]),
    );
  }
}

/// The draft in the call language first (when n8n wrote one), with English one tap away.
class _Complaint extends StatefulWidget {
  const _Complaint({required this.c});
  final GuardianController c;
  @override
  State<_Complaint> createState() => _ComplaintState();
}

class _ComplaintState extends State<_Complaint> {
  bool _english = false;

  @override
  Widget build(BuildContext context) {
    final c = widget.c;
    final local = c.complaintLocal;
    final showEnglish = local == null || _english;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      if (local != null)
        Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: SegmentedButton<bool>(
            style: SegmentedButton.styleFrom(minimumSize: const Size(0, 52), textStyle: const TextStyle(fontSize: 19)),
            segments: [
              ButtonSegment(value: false, label: Text(_langNames[c.complaintLocalLang] ?? c.complaintLocalLang)),
              const ButtonSegment(value: true, label: Text('English')),
            ],
            selected: {_english},
            onSelectionChanged: (s) => setState(() => _english = s.first),
          ),
        ),
      Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(color: Pal.card, borderRadius: BorderRadius.circular(16)),
        child: SelectableText(showEnglish ? c.complaintEnglish : local,
            style: const TextStyle(fontSize: 18, height: 1.5)),
      ),
    ]);
  }
}

class _SubmitArea extends StatelessWidget {
  const _SubmitArea({required this.c});
  final GuardianController c;

  Future<void> _confirm(BuildContext context) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Send this report to 1930?', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w800)),
        content: const Text('This files an official police complaint. It cannot be undone.',
            style: TextStyle(fontSize: 20, height: 1.35)),
        actionsPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel', style: TextStyle(fontSize: 21))),
          FilledButton(
              style: FilledButton.styleFrom(backgroundColor: Pal.critical, foregroundColor: Colors.white),
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Yes, send it', style: TextStyle(fontSize: 21, fontWeight: FontWeight.w800))),
        ],
      ),
    );
    if (ok == true) await c.submit1930();
  }

  @override
  Widget build(BuildContext context) {
    final s = c.submitState;
    final done = s == SubmitState.done;
    return Column(children: [
      SizedBox(
        width: double.infinity,
        height: 78,
        child: FilledButton.icon(
          style: FilledButton.styleFrom(
            backgroundColor: done ? Pal.safe : Pal.critical,
            foregroundColor: done ? Colors.black : Colors.white,
            disabledBackgroundColor: done ? Pal.safe : Colors.grey.shade800,
            disabledForegroundColor: done ? Colors.black : Colors.white70,
          ),
          onPressed: s == SubmitState.idle || s == SubmitState.failed ? () => _confirm(context) : null,
          icon: s == SubmitState.submitting
              ? const SizedBox(width: 26, height: 26, child: CircularProgressIndicator(strokeWidth: 3, color: Colors.white))
              : Icon(done ? Icons.check_circle : Icons.gavel, size: 30),
          label: Text(
              done
                  ? 'Report Submitted'
                  : s == SubmitState.submitting
                      ? 'Sending…'
                      : s == SubmitState.failed
                          ? 'Try again: Submit 1930 Report'
                          : 'Confirm & Submit 1930 Report',
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w900)),
        ),
      ),
      if (c.submitMessage.isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(top: 10),
          child: Text(c.submitMessage,
              textAlign: TextAlign.center,
              style: TextStyle(
                  fontSize: 18, color: s == SubmitState.failed ? Pal.caution : Pal.dim, fontWeight: FontWeight.w600)),
        ),
    ]);
  }
}
