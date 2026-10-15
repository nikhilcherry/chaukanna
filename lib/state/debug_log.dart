import 'package:flutter/foundation.dart';

class LogEntry {
  const LogEntry(this.at, this.message, this.important);
  final DateTime at;
  final String message;
  final bool important;

  String get clock =>
      '${at.hour.toString().padLeft(2, '0')}:${at.minute.toString().padLeft(2, '0')}:${at.second.toString().padLeft(2, '0')}';
}

/// Ring buffer shown in the Demo Simulator drawer, so on-stage failures
/// (missing audio, LiveKit, n8n) are visible without adb.
class DebugLog {
  DebugLog({this.capacity = 200});

  final int capacity;
  final List<LogEntry> _entries = [];

  List<LogEntry> get entries => List.unmodifiable(_entries.reversed);

  void add(String message, {bool important = false, DateTime? at}) {
    _entries.add(LogEntry(at ?? DateTime.now(), message, important));
    if (_entries.length > capacity) _entries.removeRange(0, _entries.length - capacity);
    debugPrint('[chaukanna] $message');
  }

  void clear() => _entries.clear();
}
