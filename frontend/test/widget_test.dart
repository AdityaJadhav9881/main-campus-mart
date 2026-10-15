// Smoke test for the CampusMart AI shell (Phase 7 - auth-gated).
//
// Verifies that the provider-wired app boots to the AuthScreen when no
// session is persisted (the new production default), rendering the login /
// sign-up toggle and campus branding.

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:campusmart_ai/main.dart';

void main() {
  testWidgets('app boots to AuthScreen when logged out',
      (WidgetTester tester) async {
    // In-memory prefs so AuthProvider.bootstrap() completes instantly
    // (no saved JWT -> logged out -> AuthScreen).
    SharedPreferences.setMockInitialValues({});

    await tester.pumpWidget(const CampusMartApp());
    // Allow the first frame + AuthProvider bootstrap microtasks to run.
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    await tester.pump(const Duration(milliseconds: 300));

    // CampusMart branding + the Log In / Sign Up toggle must be visible.
    expect(find.text('CampusMart AI'), findsOneWidget);
    expect(find.text('Sign Up'), findsWidgets);
    expect(find.text('College email'), findsOneWidget);
  });
}
