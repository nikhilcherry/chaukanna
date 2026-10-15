import 'dart:convert';

import 'package:http/http.dart' as http;

/// Result of the human-confirmed 1930 submission.
class ApprovalOutcome {
  const ApprovalOutcome({required this.ok, required this.route, this.target, this.detail = ''});

  final bool ok;

  /// 'approve_url' | 'webhook' | 'none'
  final String route;
  final Uri? target;
  final String detail;
}

/// Sends the approval (CONTRACTS §3): to n8n's `approve_url` (the HITL Wait
/// node's resume URL) when the incident reply carried one, falling back to the
/// approve-by-call_id webhook if that URL is unusable or fails.
class ApprovalClient {
  ApprovalClient({http.Client? client, required this.webhook, this.timeout = const Duration(seconds: 15)})
      : _client = client ?? http.Client();

  final http.Client _client;
  final String webhook;
  final Duration timeout;

  /// A phone cannot reach the laptop's localhost, so n8n resume URLs built
  /// from a default `http://localhost:5678` base are skipped.
  static bool isReachableUrl(String? url) {
    final u = Uri.tryParse(url?.trim() ?? '');
    if (u == null || !(u.isScheme('https') || u.isScheme('http')) || u.host.isEmpty) return false;
    const local = {'localhost', '127.0.0.1', '0.0.0.0', '::1'};
    return !local.contains(u.host.toLowerCase());
  }

  /// The endpoints that will be tried, in order.
  List<(String, Uri)> routes(String? approveUrl) => [
        if (isReachableUrl(approveUrl)) ('approve_url', Uri.parse(approveUrl!.trim())),
        if (isReachableUrl(webhook) && webhook.trim() != approveUrl?.trim()) ('webhook', Uri.parse(webhook.trim())),
      ];

  Future<ApprovalOutcome> submit(Map<String, dynamic> payload, {String? approveUrl, void Function(String)? log}) async {
    final rs = routes(approveUrl);
    if (rs.isEmpty) return const ApprovalOutcome(ok: false, route: 'none', detail: 'No approval endpoint configured');
    var last = '';
    for (final (route, uri) in rs) {
      try {
        final res = await _client
            .post(uri, headers: const {'Content-Type': 'application/json'}, body: jsonEncode(payload))
            .timeout(timeout);
        if (res.statusCode >= 200 && res.statusCode < 300) {
          log?.call('Approval sent via $route (${uri.host}) HTTP ${res.statusCode}');
          return ApprovalOutcome(ok: true, route: route, target: uri, detail: 'HTTP ${res.statusCode}');
        }
        last = '$route replied HTTP ${res.statusCode}';
      } catch (e) {
        last = '$route failed (${e.runtimeType})';
      }
      log?.call('Approval: $last');
    }
    return ApprovalOutcome(ok: false, route: rs.last.$1, target: rs.last.$2, detail: last);
  }
}
