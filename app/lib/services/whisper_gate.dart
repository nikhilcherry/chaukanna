/// Dedupes whisper warnings: the same clip plays at most once per [window],
/// whatever the bridge, classifier or simulator asks for.
class WhisperGate {
  WhisperGate({this.window = const Duration(seconds: 20)});

  final Duration window;
  final Map<String, DateTime> _last = {};

  /// True (and records [now]) if [clip] may play; false if it played less than [window] ago.
  bool tryAcquire(String clip, DateTime now) {
    final t = _last[clip];
    if (t != null && now.difference(t) < window) return false;
    _last[clip] = now;
    return true;
  }

  /// When [clip] last played, if it did.
  DateTime? lastPlayed(String clip) => _last[clip];

  void reset() => _last.clear();
}
