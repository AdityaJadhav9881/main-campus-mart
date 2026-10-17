import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';

/// Amazon-style 0ms local device cache for Feed, Wanted Board, Cart, and Profile.
/// Allows the app to render instantly from device storage without waiting
/// for network roundtrips.
class LocalCacheService {
  static SharedPreferences? _prefs;

  static Future<void> init() async {
    _prefs ??= await SharedPreferences.getInstance();
  }

  // --- Feed Cache ---
  static Future<void> cacheFeedProducts(List<Map<String, dynamic>> rawProducts) async {
    await init();
    try {
      final jsonStr = jsonEncode(rawProducts);
      await _prefs?.setString('cache_feed_products', jsonStr);
    } catch (_) {}
  }

  static Future<List<Map<String, dynamic>>?> getCachedFeedProducts() async {
    await init();
    try {
      final jsonStr = _prefs?.getString('cache_feed_products');
      if (jsonStr == null || jsonStr.isEmpty) return null;
      final decoded = jsonDecode(jsonStr);
      if (decoded is List) {
        return decoded.whereType<Map<String, dynamic>>().toList();
      }
    } catch (_) {}
    return null;
  }

  // --- Wanted Board Cache ---
  static Future<void> cacheWantedRequests(List<Map<String, dynamic>> rawRequests) async {
    await init();
    try {
      final jsonStr = jsonEncode(rawRequests);
      await _prefs?.setString('cache_wanted_requests', jsonStr);
    } catch (_) {}
  }

  static Future<List<Map<String, dynamic>>?> getCachedWantedRequests() async {
    await init();
    try {
      final jsonStr = _prefs?.getString('cache_wanted_requests');
      if (jsonStr == null || jsonStr.isEmpty) return null;
      final decoded = jsonDecode(jsonStr);
      if (decoded is List) {
        return decoded.whereType<Map<String, dynamic>>().toList();
      }
    } catch (_) {}
    return null;
  }

  // --- User Profile Cache ---
  static Future<void> cacheUserProfile(Map<String, dynamic> rawUser) async {
    await init();
    try {
      await _prefs?.setString('cache_user_profile', jsonEncode(rawUser));
    } catch (_) {}
  }

  static Future<Map<String, dynamic>?> getCachedUserProfile() async {
    await init();
    try {
      final jsonStr = _prefs?.getString('cache_user_profile');
      if (jsonStr == null || jsonStr.isEmpty) return null;
      final decoded = jsonDecode(jsonStr);
      if (decoded is Map<String, dynamic>) return decoded;
    } catch (_) {}
    return null;
  }

  // --- Clear on Logout ---
  static Future<void> clearAll() async {
    await init();
    await _prefs?.remove('cache_feed_products');
    await _prefs?.remove('cache_wanted_requests');
    await _prefs?.remove('cache_user_profile');
  }
}

