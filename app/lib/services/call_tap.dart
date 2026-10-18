import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:livekit_client/livekit_client.dart';

import '../config.dart';

/// Feeds an ordinary phone call to the guardian.
///
/// Android will not hand an app the call audio, so with the phone on loudspeaker its
/// microphone hears the caller. This joins the guardian's room as a second participant,
/// `caller-phone`, and publishes that microphone. The bridge treats it like any caller:
/// transcribe, classify, send the verdicts to the victim connection.
class CallTap {
  CallTap({required this.log, Future<({String url, String token})> Function(String number)? credentials})
    : _credentials = credentials;

  final void Function(String message, {bool important}) log;
  final Future<({String url, String token})> Function(String number)? _credentials;

  Room? _room;
  bool _micOn = true;
  bool get active => _room != null;

  Future<({String url, String token})> _fetch(String number) async {
    final custom = _credentials;
    if (custom != null) return custom(number);
    final base = AppConfig.callerTokenUrl;
    final sep = base.contains('?') ? '&' : '?';
    final uri = Uri.parse(
      '$base${sep}identity=caller-phone&name=${Uri.encodeComponent('Phone call')}&phone=${Uri.encodeComponent(number)}',
    );
    final res = await http.get(uri).timeout(const Duration(seconds: 8));
    if (res.statusCode != 200) throw Exception('caller token URL replied HTTP ${res.statusCode}');
    final j = jsonDecode(res.body) as Map<String, dynamic>;
    final url = (j['url'] as String?)?.isNotEmpty == true ? j['url'] as String : AppConfig.livekitUrl;
    return (url: url, token: j['token'] as String);
  }

  Future<void> start(String number) async {
    if (_room != null) return;
    try {
      final creds = await _fetch(number);
      final room = Room(roomOptions: const RoomOptions(adaptiveStream: false, dynacast: false));
      _room = room;
      await room.connect(creds.url, creds.token);
      await room.localParticipant?.setMicrophoneEnabled(_micOn);
      log('Phone call tapped: listening through the microphone as "caller-phone"');
    } catch (e) {
      log('Could not start listening to the phone call: $e', important: true);
      await stop();
    }
  }

  /// Mute while a warning plays, so the caller's side of the room does not hear it twice.
  Future<void> setMicEnabled(bool on) async {
    _micOn = on;
    try {
      await _room?.localParticipant?.setMicrophoneEnabled(on);
    } catch (e) {
      log('Phone tap mic switch failed: $e');
    }
  }

  Future<void> stop() async {
    final room = _room;
    _room = null;
    _micOn = true;
    try {
      await room?.disconnect();
    } catch (_) {}
    try {
      await room?.dispose();
    } catch (_) {}
  }
}
