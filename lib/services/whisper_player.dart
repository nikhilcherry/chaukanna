import 'dart:async';

import 'package:audio_session/audio_session.dart'
    show AndroidAudioAttributes, AndroidAudioContentType, AndroidAudioUsage;
import 'package:just_audio/just_audio.dart';

import 'clip_catalog.dart';

enum WhisperOutcome { completed, stopped }

/// Where whisper audio is routed on Android.
enum WhisperRoute {
  /// Voice-call stream: follows the call's earpiece / speaker / headset.
  call,

  /// Media stream, like music. Used for offline (simulated) calls so the demo
  /// is always audible on the loudspeaker.
  media,
}

class WhisperFailure implements Exception {
  WhisperFailure(this.message);
  final String message;
  @override
  String toString() => message;
}

/// Plays whisper warnings. The controller decides what and when; the engine
/// only plays sequences of bundled assets.
abstract class WhisperEngine {
  /// Warms up one player per warning so playback starts without load delay.
  /// Returns a description of every sequence that failed to load.
  Future<List<String>> preload(Map<String, List<ClipRef>> sequences);

  /// Plays [sequence] (short clip, then full clip) for [clip]. A newer call to
  /// [play] or [stop] ends this one with [WhisperOutcome.stopped].
  /// Throws [WhisperFailure] if the audio cannot be loaded or played.
  Future<WhisperOutcome> play(String clip, List<ClipRef> sequence, {void Function(ClipRef ref)? onClip});

  Future<void> stop();

  Future<void> setRoute(WhisperRoute route);

  void dispose();
}

/// just_audio implementation: a small pool, one AudioPlayer per warning id,
/// each preloaded with that warning's [short, full] playlist.
class JustAudioWhisperEngine implements WhisperEngine {
  final Map<String, AudioPlayer> _players = {};
  final Map<String, String> _loaded = {}; // clip -> joined asset keys
  final Map<String, Future<void>> _inflight = {};
  WhisperRoute _route = WhisperRoute.call;
  int _generation = 0;
  Completer<WhisperOutcome>? _active;

  AudioPlayer _player(String clip) => _players.putIfAbsent(clip, () {
    // No audio-session activation or interruption handling: during a
    // LiveKit call WebRTC owns audio focus, and just_audio silently skips
    // play() if activation fails. We must always play.
    final p = AudioPlayer(
      handleInterruptions: false,
      handleAudioSessionActivation: false,
      androidApplyAudioAttributes: false,
    );
    unawaited(_applyRoute(p));
    return p;
  });

  Future<void> _applyRoute(AudioPlayer p) async {
    try {
      await p.setAndroidAudioAttributes(
        _route == WhisperRoute.call
            ? const AndroidAudioAttributes(
                contentType: AndroidAudioContentType.speech,
                usage: AndroidAudioUsage.voiceCommunication,
              )
            : const AndroidAudioAttributes(contentType: AndroidAudioContentType.speech, usage: AndroidAudioUsage.media),
      );
    } catch (_) {}
  }

  /// Loads are serialised per player: just_audio interrupts an in-flight
  /// setAudioSources when another starts, so a preload racing a whisper (the
  /// first verdict often switches the call language) would make the whisper fail.
  Future<void> _load(String clip, List<ClipRef> seq) {
    final key = seq.map((r) => r.asset).join('|');
    if (_loaded[clip] == key) return Future.value();
    final pending = _inflight[clip];
    final job = () async {
      if (pending != null) {
        try {
          await pending;
        } catch (_) {}
      }
      if (_loaded[clip] == key) return;
      _loaded.remove(clip);
      final p = _player(clip);
      try {
        await p.setAudioSources([for (final r in seq) AudioSource.asset(r.asset)], preload: true);
      } catch (e) {
        throw WhisperFailure('Could not load ${seq.map((r) => r.asset).join(' + ')}: $e');
      }
      _loaded[clip] = key;
    }();
    _inflight[clip] = job;
    unawaited(
      job.then((_) {}, onError: (Object _) {}).whenComplete(() {
        if (identical(_inflight[clip], job)) _inflight.remove(clip);
      }),
    );
    return job;
  }

  @override
  Future<List<String>> preload(Map<String, List<ClipRef>> sequences) async {
    final failed = <String>[];
    for (final e in sequences.entries) {
      if (e.value.isEmpty) continue;
      try {
        await _load(e.key, e.value);
      } catch (err) {
        failed.add('$err');
      }
    }
    return failed;
  }

  @override
  Future<WhisperOutcome> play(String clip, List<ClipRef> sequence, {void Function(ClipRef ref)? onClip}) async {
    if (sequence.isEmpty) throw WhisperFailure('No audio bundled for $clip');
    final gen = ++_generation;
    _finish(WhisperOutcome.stopped);
    await _rewindAll();
    await _load(clip, sequence);
    if (gen != _generation) return WhisperOutcome.stopped;

    final p = _player(clip);
    final done = Completer<WhisperOutcome>();
    _active = done;
    final subs = <StreamSubscription<Object?>>[
      p.currentIndexStream.listen((i) {
        if (i != null && i >= 0 && i < sequence.length && !done.isCompleted) onClip?.call(sequence[i]);
      }),
      p.processingStateStream.listen((s) {
        if (s == ProcessingState.completed && !done.isCompleted) done.complete(WhisperOutcome.completed);
      }),
      p.playbackEventStream.listen(
        (_) {},
        onError: (Object e, StackTrace _) {
          if (!done.isCompleted) done.completeError(WhisperFailure('Playback error: $e'));
        },
      ),
    ];
    try {
      await p.seek(Duration.zero, index: 0);
      unawaited(
        p.play().catchError((Object e) {
          if (!done.isCompleted) done.completeError(WhisperFailure('Playback error: $e'));
        }),
      );
      return await done.future;
    } finally {
      for (final s in subs) {
        await s.cancel();
      }
      if (identical(_active, done)) _active = null;
      if (gen == _generation) await _rewind(p);
    }
  }

  void _finish(WhisperOutcome outcome) {
    final a = _active;
    _active = null;
    if (a != null && !a.isCompleted) a.complete(outcome);
  }

  Future<void> _rewind(AudioPlayer p) async {
    try {
      await p.pause();
      await p.seek(Duration.zero, index: 0);
    } catch (_) {}
  }

  Future<void> _rewindAll() async {
    for (final p in _players.values) {
      if (p.playing) await _rewind(p);
    }
  }

  @override
  Future<void> stop() async {
    _generation++;
    _finish(WhisperOutcome.stopped);
    await _rewindAll();
  }

  @override
  Future<void> setRoute(WhisperRoute route) async {
    if (route == _route) return;
    _route = route;
    for (final p in _players.values) {
      await _applyRoute(p);
    }
  }

  @override
  void dispose() {
    _finish(WhisperOutcome.stopped);
    for (final p in _players.values) {
      try {
        p.dispose();
      } catch (_) {}
    }
    _players.clear();
  }
}
