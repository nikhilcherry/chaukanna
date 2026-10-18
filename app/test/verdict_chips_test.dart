import 'package:chaukanna_app/widgets/verdict_chips.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Future<void> _show(
  WidgetTester t, {
  required int pressure,
  String scamType = 'none',
  bool otp = false,
  bool known = false,
}) => t.pumpWidget(
  MaterialApp(
    home: Scaffold(
      body: VerdictChips(scamType: scamType, asksOtp: otp, secrecy: false, knownScammer: known, pressure: pressure),
    ),
  ),
);

void main() {
  testWidgets('a calm call says so', (t) async {
    await _show(t, pressure: 0);
    expect(find.text('No scam signs so far'), findsOneWidget);
  });

  testWidgets('an early guess at a scam type is not shown as a scam', (t) async {
    // A courier saying hello can already be pressure 1 with type "other": that is "watch", not a scam.
    await _show(t, pressure: 1, scamType: 'other');
    expect(find.text('Suspected scam'), findsNothing);
    expect(find.text('Listening closely. No scam so far'), findsOneWidget);
    await _show(t, pressure: 1, scamType: 'digital_arrest');
    expect(find.text('Digital arrest scam'), findsNothing);
  });

  testWidgets('a calm OTP request from a trusted caller shows no danger pill', (t) async {
    await _show(t, pressure: 1, otp: true);
    expect(find.text('Asking for your OTP or PIN'), findsNothing);
  });

  testWidgets('from pressure 2 the scam is named', (t) async {
    await _show(t, pressure: 2, scamType: 'digital_arrest', otp: true);
    expect(find.text('Digital arrest scam'), findsOneWidget);
    expect(find.text('Asking for your OTP or PIN'), findsOneWidget);
  });

  testWidgets('a known scam number is named at once', (t) async {
    await _show(t, pressure: 1, known: true);
    expect(find.text('Known scammer number'), findsOneWidget);
  });
}
