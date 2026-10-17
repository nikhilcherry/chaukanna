import 'dart:convert';

import 'package:chaukanna_app/services/otp_sms.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('classifyOtpSms', () {
    final cases = <(String, String, String?, String, double?)>[
      // sender, body, purpose (null = not an OTP), service, amount
      ('AX-HDFCBK-S', 'OTP for txn of INR 49,999.00 at AMAZON PAY on HDFC Bank card ending 1234 is 482913. Do not share.',
          'payment', 'HDFC Bank', 49999),
      ('VM-SWIGGY', 'Your Swiggy order is out for delivery. Share OTP 4821 with the delivery partner.', 'everyday', 'Swiggy', null),
      ('VM-AMAZON', 'Your Amazon order will be delivered today. OTP 4821. Pay Rs 450 cash on delivery.', 'everyday', 'Amazon', null),
      ('AD-INDANE', 'Your LPG refill DAC is 6142. Share it with the delivery person only.', 'everyday', 'Indane', null),
      ('JD-PHONPE', '482913 is your OTP to reset UPI PIN on PhonePe. Do not share.', 'upi', 'PhonePe', null),
      ('WhatsApp', "Your WhatsApp code: 123-456. Don't share this code with others", 'messaging_account', 'WhatsApp', null),
      ('BZ-UIDAI', 'OTP for Aadhaar (XX1234) is 552211 (valid for 10 mins). Do not share.', 'government_id', 'UIDAI', null),
      ('AX-ICICIB', 'Dear Customer, 734512 is the OTP to add beneficiary on ICICI Bank iMobile. Never share.', 'bank_login',
          'ICICI Bank', null),
      ('+919812345678', 'Your SBI KYC OTP is 662288. Share with our executive to avoid block.', 'bank_login', 'a personal number', null),
      ('VM-NETFLX', 'Your Netflix verification code is 4512.', 'other_login', 'NETFLX', null),
      ('AX-SBIOTP', 'आपका ओटीपी 482913 है, ₹2,000 के भुगतान के लिए', 'payment', 'SBI', 2000),
      ('AX-HDFCBK', 'Rs 5000 debited from a/c XX1234 on 17-10-26 to VPA abc@ybl. Not you? Call 18002586161', null, '', null),
      ('VM-MYNTRA', 'Use code SAVE50 to get Rs 500 off on orders above 1999!', null, '', null),
    ];
    for (final (sender, body, purpose, service, amount) in cases) {
      test('$sender: ${purpose ?? 'not an OTP'}', () {
        final c = classifyOtpSms(sender, body);
        if (purpose == null) {
          expect(c, isNull);
          return;
        }
        expect(c, isNotNull);
        expect(c!.purpose, purpose);
        expect(c.service, service);
        expect(c.amount, amount);
      });
    }
  });

  test('the code never leaves the phone', () {
    final c = classifyOtpSms('AX-HDFCBK-S', 'OTP for txn of INR 49,999.00 at AMAZON PAY is 482913. Do not share.')!;
    final out = jsonEncode(c.toJson());
    expect(out, isNot(contains('482913')));
    expect(c.toJson().keys, unorderedEquals(['purpose', 'service', 'amount']));
  });
}
