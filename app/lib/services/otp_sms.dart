import 'package:flutter/services.dart';

/// What an OTP SMS on the phone unlocks. Only this leaves the phone (purpose, who sent it, the
/// amount), never the code: it tells a delivery code from a payment OTP better than any guess from
/// the conversation. Purposes and their risk are in CONTRACTS.md §6; the guardian owns the policy.
class OtpSmsContext {
  const OtpSmsContext({required this.purpose, required this.service, this.amount});

  /// payment | upi | card | bank_login | sim | messaging_account | government_id | other_login | everyday
  final String purpose;

  /// Who sent it ("HDFC Bank", "Swiggy", "a personal number").
  final String service;

  /// Rupees, for a payment / UPI OTP.
  final double? amount;

  Map<String, Object?> toJson() => {'purpose': purpose, 'service': service, if (amount != null) 'amount': amount};

  String describe() => [
    purpose.replaceAll('_', ' '),
    if (amount != null) '₹${amount!.toStringAsFixed(0)}',
    if (service.isNotEmpty) 'from $service',
  ].join(', ');
}

RegExp _rx(String p) => RegExp(p, caseSensitive: false);

// It is an OTP SMS only if it says so ("OTP", "verification code", "code: 123-456", "DAC"), so bank
// alerts ("debited from a/c XX1234") and promo codes ("use code SAVE50") are ignored.
final _isOtp = _rx(
  r'\b(otp|one[- ]?time (password|pin|code)|verification code|security code|auth(entication)? code|confirmation code|'
  r'login code|passcode|dac)\b|\b(code|pin)\s*(is|:|-)\s*\d|\d{4,8}\s+is (your|the)\b|is your (\w+ )?(code|otp|pin)\b|'
  r'ओटीपी|ಒಟಿಪಿ|ಓಟಿಪಿ',
);
final _messaging = _rx(r'whats ?app|telegram|\bsignal\b|instagram|facebook|\bgmail\b|google account');
final _sim = _rx(r'\b(e-?sim|sim (swap|change|replacement|upgrade)|upc|unique porting code|porting|mnp)\b');
// Says outright that the code approves a payment. Checked before the delivery words, so an
// "Amazon Pay transaction" OTP is a payment, while "pay Rs 450 cash on delivery" stays a delivery code.
final _strongPay = _rx(
  r'\b(txn|transaction|debit(ed)?|purchase|spent|autopay|e-?mandate|mandate|merchant)\b|for (a |the )?payment|'
  r'to (complete|authori[sz]e|approve|confirm) (the |your |a )?(payment|transaction|purchase)|भुगतान',
);
final _upi = _rx(r'\bupi\b|\bvpa\b|\bbhim\b|\bmpin\b');
final _everyday = _rx(
  r'deliver|\border\b|shipment|package|parcel|swiggy|zomato|blinkit|zepto|instamart|amazon|flipkart|myntra|meesho|'
  r'\bride\b|\btrip\b|\bola\b|\buber\b|rapido|\bcab\b|\bauto\b|\blpg\b|cylinder|indane|bharat ?gas|hp ?gas|\bdac\b|refill|'
  r'pick-?up|technician|urban ?company|service (visit|request)|mygate|visitor|gate ?pass|nobroker',
);
final _amount = _rx(r'(?:rs\.?|inr|₹)\s?([\d,]+(?:\.\d{1,2})?)');
final _card = _rx(r'\b(credit|debit) card\b|\bcard (ending|no|number|xx)|\bcvv\b|3-?d ?secure');
final _bank = _rx(
  r'\bbank\b|a/c|net ?banking|internet banking|mobile banking|beneficiary|\bpayee\b|'
  r'\b(sbi|hdfc|icici|axis|kotak|pnb|canara|baroda|idfc|indusind|federal|bandhan|rbl|union bank|yes bank)\b',
);
final _gov = _rx(
  r'aadhaa?r|uidai|digilocker|umang|epfo|\buan\b|\bpan\b|income ?tax|\bitr\b|pension|jeevan|e-?kyc|\bkyc\b|passport|voter|'
  r'ration|nsdl|cowin|abha',
);

const _senderNames = {
  'HDFCBK': 'HDFC Bank', 'SBIINB': 'SBI', 'SBIOTP': 'SBI', 'SBIUPI': 'SBI', 'ATMSBI': 'SBI', 'CBSSBI': 'SBI',
  'ICICIB': 'ICICI Bank', 'ICICIT': 'ICICI Bank', 'AXISBK': 'Axis Bank', 'KOTAKB': 'Kotak Bank', 'PNBSMS': 'PNB',
  'CANBNK': 'Canara Bank', 'BOBTXN': 'Bank of Baroda', 'BOBSMS': 'Bank of Baroda', 'YESBNK': 'Yes Bank',
  'IDFCFB': 'IDFC First Bank', 'INDUSB': 'IndusInd Bank', 'PAYTMB': 'Paytm', 'PHONPE': 'PhonePe', 'GOOGLE': 'Google',
  'AMAZON': 'Amazon', 'AMZNIN': 'Amazon', 'FLPKRT': 'Flipkart', 'SWIGGY': 'Swiggy', 'ZOMATO': 'Zomato', 'OLACAB': 'Ola',
  'UBERIN': 'Uber', 'RAPIDO': 'Rapido', 'INDANE': 'Indane', 'UIDAI': 'UIDAI', 'AIRTEL': 'Airtel', 'JIOINF': 'Jio',
};

/// Indian business SMS come from DLT headers like "AX-HDFCBK-S"; anything that is a bare phone
/// number is "a personal number" (a "bank OTP" from one is itself a red flag).
String otpSmsService(String sender) {
  final s = sender.trim();
  final dlt = RegExp(r'^[A-Za-z]{2}-([A-Za-z0-9]{3,8})(?:-[A-Za-z])?$').firstMatch(s);
  if (dlt != null) {
    final h = dlt.group(1)!.toUpperCase();
    return _senderNames[h] ?? h;
  }
  if (RegExp(r'^\+?\d[\d -]{5,}$').hasMatch(s)) return 'a personal number';
  return s.length > 20 ? s.substring(0, 20) : s;
}

/// Null when the SMS is not an OTP. Order matters: the most dangerous reading wins.
OtpSmsContext? classifyOtpSms(String sender, String body) {
  if (!_isOtp.hasMatch(body)) return null;
  final service = otpSmsService(sender);
  double? amount() {
    final m = _amount.firstMatch(body);
    return m == null ? null : double.tryParse(m.group(1)!.replaceAll(',', ''));
  }

  String purpose;
  double? amt;
  if (_messaging.hasMatch(body)) {
    purpose = 'messaging_account';
  } else if (_sim.hasMatch(body)) {
    purpose = 'sim';
  } else if (_strongPay.hasMatch(body)) {
    purpose = _upi.hasMatch(body) ? 'upi' : 'payment';
    amt = amount();
  } else if (_upi.hasMatch(body)) {
    purpose = 'upi';
    amt = amount();
  } else if (_everyday.hasMatch(body)) {
    purpose = 'everyday';
  } else if (_amount.hasMatch(body)) {
    purpose = 'payment';
    amt = amount();
  } else if (_card.hasMatch(body)) {
    purpose = 'card';
  } else if (_bank.hasMatch(body)) {
    purpose = 'bank_login';
  } else if (_gov.hasMatch(body)) {
    purpose = 'government_id';
  } else {
    purpose = 'other_login';
  }
  return OtpSmsContext(purpose: purpose, service: service, amount: amt);
}

class IncomingSms {
  const IncomingSms(this.sender, this.body);
  final String sender;
  final String body;
}

/// Incoming SMS from MainActivity's receiver (Android only; asks for RECEIVE_SMS on first listen).
class SmsWatcher {
  static const _channel = EventChannel('chaukanna/sms');

  static Stream<IncomingSms> messages() => _channel.receiveBroadcastStream().map((e) {
    final m = Map<Object?, Object?>.from(e as Map);
    return IncomingSms('${m['sender'] ?? ''}', '${m['body'] ?? ''}');
  });
}
