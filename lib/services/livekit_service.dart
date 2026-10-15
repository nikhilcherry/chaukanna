import 'package:flutter/foundation.dart';
import 'package:livekit_client/livekit_client.dart';

import '../models/verdict.dart';

/// Thin wrapper over the LiveKit room: connects, forwards guardian data
/// packets as [Verdict]s, and exposes mic / speaker toggles.
class LiveKitService {
  Room? _room;
  EventsListener<RoomEvent>? _listener;

  bool get connected => _room != null;

  Future<void> connect({
    required String url,
    required String token,
    required void Function(Verdict) onVerdict,
    required void Function() onDisconnected,
  }) async {
    final room = Room(roomOptions: const RoomOptions(adaptiveStream: true, dynacast: true));
    _room = room;
    _listener = room.createListener()
      ..on<DataReceivedEvent>((e) {
        final v = Verdict.tryParse(e.data);
        if (v != null) onVerdict(v);
      })
      ..on<RoomDisconnectedEvent>((_) => onDisconnected());
    await room.connect(url, token);
    await room.localParticipant?.setMicrophoneEnabled(true);
    await AudioManager.instance.setSpeakerOutputPreferred(false);
  }

  Future<void> setMuted(bool muted) async {
    try {
      await _room?.localParticipant?.setMicrophoneEnabled(!muted);
    } catch (e) {
      debugPrint('mute failed: $e');
    }
  }

  Future<void> setSpeaker(bool on) async {
    try {
      await AudioManager.instance.setSpeakerOutputPreferred(on);
    } catch (e) {
      debugPrint('speaker toggle failed: $e');
    }
  }

  Future<void> disconnect() async {
    final room = _room;
    _room = null;
    await _listener?.dispose();
    _listener = null;
    await room?.disconnect();
  }
}
