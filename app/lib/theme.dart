import 'package:flutter/material.dart';

/// A light, quiet palette: cool off-white, white cards, one blue, and a handful of
/// clean alert colours that each mean one kind of call.
class Pal {
  static const ink = Color(0xFF0F1729);
  static const brand = Color(0xFF3E63DD); // protected / ready
  static const brandSoft = Color(0xFFE9EEFF);
  static const paper = Color(0xFFFFFFFF);
  static const bg = Color(0xFFF5F6F8);
  static const line = Color(0xFFE3E6EC);

  static const card = paper;
  static const cardHi = Color(0xFFEEF0F4);
  static const text = ink;
  static const dim = Color(0xFF4B5565); // 7.6:1 on white
  static const grey = Color(0xFF6B7280);

  static const amber = Color(0xFFFFB224);
  static const orange = Color(0xFFF76B15);
  static const red = Color(0xFFD92D34);
  static const crimson = Color(0xFFB4162C);

  static const safe = brand;
  static const caution = Color(0xFF8A5A00); // amber dark enough for text on white
  static const high = Color(0xFFC2410C);
  static const critical = red;

  static Color forPressure(int p) => [brand, amber, orange, red][p.clamp(0, 3)];
  static String labelFor(int p) => ['Safe', 'Caution', 'High risk', 'Critical scam'][p.clamp(0, 3)];

  /// Readable text on a filled [c]: ink on the bright ambers and oranges, white on the rest.
  static Color onColor(Color c) => c.computeLuminance() > 0.27 ? ink : Colors.white;
}

/// Bundled fallbacks so Devanagari and Kannada always render, with real bold. 'NotoColorEmoji'
/// is not bundled: a phone skips the unknown name and uses its system emoji font, and
/// tool/screenshots_test.dart loads the file under that name so emoji render in README shots.
const kIndicFallback = ['NotoSansDevanagari', 'NotoSansKannada', 'NotoColorEmoji'];

/// Headline style: Manrope set heavy and slightly tight.
TextStyle display(double size, {Color? color, double weight = 800, double height = 1.1, double letterSpacing = -0.3}) =>
    TextStyle(
      fontFamily: 'Manrope',
      fontFamilyFallback: kIndicFallback,
      fontSize: size,
      color: color,
      height: height,
      letterSpacing: letterSpacing,
      fontWeight: weight >= 800 ? FontWeight.w800 : (weight >= 700 ? FontWeight.w700 : FontWeight.w600),
      fontVariations: [FontVariation('wght', weight)],
    );

const kSoftShadow = [BoxShadow(color: Color(0x1A0F1729), blurRadius: 24, offset: Offset(0, 8))];

BoxDecoration cardDecoration({Color color = Pal.paper, double radius = 20}) =>
    BoxDecoration(color: color, borderRadius: BorderRadius.circular(radius), boxShadow: kSoftShadow);

ThemeData buildTheme() {
  final base = ThemeData.light().textTheme
      .apply(bodyColor: Pal.text, displayColor: Pal.text, fontFamily: 'Manrope')
      .apply(fontFamilyFallback: kIndicFallback);
  // Button text styles replace (not merge with) the theme style, so derive them
  // from it to keep the font family and the Indic fallbacks.
  final label = base.labelLarge!.copyWith(fontSize: 19, fontWeight: FontWeight.w700);
  final pill = RoundedRectangleBorder(borderRadius: BorderRadius.circular(28));
  return ThemeData(
    useMaterial3: true,
    brightness: Brightness.light,
    fontFamily: 'Manrope',
    fontFamilyFallback: kIndicFallback,
    scaffoldBackgroundColor: Pal.bg,
    colorScheme: const ColorScheme.light(primary: Pal.brand, onPrimary: Colors.white, surface: Pal.card),
    textTheme: base,
    materialTapTargetSize: MaterialTapTargetSize.padded,
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      backgroundColor: Pal.ink,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      contentTextStyle: base.bodyLarge!.copyWith(fontSize: 18, color: Colors.white),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: Pal.paper,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(minimumSize: const Size(64, 56), textStyle: label, shape: pill),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(minimumSize: const Size(64, 56), textStyle: label, shape: pill),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(minimumSize: const Size(64, 56), textStyle: label, shape: pill),
    ),
    segmentedButtonTheme: SegmentedButtonThemeData(
      style: SegmentedButton.styleFrom(
        minimumSize: const Size(0, 52),
        textStyle: label.copyWith(fontSize: 18),
        selectedBackgroundColor: Pal.brand,
        selectedForegroundColor: Colors.white,
        side: const BorderSide(color: Pal.line, width: 1.5),
      ),
    ),
  );
}
