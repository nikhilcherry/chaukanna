import 'package:flutter/foundation.dart';
import 'package:just_audio/just_audio.dart';

/// Plays the pre-bundled whisper warnings from assets/audio/.
class WhisperPlayer {
  late final AudioPlayer _player = AudioPlayer();
  static const _supported = {'en', 'hi', 'kn'};

  static String? assetFor(String clip, String language) {
    if (clip.isEmpty || clip == 'none') return null;
    final lang = _supported.contains(language) ? language : 'en';
    return 'assets/audio/${clip}_$lang.wav';
  }

  /// Returns the asset played, or null if nothing was played.
  Future<String?> play(String clip, String language) async {
    final asset = assetFor(clip, language);
    if (asset == null) return null;
    try {
      await _player.stop();
      await _player.setAsset(asset);
      await _player.setVolume(1.0);
      _player.play(); // don't await: completes only when playback ends
      return asset;
    } catch (e) {
      debugPrint('Whisper playback failed for $asset: $e');
      return null;
    }
  }

  Future<void> stop() async {
    try {
      await _player.stop();
    } catch (_) {}
  }
  void dispose() {
    try {
      _player.dispose();
    } catch (_) {}
  }
}
