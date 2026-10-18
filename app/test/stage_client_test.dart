import 'dart:convert';

import 'package:chaukanna_app/services/stage_client.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  test('asks the laptop for a live call in the chosen language', () async {
    late http.Request sent;
    final stage = StageClient(
      baseUrl: 'http://localhost:8787/',
      client: MockClient((r) async {
        sent = r;
        return http.Response('{"ok": true, "lang": "en"}', 200);
      }),
    );
    expect(await stage.startLiveCall('en'), isNull);
    expect(sent.method, 'POST');
    expect(sent.url.toString(), 'http://localhost:8787/console/api/live');
    expect(jsonDecode(sent.body), {'lang': 'en'});
  });

  test("shows the laptop's own reason when it refuses", () async {
    final stage = StageClient(
      baseUrl: 'http://localhost:8787',
      client: MockClient((_) async => http.Response('{"error": "the AI scammer is already calling"}', 409)),
    );
    expect(await stage.startLiveCall('hi'), 'the AI scammer is already calling');
  });

  test('says what to check when the laptop cannot be reached', () async {
    final stage = StageClient(
      baseUrl: 'http://localhost:8787',
      client: MockClient((_) async => throw http.ClientException('Connection refused')),
    );
    expect(await stage.startLiveCall('hi'), contains('adb reverse'));
  });

  test('no STAGE_URL, no button', () => expect(StageClient(baseUrl: '').available, isFalse));
}
