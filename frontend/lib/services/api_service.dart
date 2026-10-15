import 'dart:async';

import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import '../models/product.dart';
import '../models/user_profile.dart';

/// Typed wrapper for every non-2xx API response or transport-level failure.
/// Providers catch this to surface clean messages instead of raw exceptions.
class ApiException implements Exception {
  ApiException(this.message, {this.statusCode = 0});

  final String message;
  final int statusCode;

  @override
  String toString() => 'ApiException($statusCode): $message';
}

/// HTTP client for the CampusMart FastAPI backend.
///
/// Responsibilities:
///  * Platform-aware base URL (Android emulator vs. everything else).
///  * Mock-auth bypass flag for local testing without live Firebase.
///  * Uniform timeouts, JSON decoding, and error normalization.
class ApiService {
  ApiService._();

  /// App-wide singleton - stateless besides configuration.
  static final ApiService instance = ApiService._();

  /// Every request waits at most this long before failing with a friendly
  /// timeout message (keeps the UI resilient against a dead backend).
  static const Duration timeout = Duration(seconds: 15);

  /// ---------------------------------------------------------------------------
  /// PHASE 7: MOCK AUTH REMOVED — production uses real campus email/password
  /// JWT auth (POST /auth/register|login) or Firebase ID tokens.
  /// ---------------------------------------------------------------------------
  /// Kept as a constant `false` so existing references compile; the mock-token
  /// bypass path is disabled. Students must log in through AuthScreen.
  static const bool useMockAuth = false;

  /// Bearer token the backend's dev bypass recognizes (`mock-` prefix).
  /// Only honored when the backend has AUTH_DEV_BYPASS=true (local dev).
  static const String mockToken = 'mock-local-dev-token';

  /// Identity the backend issues for mock tokens (must match auth.py).
  static const String mockUid = 'dev-mock-user';
  static const String mockEmail = 'demo.student@campus.edu';
  static const String mockName = 'Demo Student';

  /// Compile-time base-URL override for deployed builds:
  ///   flutter build web --release --dart-define=API_BASE_URL=https://campusmart-api-zia4.onrender.com
  /// When empty the platform heuristics below apply (localhost / emulator).
  static const String _apiBaseUrlOverride =
      String.fromEnvironment('API_BASE_URL');

  /// Resolves the API base URL for the current platform:
  ///  * `--dart-define=API_BASE_URL=...` -> production host (Render/Vercel).
  ///  * Android **emulator** -> 10.0.2.2 (the special alias that points back
  ///    to the host machine's loopback interface from inside the emulator).
  ///  * iOS simulator / macOS / Windows / Linux / web -> 127.0.0.1 (same host).
  ///  * Physical Android device -> replace with your computer's LAN IP, e.g.
  ///    http://192.168.1.20:8000 (10.0.2.2 only exists inside the emulator).
  static String get baseUrl {
    if (_apiBaseUrlOverride.isNotEmpty) return _apiBaseUrlOverride;
    if (kIsWeb) return 'http://127.0.0.1:8000';
    return defaultTargetPlatform == TargetPlatform.android
        ? 'http://10.0.2.2:8000'
        : 'http://127.0.0.1:8000';
  }

  /// Returns the mock token when the bypass flag is on, otherwise the token
  /// supplied by [AuthProvider] (a real Firebase ID token in Phase 5).
  String _resolveToken(String token) => useMockAuth ? mockToken : token;

  Map<String, String> _headers([String? token]) {
    return <String, String>{
      'Content-Type': 'application/json',
      'Accept': 'application/json',
      if (token != null && token.isNotEmpty) 'Authorization': 'Bearer $token',
    };
  }

  // ---------------------------------------------------------------------------
  // Transport helpers
  // ---------------------------------------------------------------------------

  Future<http.Response> _get(String path, {String? token}) async {
    try {
      final uri = Uri.parse('$baseUrl$path');
      return await http.get(uri, headers: _headers(token)).timeout(timeout);
    } on Exception catch (error) {
      throw ApiException(_friendlyTransport(error));
    }
  }

  Future<http.Response> _post(
    String path, {
    required Map<String, dynamic> body,
    String? token,
  }) async {
    try {
      final uri = Uri.parse('$baseUrl$path');
      return await http
          .post(uri, headers: _headers(token), body: jsonEncode(body))
          .timeout(timeout);
    } on Exception catch (error) {
      throw ApiException(_friendlyTransport(error));
    }
  }

  /// Turns low-level network failures into actionable developer messages.
  String _friendlyTransport(Object error) {
    if (error is TimeoutException) {
      return 'Request timed out after ${timeout.inSeconds}s. '
          'Is the backend running at $baseUrl?';
    }
    return 'Cannot reach the CampusMart API at $baseUrl. '
        'Start it with: uvicorn app.main:app --reload';
  }

  /// Extracts FastAPI's {"detail": "..."} error body (or a raw fallback).
  ApiException _apiError(http.Response response) {
    var detail = 'HTTP ${response.statusCode}';
    try {
      final decoded = jsonDecode(response.body);
      if (decoded is Map<String, dynamic> && decoded['detail'] != null) {
        detail = decoded['detail'].toString();
      }
    } on FormatException {
      // Non-JSON body (e.g. proxy HTML) -> keep the HTTP status fallback.
      detail = detail;
    }
    return ApiException(detail, statusCode: response.statusCode);
  }

  Map<String, dynamic> _decodeMap(http.Response response) {
    final decoded = jsonDecode(response.body);
    if (decoded is Map<String, dynamic>) return decoded;
    throw ApiException('Server returned unexpected JSON', statusCode: 500);
  }

  List<dynamic> _decodeList(http.Response response) {
    final decoded = jsonDecode(response.body);
    if (decoded is List<dynamic>) return decoded;
    throw ApiException('Server returned unexpected JSON', statusCode: 500);
  }

  // ---------------------------------------------------------------------------
  // Endpoint methods (per Phase 4 spec)
  // ---------------------------------------------------------------------------

  /// GET /products/ - public feed of active listings.
  Future<List<Product>> fetchActiveProducts() async {
    final response = await _get('/products/');
    if (response.statusCode != 200) throw _apiError(response);
    final items = _decodeList(response);
    return items
        .map((dynamic item) =>
            Product.fromJson(item! as Map<String, dynamic>))
        .toList();
  }

  /// POST /products/ - create a listing. The response contains the
  /// AI-processed values: category, suggested_price, and trust status.
  ///
  /// [token] is the caller's bearer token; ignored while [useMockAuth] is on.
  Future<Product> createProductListing(
    Map<String, dynamic> payload,
    String token,
  ) async {
    final response =
        await _post('/products/', body: payload, token: _resolveToken(token));
    if (response.statusCode != 201) throw _apiError(response);
    return Product.fromJson(_decodeMap(response));
  }

  /// POST /products/upload-image/ - Phase 6 cloud pipeline.
  ///
  /// Sends raw image bytes as multipart/form-data; the backend stores them on
  /// Cloudinary (or the local /uploads fallback) and returns the CDN URL that
  /// the caller plugs into `image_url` when creating the listing.
  ///
  /// Works on every platform (mobile, web, desktop) because bytes - not
  /// dart:io File objects - cross the layer boundary.
  Future<String> uploadListingImage({
    required Uint8List bytes,
    required String filename,
    required String token,
  }) async {
    try {
      final uri = Uri.parse('$baseUrl/products/upload-image/');
      final request = http.MultipartRequest('POST', uri)
        ..headers['Authorization'] = 'Bearer ${_resolveToken(token)}'
        ..files.add(
          http.MultipartFile.fromBytes(
            'file',
            bytes,
            filename: filename,
          ),
        );

      final streamed = await request.send().timeout(timeout);
      final response = await http.Response.fromStream(streamed);
      if (response.statusCode != 200) throw _apiError(response);
      return _decodeMap(response)['image_url'] as String;
    } on ApiException {
      rethrow;
    } on Exception catch (error) {
      throw ApiException(_friendlyTransport(error));
    }
  }

  /// GET /users/{firebase_uid} - public profile incl. trust score.
  /// Returns null when the profile does not exist yet (HTTP 404).
  Future<UserProfile?> fetchUserProfile(String uid) async {
    final response = await _get('/users/${Uri.encodeComponent(uid)}');
    if (response.statusCode == 404) return null;
    if (response.statusCode != 200) throw _apiError(response);
    return UserProfile.fromJson(_decodeMap(response));
  }

  /// POST /users/ - create-or-return the profile for the current identity
  /// (idempotent on the backend: 201 created, 200 if it already exists).
  /// Required in mock mode so a seller row exists before listing creation.
  Future<UserProfile> createUserProfile({
    required String name,
    required String email,
    required String token,
  }) async {
    final response = await _post(
      '/users/',
      body: <String, dynamic>{'name': name, 'email': email},
      token: _resolveToken(token),
    );
    if (response.statusCode != 200 && response.statusCode != 201) {
      throw _apiError(response);
    }
    return UserProfile.fromJson(_decodeMap(response));
  }

  // ---------------------------------------------------------------------------
  // Phase 7 - campus email/password JWT auth
  // ---------------------------------------------------------------------------

  /// POST /auth/register - create a student account, returns JWT + profile.
  Future<AuthSession> register({
    required String name,
    required String email,
    required String password,
  }) async {
    final response = await _post(
      '/auth/register',
      body: <String, dynamic>{
        'name': name,
        'email': email,
        'password': password,
      },
    );
    if (response.statusCode != 201) throw _apiError(response);
    return AuthSession.fromJson(_decodeMap(response));
  }

  /// POST /auth/login - verify credentials, returns JWT + profile.
  Future<AuthSession> login({
    required String email,
    required String password,
  }) async {
    final response = await _post(
      '/auth/login',
      body: <String, dynamic>{'email': email, 'password': password},
    );
    if (response.statusCode != 200) throw _apiError(response);
    return AuthSession.fromJson(_decodeMap(response));
  }

  /// POST /products/{product_id}/purchase - buy/reserve an active listing.
  Future<PurchaseResult> purchaseProduct({
    required String productId,
    required String token,
  }) async {
    final response = await _post(
      '/products/$productId/purchase',
      body: const <String, dynamic>{},
      token: token,
    );
    if (response.statusCode != 200) throw _apiError(response);
    return PurchaseResult.fromJson(_decodeMap(response));
  }
}

/// JWT + profile payload returned by /auth/register and /auth/login.
class AuthSession {
  const AuthSession({required this.accessToken, required this.user});

  factory AuthSession.fromJson(Map<String, dynamic> json) {
    return AuthSession(
      accessToken: json['access_token']?.toString() ?? '',
      user: UserProfile.fromJson(
        json['user'] as Map<String, dynamic>? ?? const <String, dynamic>{},
      ),
    );
  }

  final String accessToken;
  final UserProfile user;
}

/// Response body of POST /products/{id}/purchase.
class PurchaseResult {
  const PurchaseResult({
    required this.transactionId,
    required this.productId,
    required this.finalPrice,
    required this.productStatus,
  });

  factory PurchaseResult.fromJson(Map<String, dynamic> json) {
    return PurchaseResult(
      transactionId: json['transaction_id']?.toString() ?? '',
      productId: json['product_id']?.toString() ?? '',
      finalPrice: (json['final_price'] as num?)?.toDouble() ?? 0,
      productStatus: json['product_status']?.toString() ?? 'sold',
    );
  }

  final String transactionId;
  final String productId;
  final double finalPrice;
  final String productStatus;
}
