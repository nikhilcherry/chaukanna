import 'dart:convert';

import 'verdict.dart';

/// LiveKit data topic the bridge publishes on (CONTRACTS §4).
const kGuardianTopic = 'chaukanna.verdict';

/// Messages without a topic are accepted too (older bridge builds, simulator).
bool acceptsTopic(String? topic) => topic == null || topic.isEmpty || topic == kGuardianTopic;

/// Every bridge -> app message (CONTRACTS §4). Unknown types parse to null.
sealed class GuardianMessage {
  const GuardianMessage({required this.callId, this.ts});

  /// Empty when the sender did not include one.
  final String callId;

  /// Unix seconds from the sender, if any.
  final double? ts;
}

class CallStartedMessage extends GuardianMessage {
  const CallStartedMessage({required super.callId, super.ts, this.callerNumber = '', this.knownScammer = false});
  final String callerNumber;
  final bool knownScammer;
}

class VerdictMessage extends GuardianMessage {
  const VerdictMessage({
    required super.callId,
    super.ts,
    required this.verdict,
    this.speaker = 'caller',
    this.chunkText = '',
    this.language = 'en',
    this.pressure = 0,
    this.whisper = false,
    this.whisperClip = 'none',
    this.latencyMs,
    this.legacy = false,
  });

  final Verdict verdict;
  final String speaker;
  final String chunkText;
  final String language;
  final int pressure;

  /// True only when the bridge decided to whisper now (it dedupes and cools down).
  final bool whisper;
  final String whisperClip;
  final int? latencyMs;

  /// Parsed from a bare Verdict with no "type" (old format / simulator).
  final bool legacy;

  /// The clip to play now, or 'none'.
  String get clipToPlay => whisper && whisperClip.isNotEmpty ? whisperClip : 'none';
}

class IncidentMessage extends GuardianMessage {
  const IncidentMessage({required super.callId, super.ts, required this.incident});
  final IncidentInfo incident;
}

class HeartbeatMessage extends GuardianMessage {
  const HeartbeatMessage({required super.callId, super.ts});
}

class CallEndedMessage extends GuardianMessage {
  const CallEndedMessage({required super.callId, super.ts});
}

/// What n8n reported back after the incident branch ran (CONTRACTS §2 reply).
class IncidentInfo {
  const IncidentInfo({
    this.incidentId = '',
    this.callId = '',
    this.knownScammer,
    this.familyAlerted,
    this.evidenceSaved,
    this.blocklisted,
    this.complaintEn = '',
    this.complaintLocal = '',
    this.complaintLanguage = 'en',
    this.familyAlert = '',
    this.approveUrl = '',
  });

  final String incidentId;
  final String callId;

  /// Null = n8n did not say.
  final bool? knownScammer;
  final bool? familyAlerted;
  final bool? evidenceSaved;
  final bool? blocklisted;

  final String complaintEn;
  final String complaintLocal;
  final String complaintLanguage;
  final String familyAlert;
  final String approveUrl;

  bool get hasLocalDraft => complaintLocal.trim().isNotEmpty && complaintLanguage != 'en';

  factory IncidentInfo.fromJson(Map<String, dynamic> j) {
    final draft = j['complaint_draft'];
    var en = '', local = '', lang = 'en';
    if (draft is Map) {
      en = jStr(draft['en']);
      local = jStr(draft['local']);
      lang = normLang(jStr(draft['language'], 'en'));
    } else if (draft is String) {
      en = draft;
    }
    if (en.isEmpty && local.isNotEmpty && lang == 'en') en = local;
    final alert = j['family_alert'];
    return IncidentInfo(
      incidentId: jStr(j['incident_id']),
      callId: jStr(j['call_id']),
      knownScammer: jBoolOrNull(j['known_scammer']),
      familyAlerted: jBoolOrNull(j['family_alerted']),
      evidenceSaved: jBoolOrNull(j['evidence_saved']),
      blocklisted: jBoolOrNull(j['blocklisted']),
      complaintEn: en,
      complaintLocal: local,
      complaintLanguage: lang,
      familyAlert: alert is List ? alert.map((e) => '$e').join('\n') : jStr(alert),
      approveUrl: jStr(j['approve_url']),
    );
  }
}

/// Decodes one data packet. Returns null for malformed JSON, non-objects and
/// unknown message types; callers must simply ignore those.
GuardianMessage? parseGuardianMessage(List<int> bytes) {
  try {
    return parseGuardianJson(jsonDecode(utf8.decode(bytes)));
  } catch (_) {
    return null;
  }
}

GuardianMessage? parseGuardianJson(Object? decoded) {
  if (decoded is! Map) return null;
  final j = decoded.map((k, v) => MapEntry('$k', v));
  final callId = jStr(j['call_id']);
  final ts = j['ts'] is num ? (j['ts'] as num).toDouble() : null;
  final type = j['type'];

  if (type == null) {
    // Bare Verdict (old format / simulator).
    final looksLikeVerdict =
        j.containsKey('pressure') || j.containsKey('scam_type') || j.containsKey('recommended_whisper_clip');
    if (!looksLikeVerdict) return null;
    final v = Verdict.fromJson(j);
    return VerdictMessage(
      callId: callId,
      ts: ts,
      verdict: v,
      speaker: jStr(j['speaker'], 'caller'),
      chunkText: v.transcript,
      language: v.language,
      pressure: v.pressure,
      whisper: v.recommendedWhisperClip != 'none',
      whisperClip: v.recommendedWhisperClip,
      legacy: true,
    );
  }

  switch (type) {
    case 'call_started':
      return CallStartedMessage(
        callId: callId,
        ts: ts,
        callerNumber: jStr(j['caller_number']),
        knownScammer: jBool(j['known_scammer']),
      );
    case 'verdict':
      final inner = j['verdict'];
      final v = Verdict.fromJson(inner is Map ? inner.map((k, v) => MapEntry('$k', v)) : j);
      final clipField = jStr(j['whisper_clip'], 'none');
      final clip = clipField != 'none' ? clipField : v.recommendedWhisperClip;
      final hasWhisperFlag = j['whisper'] is bool;
      return VerdictMessage(
        callId: callId.isNotEmpty ? callId : v.callId,
        ts: ts,
        verdict: v,
        speaker: jStr(j['speaker'], 'caller'),
        chunkText: jStr(j['chunk_text'], v.transcript),
        language: normLang(jStr(j['language'], v.language)),
        pressure: (j.containsKey('pressure') ? jInt(j['pressure']) : v.pressure).clamp(0, 3),
        whisper: (hasWhisperFlag ? j['whisper'] as bool : clip != 'none') && clip != 'none',
        whisperClip: clip,
        latencyMs: j['latency_ms'] is num ? (j['latency_ms'] as num).toInt() : null,
      );
    case 'incident':
      final nested = j['incident'];
      final body = nested is Map ? {...j, ...nested.map((k, v) => MapEntry('$k', v))} : j;
      final info = IncidentInfo.fromJson(body);
      return IncidentMessage(callId: callId.isNotEmpty ? callId : info.callId, ts: ts, incident: info);
    case 'heartbeat':
      return HeartbeatMessage(callId: callId, ts: ts);
    case 'call_ended':
      return CallEndedMessage(callId: callId, ts: ts);
    default:
      return null;
  }
}
