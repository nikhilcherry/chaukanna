import 'package:flutter/material.dart';

class Pal {
  static const bg = Color(0xFF0B0F14);
  static const card = Color(0xFF161D26);
  static const text = Color(0xFFFFFFFF);
  static const dim = Color(0xFFB4BFCC);
  static const safe = Color(0xFF2ECC71);
  static const caution = Color(0xFFFFC107);
  static const high = Color(0xFFFF7A1A);
  static const critical = Color(0xFFE5173F);
  static const crimson = Color(0xFFDC143C);

  static Color forPressure(int p) => [safe, caution, high, critical][p.clamp(0, 3)];
  static String labelFor(int p) => ['SAFE', 'CAUTION', 'HIGH RISK', 'CRITICAL SCAM'][p.clamp(0, 3)];
}

ThemeData buildTheme() => ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      scaffoldBackgroundColor: Pal.bg,
      colorScheme: const ColorScheme.dark(primary: Pal.safe, surface: Pal.card),
      textTheme: ThemeData.dark().textTheme.apply(bodyColor: Pal.text, displayColor: Pal.text),
    );
