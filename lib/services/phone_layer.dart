import 'dart:async';
import 'dart:convert';
import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

enum PhoneCallState { idle, ringing, offhook }

/// A call the screening service dealt with before it rang: [blocked] numbers never rang,
/// [flagged] ones (risky country code) rang with a warning notification.
class ScreenedCall {
  const ScreenedCall({required this.number, required this.blocked, required this.note, required this.at});
  final String number;
  final bool blocked;
  final String note;
  final DateTime at;

  static List<ScreenedCall> parseLog(String json) {
    try {
      final list = jsonDecode(json) as List<dynamic>;
      return [
        for (final e in list.whereType<Map<String, dynamic>>())
          ScreenedCall(
            number: (e['number'] as String?) ?? '',
            blocked: e['kind'] == 'blocked',
            note: (e['note'] as String?) ?? '',
            at: DateTime.fromMillisecondsSinceEpoch((e['at'] as num?)?.toInt() ?? 0),
          ),
      ];
    } catch (_) {
      return const [];
    }
  }
}

class PhoneEvent {
  const PhoneEvent(this.state, this.number);
  final PhoneCallState state;
  final String number;
}

class PhonePermissions {
  const PhonePermissions({
    this.microphone = false,
    this.phone = false,
    this.callLog = false,
    this.answerCalls = false,
    this.notifications = false,
    this.overlay = false,
    this.enabled = false,
  });

  final bool microphone;
  final bool phone;
  final bool callLog;
  final bool answerCalls;
  final bool notifications;
  final bool overlay;

  /// The protection switch was left on.
  final bool enabled;

  /// What it cannot work without: hearing the call and knowing it is happening.
  bool get ready => microphone && phone;

  /// Nice to have: show the caller's number, hang up for you, put warnings over the dialer.
  List<String> get missingExtras => [
    if (!callLog) "the caller's number",
    if (!answerCalls) 'hanging up for you',
    if (!overlay) 'warnings over the dialer',
  ];

  factory PhonePermissions.fromMap(Map<Object?, Object?> m) => PhonePermissions(
    microphone: m['microphone'] == true,
    phone: m['phone'] == true,
    callLog: m['callLog'] == true,
    answerCalls: m['answerCalls'] == true,
    notifications: m['notifications'] == true,
    overlay: m['overlay'] == true,
    enabled: m['enabled'] == true,
  );
}

/// What the app can do about the phone's ordinary calls. Android gives no access to the
/// call audio, so this only reports call state, keeps the app alive, and acts on the call.
abstract class PhoneLayer {
  Stream<PhoneEvent> get events;
  Future<PhonePermissions> status();
  Future<PhonePermissions> requestPermissions();
  Future<void> openOverlaySettings();
  Future<bool> start();
  Future<void> stop();
  Future<bool> endCall();
  Future<bool> setSpeaker(bool on);
  Future<bool> bringToFront();

  /// Whether Chaukanna is the phone's call-screening app, so it sees numbers before they ring.
  Future<bool> screeningHeld();

  /// Ask Android to make Chaukanna the call-screening app. Resolves to whether it now is.
  Future<bool> requestScreening();

  /// The numbers the screening service blocked or flagged, newest first.
  Future<List<ScreenedCall>> screenedCalls();

  /// The real implementation on Android; null on every other platform.
  static PhoneLayer? platform() => !kIsWeb && Platform.isAndroid ? AndroidPhoneLayer() : null;
}

class AndroidPhoneLayer implements PhoneLayer {
  static const _methods = MethodChannel('chaukanna/phone');
  static const _events = EventChannel('chaukanna/phone/events');

  @override
  Stream<PhoneEvent> get events => _events.receiveBroadcastStream().map((e) {
    final m = e as Map<Object?, Object?>;
    final state = switch (m['state']) {
      'ringing' => PhoneCallState.ringing,
      'offhook' => PhoneCallState.offhook,
      _ => PhoneCallState.idle,
    };
    return PhoneEvent(state, (m['number'] as String?) ?? '');
  });

  Future<PhonePermissions> _perms(String method) async {
    final m = await _methods.invokeMapMethod<Object?, Object?>(method);
    return PhonePermissions.fromMap(m ?? const {});
  }

  @override
  Future<PhonePermissions> status() => _perms('status');

  @override
  Future<PhonePermissions> requestPermissions() => _perms('requestPermissions');

  @override
  Future<void> openOverlaySettings() => _methods.invokeMethod('openOverlaySettings');

  @override
  Future<bool> start() async => await _methods.invokeMethod<bool>('start') ?? false;

  @override
  Future<void> stop() => _methods.invokeMethod('stop');

  @override
  Future<bool> endCall() async => await _methods.invokeMethod<bool>('endCall') ?? false;

  @override
  Future<bool> setSpeaker(bool on) async => await _methods.invokeMethod<bool>('setSpeaker', {'on': on}) ?? false;

  @override
  Future<bool> bringToFront() async => await _methods.invokeMethod<bool>('bringToFront') ?? false;

  @override
  Future<bool> screeningHeld() async => await _methods.invokeMethod<bool>('screeningStatus') ?? false;

  @override
  Future<bool> requestScreening() async => await _methods.invokeMethod<bool>('requestScreening') ?? false;

  @override
  Future<List<ScreenedCall>> screenedCalls() async =>
      ScreenedCall.parseLog(await _methods.invokeMethod<String>('screenedLog') ?? '[]');
}
