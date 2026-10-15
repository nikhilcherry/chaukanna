import 'package:flutter/material.dart';

class Pal {
  static const bg = Color(0xFF0B0F14);
  static const card = Color(0xFF161D26);
  static const cardHi = Color(0xFF1F2833);
  static const text = Color(0xFFFFFFFF);
  static const dim = Color(0xFFC3CCD6); // >= 9:1 on bg and card
  static const safe = Color(0xFF2ECC71);
  static const caution = Color(0xFFFFC107);
  static const high = Color(0xFFFF7A1A);
  static const critical = Color(0xFFE5173F);
  static const crimson = Color(0xFFDC143C);
  static const grey = Color(0xFF8A96A3);

  static Color forPressure(int p) => [safe, caution, high, critical][p.clamp(0, 3)];
  static String labelFor(int p) => ['SAFE', 'CAUTION', 'HIGH RISK', 'CRITICAL SCAM'][p.clamp(0, 3)];

  /// Readable text on a filled [c] (black on the bright greens/ambers/oranges,
  /// white on the reds), so contrast never depends on colour perception.
  static Color onColor(Color c) => c.computeLuminance() > 0.18 ? Colors.black : Colors.white;
}

/// Bundled fallbacks so Devanagari and Kannada always render, with real bold.
const kIndicFallback = ['NotoSansDevanagari', 'NotoSansKannada'];

ThemeData buildTheme() {
  final base = ThemeData.dark().textTheme.apply(
        bodyColor: Pal.text,
        displayColor: Pal.text,
        fontSizeFactor: 1.15,
      );
  return ThemeData(
    useMaterial3: true,
    brightness: Brightness.dark,
    fontFamilyFallback: kIndicFallback,
    scaffoldBackgroundColor: Pal.bg,
    colorScheme: const ColorScheme.dark(primary: Pal.safe, onPrimary: Colors.black, surface: Pal.card),
    textTheme: base,
    materialTapTargetSize: MaterialTapTargetSize.padded,
    snackBarTheme: const SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      contentTextStyle: TextStyle(fontSize: 18, fontFamilyFallback: kIndicFallback),
    ),
    dialogTheme: const DialogThemeData(backgroundColor: Pal.card),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(minimumSize: const Size(64, 56), textStyle: const TextStyle(fontSize: 20)),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(minimumSize: const Size(64, 56), textStyle: const TextStyle(fontSize: 20)),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(minimumSize: const Size(64, 56)),
    ),
  );
}
