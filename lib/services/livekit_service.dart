import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:livekit_client/livekit_client.dart';

import '../config.dart';

enum LinkState { off, connecting, connected, reconnecting, failed }

class CallerInfo {
  const CallerInfo(this.identity, this.number);
  final String identity;
  final String number;
}

/// Persistent LiveKit room connection for the victim phone.
///
/// The app stays in the room between calls so it never misses a late n8n
/// incident message, and it reconnects with backoff if the room drops. Mic and
/// remote audio are switched per call rather than by leaving the room.
class LiveKitTransport {
  LiveKitTransport({required this.onData, required this.onCallerJoined, required this.onCallerLeft, required this.log});

  static const guardianIdentity = 'chaukanna-guardian';

  final void Function(List<int> data, String? topic) onData;
  final void Function(CallerInfo caller) onCallerJoined;
  final void Function(String identity) onCallerLeft;
  final void Function(String message, {bool important}) log;

  final ValueNotifier<LinkState> state = ValueNotifier(LinkState.off);

  Room? _room;
  EventsListener<RoomEvent>? _listener;
  Timer? _retry;
  int _attempt = 0;
  bool _disposed = false;
  bool _micOn = false;
  bool _remoteAudioOn = true;
  bool _speaker = AppConfig.speakerByDefault;

  String get roomName => _room?.name ?? '';

  static bool isCaller(String identity) =>
      identity.isNotEmpty && identity != guardianIdentity && identity != AppConfig.victimIdentity;

  Future<void> start() async {
    if (!AppConfig.liveKitConfigured) {
      state.value = LinkState.off;
      return;
    }
    await _connect();
  }

  Future<({String url, String token})> _credentials() async {
    if (AppConfig.livekitTokenUrl.isNotEmpty) {
      final res = await http.get(Uri.parse(AppConfig.livekitTokenUrl)).timeout(const Duration(seconds: 10));
      if (res.statusCode != 200) throw Exception('token URL replied HTTP ${res.statusCode}');
      final j = jsonDecode(res.body) as Map<String, dynamic>;
      final url = (j['url'] as String?)?.isNotEmpty == true ? j['url'] as String : AppConfig.livekitUrl;
      return (url: url, token: j['token'] as String);
    }
    return (url: AppConfig.livekitUrl, token: AppConfig.livekitToken);
  }

  Future<void> _connect() async {
    if (_disposed) return;
    state.value = _attempt == 0 ? LinkState.connecting : LinkState.reconnecting;
    try {
      final creds = await _credentials();
      _describeToken(creds.token);
      final room = Room(roomOptions: const RoomOptions(adaptiveStream: false, dynacast: false));
      _room = room;
      _listener = room.createListener()
        ..on<DataReceivedEvent>((e) => onData(e.data, e.topic))
        ..on<ParticipantConnectedEvent>((e) => _joined(e.participant))
        ..on<ParticipantDisconnectedEvent>((e) {
          if (isCaller(e.participant.identity)) onCallerLeft(e.participant.identity);
        })
        ..on<TrackSubscribedEvent>((e) {
          if (!_remoteAudioOn && e.track is RemoteAudioTrack) unawaited(e.track.disable());
        })
        ..on<RoomReconnectingEvent>((_) => state.value = LinkState.reconnecting)
        ..on<RoomReconnectedEvent>((_) => state.value = LinkState.connected)
        ..on<RoomDisconnectedEvent>((e) => _onDisconnected(room, e.reason));
      await room.connect(creds.url, creds.token);
      _attempt = 0;
      state.value = LinkState.connected;
      final me = room.localParticipant?.identity ?? '';
      log('LiveKit connected to room "${room.name}" as "$me"');
      if (me != AppConfig.victimIdentity) {
        log(
          'Token identity is "$me", but the bridge only sends to "${AppConfig.victimIdentity}". '
          'No verdicts will arrive.',
          important: true,
        );
      }
      // Publish the mic once now (so the permission prompt happens before any
      // call), then keep it muted until a call is active.
      try {
        await room.localParticipant?.setMicrophoneEnabled(true);
        if (!_micOn) await room.localParticipant?.setMicrophoneEnabled(false);
      } catch (e) {
        log('Microphone unavailable: $e', important: true);
      }
      await setSpeaker(_speaker);
      for (final p in room.remoteParticipants.values) {
        _joined(p);
      }
    } catch (e) {
      log('LiveKit connect failed: $e', important: _attempt == 0);
      await _teardown();
      _scheduleRetry();
    }
  }

  void _joined(RemoteParticipant p) {
    if (!isCaller(p.identity)) return;
    var number = '';
    try {
      final meta = p.metadata == null || p.metadata!.isEmpty ? null : jsonDecode(p.metadata!);
      if (meta is Map && meta['phone'] is String) number = meta['phone'] as String;
    } catch (_) {}
    if (number.isEmpty) number = p.name.isNotEmpty ? p.name : p.identity;
    onCallerJoined(CallerInfo(p.identity, number));
  }

  void _onDisconnected(Room room, DisconnectReason? reason) {
    if (!identical(room, _room) || _disposed) return;
    if (reason == DisconnectReason.duplicateIdentity) {
      log(
        'Another phone joined as "${AppConfig.victimIdentity}" and took over. Not reconnecting; '
        'restart the app on the phone that should be the victim.',
        important: true,
      );
      state.value = LinkState.failed;
      unawaited(_teardown());
      return;
    }
    log('LiveKit disconnected (${reason?.name ?? 'unknown'}), reconnecting');
    unawaited(_teardown());
    _scheduleRetry();
  }

  void _scheduleRetry() {
    if (_disposed) return;
    _attempt++;
    state.value = LinkState.reconnecting;
    final secs = math.min(30, 1 << math.min(_attempt, 5));
    _retry?.cancel();
    _retry = Timer(Duration(seconds: secs), _connect);
  }

  Future<void> _teardown() async {
    final room = _room;
    _room = null;
    await _listener?.dispose();
    _listener = null;
    try {
      await room?.disconnect();
    } catch (_) {}
  }

  /// Logs who the token is for and when it expires (stage-day sanity check).
  void _describeToken(String token) {
    try {
      final parts = token.split('.');
      if (parts.length != 3) return;
      final j = jsonDecode(utf8.decode(base64Url.decode(base64Url.normalize(parts[1])))) as Map<String, dynamic>;
      final exp = j['exp'] is num ? DateTime.fromMillisecondsSinceEpoch((j['exp'] as num).toInt() * 1000) : null;
      final room = (j['video'] is Map) ? (j['video'] as Map)['room'] : null;
      final left = exp?.difference(DateTime.now());
      log(
        'LiveKit token: identity "${j['sub']}", room "$room", '
        '${exp == null
            ? 'no expiry'
            : left!.isNegative
            ? 'EXPIRED at $exp'
            : 'expires $exp'}',
        important: left != null && left.isNegative,
      );
    } catch (_) {}
  }

  /// Tell the guardian what an OTP SMS on this phone is for (CONTRACTS.md §6). Never the code.
  Future<bool> sendOtpSms(Map<String, Object?> context) async {
    final me = _room?.localParticipant;
    if (me == null) return false;
    try {
      await me.publishData(
        utf8.encode(jsonEncode(context)),
        reliable: true,
        destinationIdentities: [guardianIdentity],
        topic: 'chaukanna.otp_sms',
      );
      return true;
    } catch (e) {
      log('OTP SMS context not sent: $e');
      return false;
    }
  }

  Future<void> setMicEnabled(bool on) async {
    _micOn = on;
    try {
      await _room?.localParticipant?.setMicrophoneEnabled(on);
    } catch (e) {
      log('Mic switch failed: $e');
    }
  }

  /// Silence (or restore) the caller's audio, e.g. after the victim hangs up.
  Future<void> setRemoteAudio(bool on) async {
    _remoteAudioOn = on;
    final room = _room;
    if (room == null) return;
    for (final p in room.remoteParticipants.values) {
      for (final pub in p.audioTrackPublications) {
        try {
          if (on) {
            await pub.enable();
            await pub.track?.enable();
          } else {
            await pub.track?.disable();
            await pub.disable();
          }
        } catch (_) {}
      }
    }
  }

  Future<void> setSpeaker(bool on) async {
    _speaker = on;
    if (_room == null) return;
    try {
      await AudioManager.instance.setSpeakerOutputPreferred(on);
    } catch (e) {
      log('Speaker switch failed: $e');
    }
  }

  Future<void> dispose() async {
    _disposed = true;
    _retry?.cancel();
    await _teardown();
  }
}
