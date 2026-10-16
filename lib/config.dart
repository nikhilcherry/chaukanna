/// Build-time configuration, supplied with --dart-define.
///
/// Everything is optional. With no LiveKit settings the app runs fully offline
/// and the Demo Simulator drives every screen.
class AppConfig {
  /// wss://... LiveKit server the bridge also joins.
  static const livekitUrl = String.fromEnvironment('LIVEKIT_URL');

  /// A pre-minted access token for identity [victimIdentity]. Mint it with a
  /// TTL that outlives the event (the default LiveKit TTL is 6 h).
  static const livekitToken = String.fromEnvironment('LIVEKIT_TOKEN');

  /// Optional alternative to [livekitToken]: GET this URL, expect
  /// `{"token": "...", "url": "wss://..."}` back.
  static const livekitTokenUrl = String.fromEnvironment('LIVEKIT_TOKEN_URL');

  /// The bridge sends data messages only to this identity.
  static const victimIdentity = String.fromEnvironment('VICTIM_IDENTITY', defaultValue: 'victim');

  /// Fallback approval endpoint (CONTRACTS §3) when no `approve_url` arrived.
  static const n8nApprovalWebhook = String.fromEnvironment(
    'N8N_APPROVAL_WEBHOOK',
    defaultValue: 'https://n8n.premortem.tech/webhook/chaukanna-approve',
  );

  static const victimId = String.fromEnvironment('VICTIM_ID', defaultValue: 'demo-victim-1');

  /// How the family refers to the protected person in simulated alerts.
  static const victimName = String.fromEnvironment('VICTIM_NAME', defaultValue: 'Kamala Devi');

  /// Language whose whisper clips are preloaded before the first verdict says
  /// which language the call is in (hi | kn | en).
  static const preferredLanguage = String.fromEnvironment('VICTIM_LANG', defaultValue: 'hi');

  /// Pause the victim's microphone while a whisper plays, so the caller cannot
  /// hear the warning even if echo cancellation misses it.
  static const muteMicDuringWhisper = bool.fromEnvironment('MUTE_MIC_DURING_WHISPER', defaultValue: true);

  /// Start calls on the loudspeaker (stage demo) or the earpiece.
  static const speakerByDefault = bool.fromEnvironment('SPEAKER_DEFAULT', defaultValue: true);

  /// 'call' plays whispers on the voice-call audio route (follows earpiece /
  /// speaker / headset of the call); 'media' plays them like music.
  static const whisperRoute = String.fromEnvironment('WHISPER_ROUTE', defaultValue: 'call');

  /// Hang up automatically a few seconds after a known-scammer warning.
  static const autoBlockKnownScammers = bool.fromEnvironment('AUTO_BLOCK_KNOWN', defaultValue: true);

  static bool get liveKitConfigured => livekitTokenUrl.isNotEmpty || (livekitUrl.isNotEmpty && livekitToken.isNotEmpty);
}
