import 'package:chaukanna_app/services/livekit_service.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('a Chaukanna agent is never taken for the caller', () {
    expect(LiveKitTransport.isAgent('agent-chaukanna-safety'), isTrue);
    expect(LiveKitTransport.isCaller('agent-chaukanna-safety'), isFalse);
    expect(LiveKitTransport.isCaller('caller-ai-7b34'), isTrue);
    expect(LiveKitTransport.isCaller('caller-phone'), isTrue);
    expect(LiveKitTransport.isCaller(LiveKitTransport.guardianIdentity), isFalse);
  });
}
