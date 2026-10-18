import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../config.dart';

/// Stage demo only: asks the laptop to have the AI scammer call this phone now.
///
/// The bridge's token_server.py answers POST /console/api/live: it starts whatever part of the
/// system is down, then tools/ai_scammer.py joins the room as the caller. The console API answers on the
/// laptop only, which is why the phone reaches it through `adb reverse tcp:8787 tcp:8787`.
class StageClient {
  StageClient({String? baseUrl, http.Client? client})
    : _base = baseUrl ?? AppConfig.stageUrl,
      _client = client ?? http.Client();

  final String _base;
  final http.Client _client;

  bool get available => _base.isNotEmpty;

  /// Null when the call is on its way; otherwise what went wrong, in words for the screen.
  Future<String?> startLiveCall(String lang) async {
    final uri = Uri.parse('${_base.replaceFirst(RegExp(r'/+$'), '')}/console/api/live');
    try {
      final res = await _client
          .post(uri, headers: {'Content-Type': 'application/json'}, body: jsonEncode({'lang': lang}))
          .timeout(const Duration(seconds: 8));
      if (res.statusCode == 200) return null;
      try {
        final err = (jsonDecode(res.body) as Map<String, dynamic>)['error'];
        if (err is String && err.isNotEmpty) return err;
      } catch (_) {}
      return 'The laptop replied HTTP ${res.statusCode}';
    } on TimeoutException {
      return 'The laptop did not answer. Is the phone on USB with adb reverse?';
    } catch (_) {
      return 'Cannot reach the laptop. Is the phone on USB with adb reverse?';
    }
  }
}
