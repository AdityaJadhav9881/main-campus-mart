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
  String _token = '';

  UserProfile? get profile => _profile;
  bool get isLoggedIn => _isLoggedIn;
  bool get isLoading => _isLoading;
  bool get isRestoring => _isRestoring;
  String? get errorMessage => _errorMessage;

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
      _errorMessage = 'Session restore failed: $error';
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
      _errorMessage = 'Could not refresh profile: $error';
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
      _errorMessage = 'Login failed: $error';
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
  }) async {
    _isLoading = true;
    _errorMessage = null;
    notifyListeners();
    try {
      final session = await _api.register(
        name: name,
        email: email,
        password: password,
      );
      await _adoptSession(session);
      return true;
    } on ApiException catch (error) {
      _errorMessage = error.message;
      return false;
    } catch (error) {
      _errorMessage = 'Registration failed: $error';
      return false;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> logout() async {
    _token = '';
    _profile = null;
    _isLoggedIn = false;
    _errorMessage = null;
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
