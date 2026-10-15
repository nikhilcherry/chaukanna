/// Masks OTP-like digit runs (4-8 digits) before a transcript line is shown,
/// stored as evidence or sent anywhere.
///
/// Masked:   "482913", "4 8 2 9 1 3", "482 913", Devanagari/Kannada digits.
/// Kept:     phone numbers (more than 8 digits), dates/times with - / . :
///           separators, 1930 (the cybercrime helpline), rupee amounts, and
///           digits glued to letters (codes like KA01AB1234).
String maskOtp(String text) {
  if (text.isEmpty) return text;
  return text.replaceAllMapped(_group, (m) {
    final s = m.group(0)!;
    final digits = s.replaceAll(_sep, '');
    final n = digits.length;
    if (n < 4 || n > 8) return s;
    if (_asciiDigits(digits) == '1930') return s;
    final chunks = s.split(_sep);
    if (chunks.length > 1 && s.contains(_dateSep)) return s; // 15-10-2026, 10:30
    final before = text.substring(0, m.start);
    final after = text.substring(m.end);
    if (before.isNotEmpty && _letter.hasMatch(before[before.length - 1])) return s;
    if (after.isNotEmpty && _letter.hasMatch(after[0])) return s;
    if (_currencyBefore.hasMatch(before) || _currencyAfter.hasMatch(after)) return s;
    return '•' * n;
  });
}

const _d = '0-9\u0966-\u096F\u0CE6-\u0CEF'; // ASCII, Devanagari, Kannada digits
final _group = RegExp('[$_d]+(?:[ \\-/.:][$_d]+)*');
final _sep = RegExp('[ \\-/.:]');
final _dateSep = RegExp('[\\-/.:]');
final _letter = RegExp('[A-Za-z]');
final _currencyBefore = RegExp(r'(₹|rs\.?|inr|rupees?)\s*$', caseSensitive: false);
final _currencyAfter =
    RegExp(r'^\s*(₹|rs\b|inr\b|rupees?\b|lakh|crore|रुपये|रुपए|रुपया|लाख|ರೂಪಾಯಿ|ಲಕ್ಷ)', caseSensitive: false);

String _asciiDigits(String s) => String.fromCharCodes(s.runes.map((r) {
      if (r >= 0x0966 && r <= 0x096F) return r - 0x0966 + 0x30;
      if (r >= 0x0CE6 && r <= 0x0CEF) return r - 0x0CE6 + 0x30;
      return r;
    }));
