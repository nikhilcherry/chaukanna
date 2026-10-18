import 'package:flutter/material.dart';

/// How one kind of scam call presents itself to the user. Each type has its own
/// colour and icon, a plain statement of why it is a scam and the one thing to do.
/// The words and icon carry the meaning; colour only backs them up.
class ScamProfile {
  const ScamProfile({
    required this.label,
    required this.icon,
    required this.field,
    required this.onField,
    required this.truth,
    required this.action,
  });

  final String label;
  final IconData icon;

  /// The call type's colour: the alarm background and the live-call accents.
  final Color field;

  /// Text and icon colour that reads on [field].
  final Color onField;

  /// The fact that breaks the scam's spell, in one sentence.
  final String truth;

  /// What to do right now.
  final String action;

  static const _ink = Color(0xFF0F1729);

  static const digitalArrest = ScamProfile(
    label: 'Digital arrest scam',
    icon: Icons.gavel,
    field: Color(0xFFD92D34),
    onField: Colors.white,
    truth: 'Police, CBI and courts never arrest or question anyone over a phone or video call.',
    action: 'Hang up. Do not pay or share anything.',
  );

  static const kyc = ScamProfile(
    label: 'KYC update scam',
    icon: Icons.badge_outlined,
    field: Color(0xFFFFB224),
    onField: _ink,
    truth: 'Banks never fix KYC over the phone or ask for Aadhaar, PAN or card details on a call.',
    action: 'Do not share any numbers. Visit your branch.',
  );

  static const bank = ScamProfile(
    label: 'Fake bank call',
    icon: Icons.account_balance,
    field: Color(0xFF3E63DD),
    onField: Colors.white,
    truth: 'A real bank will never ask for your PIN, password or OTP.',
    action: 'Hang up. Call the number on your card.',
  );

  static const prize = ScamProfile(
    label: 'Prize or lottery scam',
    icon: Icons.card_giftcard,
    field: Color(0xFF8E4EC6),
    onField: Colors.white,
    truth: 'You cannot win a contest you never entered. Real prizes never ask you to pay first.',
    action: 'Hang up. Do not send any money.',
  );

  static const otp = ScamProfile(
    label: 'Asking for your OTP',
    icon: Icons.password,
    field: Color(0xFFF76B15),
    onField: _ink,
    truth: 'An OTP or PIN is a key to your money. No honest caller needs it.',
    action: 'Do not say the code. Hang up.',
  );

  static const secrecy = ScamProfile(
    label: 'Asking you to stay secret',
    icon: Icons.lock_outline,
    field: Color(0xFF0B7A6E),
    onField: Colors.white,
    truth: 'Scammers cut you off from family so nobody can stop them.',
    action: 'Hang up and call someone you trust.',
  );

  static const known = ScamProfile(
    label: 'Known scammer number',
    icon: Icons.phone_disabled,
    field: Color(0xFFB4162C),
    onField: Colors.white,
    truth: 'This number has already been reported by other people.',
    action: 'Hang up now.',
  );

  static const generic = ScamProfile(
    label: 'Suspected scam',
    icon: Icons.priority_high,
    field: Color(0xFFFFB224),
    onField: _ink,
    truth: 'This call shows signs of a scam.',
    action: 'Do not share anything. Hang up if unsure.',
  );

  /// Picks the profile for a live call. The strongest signal wins:
  /// known number, then the scam type, then what is being asked for.
  static ScamProfile resolve({
    required String scamType,
    bool knownScammer = false,
    bool asksOtp = false,
    bool secrecy = false,
    String clip = 'none',
  }) {
    if (knownScammer || clip == 'warn_known_scammer') return known;
    final byType = switch (scamType) {
      'digital_arrest' => digitalArrest,
      'kyc_update' => kyc,
      'bank_impersonation' => bank,
      'prize_lottery' => prize,
      'other' => generic,
      _ => null,
    };
    if (byType != null) return byType;
    if (clip == 'warn_otp' || asksOtp) return ScamProfile.otp;
    if (clip == 'warn_secrecy' || secrecy) return ScamProfile.secrecy;
    if (clip == 'warn_digital_arrest') return digitalArrest;
    return generic;
  }
}
