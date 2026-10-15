import 'package:flutter/services.dart';

import '../generated/whisper_clips.dart' as gen;
import '../models/verdict.dart';

/// One playable whisper clip.
class ClipRef {
  const ClipRef({
    required this.clip,
    required this.lang,
    required this.variant,
    required this.asset,
    required this.text,
    this.durationMs,
  });

  final String clip; // warn_otp | ...
  final String lang; // hi | kn | en
  final String variant; // short | full
  final String asset; // Flutter asset key
  final String text; // caption: what the clip says
  final int? durationMs;

  @override
  String toString() => asset;
}

typedef ClipLookup = ClipRef? Function(String clip, String lang, String variant);

/// The on-screen warning: always English, plus the call language when it is not English.
class WarningText {
  const WarningText(this.en, this.local, this.localLang);
  final String en;
  final String? local;
  final String localLang;
}

/// Resolves warning ids to bundled audio and captions.
///
/// Clip metadata comes from lib/generated/whisper_clips.dart (written by
/// tts_asset_generator, never edited by hand); the lookup is injectable for
/// tests. Every asset is checked against the bundle's AssetManifest, so a
/// missing file shows up at call start instead of silently at the moment a
/// warning should play.
class ClipCatalog {
  ClipCatalog({ClipLookup? lookup, Set<String>? bundledAssets})
    : _lookup = lookup ?? generatedClip,
      _assets = bundledAssets;

  static List<String> get clipIds => gen.kWhisperClipIds;
  static List<String> get languages => gen.kWhisperLangs;

  final ClipLookup _lookup;

  /// Null = not checked (tests, or the manifest could not be read).
  final Set<String>? _assets;

  /// Number of bundled audio assets, or null when unknown.
  int? get bundledAudioCount => _assets?.where((a) => a.startsWith('assets/audio/') && a.endsWith('.wav')).length;

  static Future<ClipCatalog> load(AssetBundle bundle, {ClipLookup? lookup}) async {
    try {
      final manifest = await AssetManifest.loadFromAssetBundle(bundle);
      return ClipCatalog(lookup: lookup, bundledAssets: manifest.listAssets().toSet());
    } catch (_) {
      return ClipCatalog(lookup: lookup);
    }
  }

  bool isBundled(String asset) => _assets == null || _assets.contains(asset);

  ClipRef? _exact(String clip, String lang, String variant) {
    final r = _lookup(clip, lang, variant);
    if (r == null || r.lang != lang || !isBundled(r.asset)) return null;
    return r;
  }

  /// The language whose clips will actually play: [lang] when it has audio, else English.
  String playableLang(String clip, String lang) {
    final l = normLang(lang);
    if (_exact(clip, l, 'full') != null || _exact(clip, l, 'short') != null) return l;
    return 'en';
  }

  /// What to play for one warning: the short clip first (if bundled), then the
  /// full clip. Both in the same language. Empty when nothing is bundled.
  List<ClipRef> sequence(String clip, String lang) {
    if (clip.isEmpty || clip == 'none') return const [];
    final l = playableLang(clip, lang);
    return [?_exact(clip, l, 'short'), ?_exact(clip, l, 'full')];
  }

  /// Big on-screen text for a warning: the short clip's words (what the victim
  /// hears first), in English and in the call language.
  WarningText warningText(String clip, String lang) {
    final l = normLang(lang);
    String? text(String language) {
      final s = _lookup(clip, language, 'short');
      if (s != null && s.lang == language) return s.text;
      return _headlines[clip]?[language];
    }

    final en = text('en') ?? _generic['en']!;
    final local = l == 'en' ? null : (text(l) ?? _generic[l]);
    return WarningText(en, local, l);
  }

  /// Human-readable list of warnings that have no audio at all in [lang].
  List<String> missingAudio(String lang) => [
    for (final c in clipIds)
      if (sequence(c, lang).isEmpty)
        '$c/$lang'
      else if (playableLang(c, lang) != normLang(lang))
        '$c/$lang (English fallback)',
  ];
}

/// Adapter over the generated metadata. Returns the exact language only;
/// [ClipCatalog] does the English fallback itself so short and full clips
/// always come from the same language.
ClipRef? generatedClip(String clip, String lang, String variant) {
  final g = gen.whisperClip(clip, lang, variant: variant);
  if (g == null || g.lang != lang) return null;
  return ClipRef(
    clip: g.clip,
    lang: g.lang,
    variant: g.variant,
    asset: g.asset,
    text: g.text,
    durationMs: g.durationMs,
  );
}

/// Shown when a high-pressure alarm has no specific warning.
const _generic = {
  'en': 'Careful! This call looks like a scam.',
  'hi': 'सावधान! यह कॉल धोखा लग रही है।',
  'kn': 'ಎಚ್ಚರ! ಈ ಕರೆ ವಂಚನೆಯಂತೆ ಕಾಣುತ್ತಿದೆ.',
};

/// Last-resort headlines if a clip has no caption at all.
const _headlines = <String, Map<String, String>>{
  'warn_otp': {
    'en': 'STOP! Do NOT share your OTP or PIN!',
    'hi': 'रुकिए! OTP या PIN किसी को न बताएं!',
    'kn': 'ನಿಲ್ಲಿ! OTP ಅಥವಾ PIN ಯಾರಿಗೂ ಹೇಳಬೇಡಿ!',
  },
  'warn_digital_arrest': {
    'en': 'SCAM! No police arrest over phone. Hang up!',
    'hi': 'धोखा! फोन पर कोई गिरफ्तारी नहीं होती। कॉल काटें!',
    'kn': 'ವಂಚನೆ! ಫೋನ್‌ನಲ್ಲಿ ಯಾವುದೇ ಅರೆಸ್ಟ್ ಇಲ್ಲ. ಕರೆ ಕಟ್ ಮಾಡಿ!',
  },
  'warn_secrecy': {
    'en': 'DANGER! Tell your family right now!',
    'hi': 'खतरा! अभी अपने परिवार को बताएं!',
    'kn': 'ಅಪಾಯ! ಈಗಲೇ ಕುಟುಂಬಕ್ಕೆ ತಿಳಿಸಿ!',
  },
  'warn_known_scammer': {
    'en': 'KNOWN SCAMMER! Call blocked.',
    'hi': 'जाना-पहचाना ठग! कॉल ब्लॉक की गई।',
    'kn': 'ಗೊತ್ತಿರುವ ವಂಚಕ! ಕರೆ ನಿರ್ಬಂಧಿಸಲಾಗಿದೆ.',
  },
};
