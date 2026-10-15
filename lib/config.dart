/// Build-time configuration, supplied with --dart-define.
/// Leave empty to run fully offline (demo simulator only).
class AppConfig {
  static const livekitUrl = String.fromEnvironment('LIVEKIT_URL');
  static const livekitToken = String.fromEnvironment('LIVEKIT_TOKEN');
  static const n8nApprovalWebhook = String.fromEnvironment('N8N_APPROVAL_WEBHOOK');

  static bool get liveKitConfigured =>
      livekitUrl.isNotEmpty && livekitToken.isNotEmpty;
  static bool get webhookConfigured => n8nApprovalWebhook.isNotEmpty;
}
