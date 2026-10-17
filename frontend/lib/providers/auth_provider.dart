import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/user_profile.dart';
import '../services/api_service.dart';

/// Manages the real student session: JWT persistence, login/register, and
/// profile hydration (Phase 7 - zero mocks).
///
/// Session lifecycle:
///   1. On boot, restore the saved JWT + profile from shared_preferences.
///   2. If a token exists, re-fetch the live profile (trust score freshness).
///   3. `login()` / `register()` call the backend, then persist + hydrate.
///   4. `logout()` clears storage and returns the app to the AuthScreen.
class AuthProvider extends ChangeNotifier {
  AuthProvider({ApiService? api}) : _api = api ?? ApiService.instance;

  static const _tokenKey = 'jwt_token';
  static const _userKey = 'user_json';

  final ApiService _api;

  UserProfile? _profile;
  bool _isLoggedIn = false;
  bool _isLoading = false;
  bool _isRestoring = true;
  String? _errorMessage;
  String? _fallbackOtp;
  String _token = '';

  UserProfile? get profile => _profile;
  bool get isLoggedIn => _isLoggedIn;
  bool get isLoading => _isLoading;
  bool get isRestoring => _isRestoring;
  String? get errorMessage => _errorMessage;
  String? get fallbackOtp => _fallbackOtp;

  void clearFallbackOtp() {
    _fallbackOtp = null;
    notifyListeners();
  }

  /// Bearer token used for every authenticated call (JWT or Firebase).
  String get token => _token;

  // ---------------------------------------------------------------------------
  // Boot: restore persisted session
  // ---------------------------------------------------------------------------
  Future<void> bootstrap() async {
    _isRestoring = true;
    notifyListeners();

    try {
      final prefs = await SharedPreferences.getInstance();
      final savedToken = prefs.getString(_tokenKey);
      final savedUser = prefs.getString(_userKey);

      if (savedToken != null && savedToken.isNotEmpty) {
        _token = savedToken;
        _isLoggedIn = true;
        // Hydrate instantly from cache, then refresh from the server below.
        if (savedUser != null) {
          try {
            _profile = UserProfile.fromJson(
              jsonDecode(savedUser) as Map<String, dynamic>,
            );
          } catch (_) {
            await prefs.remove(_userKey);
          }
        }
        notifyListeners();
        await _refreshFromServer();
      }
    } catch (error) {
      _errorMessage = 'We could not restore your session. Please sign in again.';
    } finally {
      _isRestoring = false;
      notifyListeners();
    }
  }

  Future<void> _refreshFromServer() async {
    if (_profile == null) return;
    try {
      final fresh = await _api.fetchUserProfile(_profile!.firebaseUid);
      if (fresh != null) {
        _profile = fresh;
        await _persistProfile(fresh);
      }
    } on ApiException catch (error) {
      // Keep the cached profile; surface the cause for the retry UI.
      _errorMessage = error.message;
    } catch (error) {
      _errorMessage = 'We could not refresh your profile right now. Please retry in a moment.';
    }
  }

  // ---------------------------------------------------------------------------
  // Login / register / logout
  // ---------------------------------------------------------------------------
  Future<bool> login({required String email, required String password}) async {
    _isLoading = true;
    _errorMessage = null;
    notifyListeners();
    try {
      final session = await _api.login(email: email, password: password);
      await _adoptSession(session);
      return true;
    } on ApiException catch (error) {
      _errorMessage = error.message;
      return false;
    } catch (error) {
      _errorMessage = 'We could not sign you in right now. Check your connection and try again.';
      return false;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<bool> register({
    required String name,
    required String email,
    required String password,
    String? collegeName,
    String? collegeCode,
  }) async {
    _isLoading = true;
    _errorMessage = null;
    notifyListeners();
    try {
      final session = await _api.register(
        name: name,
        email: email,
        password: password,
        collegeName: collegeName,
        collegeCode: collegeCode,
      );
      await _adoptSession(session);
      return true;
    } on ApiException catch (error) {
      _errorMessage = error.message;
      return false;
    } catch (error) {
      _errorMessage = 'We could not create your account right now. Check your connection and try again.';
      return false;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  // ---------------------------------------------------------------------------
  // Task 4 - 2-step email OTP signup (Brevo verification code)
  // ---------------------------------------------------------------------------

  /// Step 1 - park the signup and have the 6-digit code emailed.
  ///
  /// [collegeName]/[collegeCode] are the CET college picked in the required
  /// Sign Up sheet (Task 3); they ride along so the new profile starts
  /// pre-linked to its campus network.
  Future<bool> sendOtp({
    required String name,
    required String email,
    required String password,
    String? collegeName,
    String? collegeCode,
  }) async {
    _isLoading = true;
    _errorMessage = null;
    _fallbackOtp = null;
    notifyListeners();
    try {
      final res = await _api.sendOtp(
        name: name,
        email: email,
        password: password,
        collegeName: collegeName,
        collegeCode: collegeCode,
      );
      _fallbackOtp = res['fallback_otp_code'] as String?;
      return true;
    } on ApiException catch (error) {
      _errorMessage = error.message;
      return false;
    } catch (error) {
      _errorMessage = 'We could not send your verification code right now. Please try again.';
      return false;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// Step 2 - verify the code, then adopt the JWT session it returns.
  Future<bool> verifyOtp({
    required String email,
    required String otpCode,
  }) async {
    _isLoading = true;
    _errorMessage = null;
    notifyListeners();
    try {
      final session = await _api.verifyOtp(email: email, otpCode: otpCode);
      _fallbackOtp = null;
      await _adoptSession(session);
      return true;
    } on ApiException catch (error) {
      _errorMessage = error.message;
      return false;
    } catch (error) {
      _errorMessage = 'We could not verify that code right now. Please try again.';
      return false;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// Fresh code for a signup still waiting on step 2 (server also re-emails).
  Future<bool> resendOtp({required String email}) async {
    _errorMessage = null;
    try {
      final res = await _api.resendOtp(email: email);
      _fallbackOtp = res['fallback_otp_code'] as String?;
      notifyListeners();
      return true;
    } on ApiException catch (error) {
      _errorMessage = error.message;
      notifyListeners();
      return false;
    } catch (error) {
      _errorMessage = 'We could not resend the code right now. Please try again.';
      notifyListeners();
      return false;
    }
  }

  // ---------------------------------------------------------------------------
  // College network (Task 3) - Profile tab editor
  // ---------------------------------------------------------------------------

  /// Repoint this student's campus network after a Profile-tab college swap.
  /// The next listing they publish inherits the new college.
  Future<bool> updateCollege({
    required String collegeName,
    String? collegeCode,
  }) async {
    if (_token.isEmpty) return false;
    _errorMessage = null;
    try {
      final updated = await _api.updateMyCollege(
        token: _token,
        collegeName: collegeName,
        collegeCode: collegeCode,
      );
      _profile = updated;
      await _persistProfile(updated);
      notifyListeners();
      return true;
    } on ApiException catch (error) {
      _errorMessage = error.message;
      notifyListeners();
      return false;
    } catch (error) {
      _errorMessage =
          'We could not update your college right now. Please try again.';
      notifyListeners();
      return false;
    }
  }

  Future<void> logout() async {
    _token = '';
    _profile = null;
    _isLoggedIn = false;
    _errorMessage = null;
    ApiService.clearAccessTerminated();
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove(_tokenKey);
      await prefs.remove(_userKey);
    } catch (_) {
      // Best-effort storage clear - in-memory state is already reset.
    }
    notifyListeners();
  }

  /// Pull-to-refresh on the Profile tab (kept for API compatibility).
  Future<void> refreshProfile() => bootstrap();

  // ---------------------------------------------------------------------------
  // Internals
  // ---------------------------------------------------------------------------
  Future<void> _adoptSession(AuthSession session) async {
    _token = session.accessToken;
    _profile = session.user;
    _isLoggedIn = true;
    ApiService.clearAccessTerminated();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_tokenKey, session.accessToken);
    await _persistProfile(session.user);
  }

  Future<void> _persistProfile(UserProfile profile) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_userKey, jsonEncode(profile.toJson()));
    } catch (_) {
      // Non-fatal: token alone is enough for API calls; profile refreshes
      // will re-hydrate on next boot.
    }
  }
}
