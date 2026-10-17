import 'dart:async';

import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart' show MediaType;

import '../models/ai_analysis.dart';
import '../models/call_session.dart';
import '../models/cart_models.dart';
import '../models/chat_models.dart';
import '../models/college.dart';
import '../models/notification_item.dart';
import '../models/product.dart';
import '../models/user_profile.dart';
import '../models/wanted_request.dart';

/// Typed wrapper for every non-2xx API response or transport-level failure.
/// Providers catch this to surface clean messages instead of raw exceptions.
class ApiException implements Exception {
  ApiException(this.message, {this.statusCode = 0});

  final String message;
  final int statusCode;

  /// True for the canonical `ACCOUNT_TERMINATED: ...` 403 detail - the UI
  /// raises its non-dismissible "Access Terminated" gate for this.
  bool get isAccessTerminated => statusCode == 403 && message.startsWith('ACCOUNT_TERMINATED');

  @override
  String toString() => 'ApiException($statusCode): $message';
}

/// HTTP client for the CampusMart FastAPI backend.
///
/// Responsibilities:
///  * Platform-aware base URL (Android emulator vs. everything else).
///  * 75s requests with a warm-start retry policy (Render free instances cold
///    boot for 30-60s; GETs re-fire once, unsafe POSTs only on gateway errors).
///  * Uniform timeouts, JSON decoding, and error normalization.
///  * `ACCOUNT_TERMINATED` signal ([accessTerminated]) for the blocked gate.
class ApiService {
  ApiService._();

  /// Shared keep-alive HTTP client (one per isolate).
  static final http.Client _client = http.Client();

  /// App-wide singleton - stateless besides configuration.
  static final ApiService instance = ApiService._();

  /// Every request waits at most this long before failing. Render's cold
  /// starts need well over the old 15s budget, so the app allows 75s and
  /// auto-retries (see [_send]).
  static const Duration timeout = Duration(seconds: 75);

  /// Pause before the single automatic retry of a failed attempt.
  static const Duration _retryDelay = Duration(milliseconds: 450);

  /// HTTP statuses that indicate a transient gateway/wake-up failure worth
  /// one automatic retry for every verb.
  static const Set<int> _retryableStatuses = <int>{502, 503, 504};

  /// Fires when the backend answers a request with the canonical blocked
  /// 403 (`ACCOUNT_TERMINATED: ...`). Listened to by the app shell so the
  /// non-dismissible "Access Terminated" gate can cover every screen.
  static final ValueNotifier<bool> accessTerminated = ValueNotifier<bool>(false);

  /// Clears the terminated gate (call on sign-out / fresh login).
  static void clearAccessTerminated() => accessTerminated.value = false;

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
  // Transport helpers (75s budget + single warm-start retry)
  // ---------------------------------------------------------------------------

  /// Runs [request] under the warm-start retry policy:
  ///
  ///  * **GET** - retried once on timeout, on 502/503/504, and on a refused
  ///    connection (read-only, always safe; this is the Render cold-start path).
  ///  * **POST/DELETE** - retried once only when the request verifiably never
  ///    reached the app (refused connection) or the gateway failed it
  ///    (502/503/504). A *timeout* is NOT retried for unsafe verbs so a slow
  ///    success can never double-create a listing or purchase.
  Future<http.Response> _send(
    String method,
    String path, {
    Map<String, dynamic>? body,
    String? token,
  }) async {
    final uri = Uri.parse('$baseUrl$path');
    final retryOnTimeout = method == 'GET';
    final payload = body == null ? null : jsonEncode(body);
    final isAi = path.startsWith('/ai/') || path.contains('/ai');
    final reqTimeout = isAi ? const Duration(seconds: 25) : timeout;

    for (var attempt = 0; ; attempt++) {
      try {
        final request = http.Request(method, uri)
          ..headers.addAll(_headers(token));
        if (payload != null) request.body = payload;
        final streamed = await _client.send(request).timeout(reqTimeout);
        final response = await http.Response.fromStream(streamed);

        if (attempt == 0 && _retryableStatuses.contains(response.statusCode)) {
          await Future<void>.delayed(_retryDelay);
          continue;
        }
        return response;
      } on TimeoutException {
        if (attempt == 0 && retryOnTimeout) {
          await Future<void>.delayed(_retryDelay);
          continue;
        }
        throw ApiException(_friendlyTimeout(method, isAi: isAi), statusCode: 408);
      } on Exception catch (error) {
        if (attempt == 0 && _isConnectionFailure(error)) {
          await Future<void>.delayed(_retryDelay);
          continue;
        }
        throw ApiException(_friendlyTransport(error, isAi: isAi));
      }
    }
  }

  Future<http.Response> _get(String path, {String? token}) =>
      _send('GET', path, token: token);

  Future<http.Response> _post(
    String path, {
    required Map<String, dynamic> body,
    String? token,
  }) =>
      _send('POST', path, body: body, token: token);

  Future<http.Response> _delete(String path, {String? token}) =>
      _send('DELETE', path, token: token);

  /// True when [error] means the request never left the device (safe to
  /// retry for any verb). Works cross-platform without importing dart:io.
  static bool _isConnectionFailure(Object error) {
    if (error is http.ClientException) return true;
    final text = error.toString().toLowerCase();
    return text.contains('connection refused') ||
        text.contains('connection reset') ||
        text.contains('failed host lookup') ||
        text.contains('network is unreachable') ||
        text.contains('connection closed');
  }

  /// Friendly timeout copy - deliberately free of server internals; students
  /// only need to know the marketplace is waking up and to tap again.
  String _friendlyTimeout(String method, {bool isAi = false}) {
    if (isAi) {
      return 'The AI assistant took a moment too long to respond. Please try again.';
    }
    if (method == 'GET') {
      return 'Still waking up! The Campus Mart Ai marketplace can take up to '
          'a minute to start on first launch - please try again in a few '
          'seconds.';
    }
    return 'That took too long to reach the server. Please check your '
        'connection and try again - do not resubmit yet if a listing or '
        'purchase was in progress.';
  }

  /// Turns low-level network failures into actionable, student-safe messages.
  String _friendlyTransport(Object error, {bool isAi = false}) {
    if (error is TimeoutException) {
      return _friendlyTimeout('GET', isAi: isAi);
    }
    if (isAi) {
      return 'Could not connect to CampusMart AI. Check your internet connection.';
    }
    return 'Cannot reach Campus Mart Ai right now. Check your internet '
        'connection and try again.';
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
    final error = ApiException(detail, statusCode: response.statusCode);
    if (error.isAccessTerminated) accessTerminated.value = true;
    return error;
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
  ///
  /// Optional server-side search (added for the Discover search bar):
  ///  * [query]  -> `?q=` title/description/category/tag ILIKE match.
  ///  * [category] -> `?category=` exact category filter (skip "All").
  ///  * [college] -> `?college=` exact campus filter for the "🎓 My College"
  ///    network toggle.
  Future<List<Product>> fetchActiveProducts({
    String? query,
    String? category,
    String? college,
    String? branch,
    String? academicYear,
  }) async {
    final params = <String, String>{};
    final trimmedQuery = query?.trim() ?? '';
    if (trimmedQuery.isNotEmpty) params['q'] = trimmedQuery;
    final trimmedCategory = category?.trim() ?? '';
    if (trimmedCategory.isNotEmpty && trimmedCategory != 'All') {
      params['category'] = trimmedCategory;
    }
    final trimmedCollege = college?.trim() ?? '';
    if (trimmedCollege.isNotEmpty) params['college'] = trimmedCollege;
    final trimmedBranch = branch?.trim() ?? '';
    if (trimmedBranch.isNotEmpty && trimmedBranch != 'All Branches') {
      params['branch'] = trimmedBranch;
    }
    final trimmedYear = academicYear?.trim() ?? '';
    if (trimmedYear.isNotEmpty && trimmedYear != 'All Years') {
      params['academic_year'] = trimmedYear;
    }
    final path = params.isEmpty
        ? '/products/'
        : '/products/?${params.entries.map((e) => '${Uri.encodeQueryComponent(e.key)}=${Uri.encodeQueryComponent(e.value)}').join('&')}';
    final response = await _get(path);
    if (response.statusCode != 200) throw _apiError(response);
    final items = _decodeList(response);
    return items
        .map((dynamic item) =>
            Product.fromJson(item! as Map<String, dynamic>))
        .toList();
  }

  /// GET /products/{product_id} - single listing (bell-notification deep
  /// links). Returns null when the listing no longer exists.
  Future<Product?> fetchProductById(String productId) async {
    final response = await _get('/products/$productId');
    if (response.statusCode == 404) return null;
    if (response.statusCode != 200) throw _apiError(response);
    return Product.fromJson(_decodeMap(response));
  }

  /// POST /products/analyze-images - the 4-angle Vision AI inspection.
  ///
  /// JSON body (NOT multipart): the photos must already be uploaded through
  /// [uploadListingImage] so [imageUrls] carries their CDN URLs. Fewer than
  /// 4 URLs is rejected server-side with HTTP 400 and a clear message.
  /// Returns the strict-JSON auto-fill for the Sell form.
  Future<AiPhotoAnalysis> analyzeImages({
    required List<String> imageUrls,
    String? title,
    String? description,
    String? condition,
    required String token,
  }) async {
    final response = await _post(
      '/products/analyze-images',
      body: <String, dynamic>{
        'image_urls': imageUrls,
        if (title != null && title.trim().isNotEmpty) 'title': title.trim(),
        if (description != null && description.trim().isNotEmpty)
          'description': description.trim(),
        if (condition != null && condition.trim().isNotEmpty)
          'condition': condition.trim(),
      },
      token: token,
    );
    if (response.statusCode != 200) throw _apiError(response);
    return AiPhotoAnalysis.fromJson(_decodeMap(response));
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
  ///
  /// The multipart part ALWAYS carries an explicit `Content-Type`. Without it
  /// browsers and several Android HTTP stacks fall back to
  /// `application/octet-stream`, which used to make the backend reject the
  /// photo with a 400 (the "application/octet-stream" upload bug).
  Future<String> uploadListingImage({
    required Uint8List bytes,
    required String filename,
    required String token,
  }) async {
    // Multipart bodies are single-use, so each attempt rebuilds the request.
    // Retry policy: once on a refused connection or 502/503/504 (the photo
    // never landed) - never on timeout, since Cloudinary may hold a copy.
    for (var attempt = 0; ; attempt++) {
      try {
        final uri = Uri.parse('$baseUrl/products/upload-image/');
        final request = http.MultipartRequest('POST', uri)
          ..headers['Authorization'] = 'Bearer ${_resolveToken(token)}'
          ..files.add(
            http.MultipartFile.fromBytes(
              'file',
              bytes,
              filename: filename,
              contentType: _imageMediaType(bytes, filename),
            ),
          );

        final streamed = await _client.send(request).timeout(timeout);
        final response = await http.Response.fromStream(streamed);
        if (attempt == 0 && _retryableStatuses.contains(response.statusCode)) {
          await Future<void>.delayed(_retryDelay);
          continue;
        }
        if (response.statusCode != 200) throw _apiError(response);
        return _decodeMap(response)['image_url'] as String;
      } on ApiException {
        rethrow;
      } on TimeoutException {
        throw ApiException(
          'The photo upload took too long. Check your connection and retry '
          'this photo.',
          statusCode: 408,
        );
      } on Exception catch (error) {
        if (attempt == 0 && _isConnectionFailure(error)) {
          await Future<void>.delayed(_retryDelay);
          continue;
        }
        throw ApiException(_friendlyTransport(error));
      }
    }
  }

  /// Resolves the media type for an uploaded photo.
  ///
  /// Priority: filename extension (`.jpg`, `.jpeg`, `.png`, `.webp`, `.gif`,
  /// `.heic`) -> leading magic bytes (JPEG/PNG/GIF/WebP) -> safe JPEG default.
  static MediaType _imageMediaType(Uint8List bytes, String filename) {
    final lower = filename.toLowerCase();
    if (lower.endsWith('.png')) return MediaType('image', 'png');
    if (lower.endsWith('.webp')) return MediaType('image', 'webp');
    if (lower.endsWith('.gif')) return MediaType('image', 'gif');
    if (lower.endsWith('.heic') || lower.endsWith('.heif')) {
      return MediaType('image', 'heic');
    }
    if (lower.endsWith('.jpg') || lower.endsWith('.jpeg')) {
      return MediaType('image', 'jpeg');
    }

    if (bytes.length >= 4) {
      final isPng = bytes[0] == 0x89 &&
          bytes[1] == 0x50 &&
          bytes[2] == 0x4E &&
          bytes[3] == 0x47;
      if (isPng) return MediaType('image', 'png');

      final isGif = bytes[0] == 0x47 && // G
          bytes[1] == 0x49 && // I
          bytes[2] == 0x46 && // F
          bytes[3] == 0x38; // 8
      if (isGif) return MediaType('image', 'gif');

      final isJpeg = bytes[0] == 0xFF && bytes[1] == 0xD8 && bytes[2] == 0xFF;
      if (isJpeg) return MediaType('image', 'jpeg');

      if (bytes.length >= 12) {
        // "RIFF....WEBP"
        final isWebp = bytes[0] == 0x52 && // R
            bytes[1] == 0x49 && // I
            bytes[2] == 0x46 && // F
            bytes[3] == 0x46 && // F
            bytes[8] == 0x57 && // W
            bytes[9] == 0x45 && // E
            bytes[10] == 0x42 && // B
            bytes[11] == 0x50; // P
        if (isWebp) return MediaType('image', 'webp');
      }
    }
    return MediaType('image', 'jpeg');
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
  ///
  /// [collegeName]/[collegeCode] carry the CET college picked in the Sign Up
  /// sheet (required by the UI; optional server-side for older clients).
  Future<AuthSession> register({
    required String name,
    required String email,
    required String password,
    String? collegeName,
    String? collegeCode,
  }) async {
    final response = await _post(
      '/auth/register',
      body: <String, dynamic>{
        'name': name,
        'email': email,
        'password': password,
        if (collegeName != null && collegeName.trim().isNotEmpty)
          'college_name': collegeName.trim(),
        if (collegeCode != null && collegeCode.trim().isNotEmpty)
          'college_code': collegeCode.trim(),
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
  ///
  /// The 4-step checkout sheet passes the optional handover details; quick-buy
  /// callers send nothing and the order still goes through.
  Future<PurchaseResult> purchaseProduct({
    required String productId,
    required String token,
    String? deliveryAddress,
    String? hostelOrLandmark,
    String? contactPhone,
    String? paymentMethod,
    String? upiReference,
    String? otpCode,
    String? notes,
  }) async {
    final response = await _post(
      '/products/$productId/purchase',
      body: <String, dynamic>{
        if (deliveryAddress != null && deliveryAddress.trim().isNotEmpty)
          'delivery_address': deliveryAddress.trim(),
        if (hostelOrLandmark != null && hostelOrLandmark.trim().isNotEmpty)
          'hostel_or_landmark': hostelOrLandmark.trim(),
        if (contactPhone != null && contactPhone.trim().isNotEmpty)
          'contact_phone': contactPhone.trim(),
        if (paymentMethod != null && paymentMethod.trim().isNotEmpty)
          'payment_method': paymentMethod.trim(),
        if (upiReference != null && upiReference.trim().isNotEmpty)
          'upi_reference': upiReference.trim(),
        if (otpCode != null && otpCode.trim().isNotEmpty)
          'otp_code': otpCode.trim(),
        if (notes != null && notes.trim().isNotEmpty) 'notes': notes.trim(),
      },
      token: token,
    );
    if (response.statusCode != 200) throw _apiError(response);
    return PurchaseResult.fromJson(_decodeMap(response));
  }

  /// GET /transactions/my - the logged-in student's bought + sold history.
  Future<TransactionHistory> fetchMyTransactions({required String token}) async {
    final response = await _get('/transactions/my', token: token);
    if (response.statusCode != 200) throw _apiError(response);
    final body = _decodeMap(response);
    return TransactionHistory.fromJson(body);
  }

  /// DELETE /products/{product_id} - remove one of your own listings.
  /// Returns normally on HTTP 204; throws [ApiException] otherwise
  /// (403 for someone else's item, 400 when it already has buyers).
  Future<void> deleteProduct({
    required String productId,
    required String token,
  }) async {
    final response = await _delete('/products/$productId', token: token);
    if (response.statusCode != 204 && response.statusCode != 200) {
      throw _apiError(response);
    }
  }

  // ---------------------------------------------------------------------------
  // Task 4 - OTP signup (Brevo 6-digit email verification)
  // ---------------------------------------------------------------------------

  /// POST /auth/send-otp - step 1: park the signup + email a 6-digit code.
  /// Throws 409 when the address already has an account.
  Future<Map<String, dynamic>> sendOtp({
    required String name,
    required String email,
    required String password,
    String? collegeName,
    String? collegeCode,
  }) async {
    final response = await _post(
      '/auth/send-otp',
      body: <String, dynamic>{
        'name': name.trim(),
        'email': email.trim(),
        'password': password,
        if (collegeName != null && collegeName.trim().isNotEmpty)
          'college_name': collegeName.trim(),
        if (collegeCode != null && collegeCode.trim().isNotEmpty)
          'college_code': collegeCode.trim(),
      },
    );
    if (response.statusCode != 200) throw _apiError(response);
    return _decodeMap(response);
  }

  /// POST /auth/verify-otp - step 2: validate the code, create the active
  /// account, and adopt the returned JWT session (HTTP 201).
  Future<AuthSession> verifyOtp({
    required String email,
    required String otpCode,
  }) async {
    final response = await _post(
      '/auth/verify-otp',
      body: <String, dynamic>{'email': email.trim(), 'otp_code': otpCode},
    );
    if (response.statusCode != 201) throw _apiError(response);
    return AuthSession.fromJson(_decodeMap(response));
  }

  /// POST /auth/resend-otp - fresh code for a signup still on step 2.
  Future<Map<String, dynamic>> resendOtp({required String email}) async {
    final response = await _post(
      '/auth/resend-otp',
      body: <String, dynamic>{'email': email.trim()},
    );
    if (response.statusCode != 200) throw _apiError(response);
    return _decodeMap(response);
  }

  // ---------------------------------------------------------------------------
  // Task 5 - buyer-seller chat + Ask CampusMart AI
  // ---------------------------------------------------------------------------

  /// POST /chats/messages - send one message on a product thread (201).
  ///
  /// [imageUrl] attaches a photo (already uploaded via [uploadListingImage])
  /// WhatsApp-style; the text [message] may be empty for a photo-only send.
  Future<ChatMessage> sendMessage({
    required String productId,
    required String receiverId,
    required String message,
    required String token,
    String? imageUrl,
  }) async {
    final response = await _post(
      '/chats/messages',
      body: <String, dynamic>{
        'product_id': productId,
        'receiver_id': receiverId,
        'message': message,
        if (imageUrl != null && imageUrl.trim().isNotEmpty)
          'image_url': imageUrl.trim(),
      },
      token: token,
    );
    if (response.statusCode != 201) throw _apiError(response);
    return ChatMessage.fromJson(_decodeMap(response));
  }

  /// GET /chats/conversations - my inbox threads, newest first.
  Future<List<Conversation>> fetchConversations({required String token}) async {
    final response = await _get('/chats/conversations', token: token);
    if (response.statusCode != 200) throw _apiError(response);
    return _decodeList(response)
        .map((dynamic row) =>
            Conversation.fromJson(row! as Map<String, dynamic>))
        .toList();
  }

  /// GET /chats/messages/{product_id}/{other_user_id} - full thread history
  /// (opening it also clears the receiver's unread badge server-side).
  Future<List<ChatMessage>> fetchThreadMessages({
    required String productId,
    required String otherUserId,
    required String token,
  }) async {
    final response = await _get(
      '/chats/messages/${Uri.encodeComponent(productId)}/'
      '${Uri.encodeComponent(otherUserId)}',
      token: token,
    );
    if (response.statusCode != 200) throw _apiError(response);
    return _decodeList(response)
        .map((dynamic row) =>
            ChatMessage.fromJson(row! as Map<String, dynamic>))
        .toList();
  }

  /// POST /ai/chat - Ask CampusMart AI. Falls back to the catalog-aware
  /// local assistant (source='catalog') when no live LLM is configured.
  ///
  /// [imageUrl] attaches one photo (already uploaded via [uploadListingImage])
  /// so the assistant can inspect it; [message] may be empty then.
  /// [sessionId] appends the turn to a saved conversation; the response then
  /// carries the session id + (auto) title for the history drawer.
  Future<AiChatReply> askAi({
    required String message,
    List<AiChatTurn> history = const <AiChatTurn>[],
    String? token,
    String? imageUrl,
    String? sessionId,
  }) async {
    try {
      final response = await _post(
        '/ai/chat',
        body: <String, dynamic>{
          'message': message,
          'history': history.map((turn) => turn.toJson()).toList(),
          if (imageUrl != null && imageUrl.trim().isNotEmpty)
            'image_url': imageUrl.trim(),
          if (sessionId != null && sessionId.trim().isNotEmpty)
            'session_id': sessionId.trim(),
        },
        token: token,
      );
      if (response.statusCode != 200) throw _apiError(response);
      return AiChatReply.fromJson(_decodeMap(response));
    } catch (_) {
      return _clientSideAiChatFallback(message, sessionId: sessionId);
    }
  }

  AiChatReply _clientSideAiChatFallback(String message, {String? sessionId}) {
    final lower = message.trim().toLowerCase();
    String reply;

    if (lower.startsWith('hi') ||
        lower.startsWith('hello') ||
        lower.startsWith('hey') ||
        lower == 'sup' ||
        lower == 'namaste') {
      reply = "Hello! 👋 I'm **CampusMart AI**, your campus marketplace companion.\n\n"
          "I can help you:\n"
          "• **Find College Gear**: Check student listings for textbooks, calculators, drafters, electronics, cycles, etc.\n"
          "• **Fair Pricing**: Verify fair resale prices in ₹ before buying or selling.\n"
          "• **Post on Wanted Board**: Request gear from students across campus.\n\n"
          "What are you looking for today?";
    } else if (lower.contains('calc') || lower.contains('casio')) {
      reply =
          "Scientific calculators (like Casio FX-991EX / MS) typically resale for **₹400 – ₹850** depending on condition and battery life. Check the Discover tab to see active student listings!";
    } else if (lower.contains('draft') || lower.contains('roller')) {
      reply =
          "Engineering mini drafters typically sell on campus for **₹250 – ₹450**. Check that the scale arms and clamps are intact before meetup.";
    } else if (lower.contains('book') || lower.contains('textbook')) {
      reply =
          "Course textbooks and exam guides generally resale for **₹200 – ₹450** (about 40%–60% of original MRP). You can also post an urgent request on the Wanted board!";
    } else if (lower.contains('price') ||
        lower.contains('cost') ||
        lower.contains('worth') ||
        lower.contains('how much') ||
        lower.contains('rate')) {
      reply =
          "Here are typical fair second-hand campus resale benchmarks across Indian engineering/degree colleges:\n\n"
          "• **Scientific Calculator**: ₹400 – ₹850\n"
          "• **Engineering Mini Drafter**: ₹250 – ₹450\n"
          "• **Academic Textbooks**: ₹200 – ₹450\n"
          "• **Bluetooth Speakers**: ₹1,800 – ₹5,500\n"
          "• **Student Laptops**: ₹16,000 – ₹32,000\n\n"
          "Would you like an estimate on a specific item?";
    } else {
      reply =
          "I'm here to help with campus gear, textbook advice, and fair resale prices in ₹. Feel free to search products on Discover or post a request on the Wanted board!";
    }

    return AiChatReply(
      reply: reply,
      source: 'catalog',
      sessionId: sessionId,
      sessionTitle: sessionId != null ? null : 'Campus Marketplace Chat',
    );
  }

  // ---------------------------------------------------------------------------
  // College network - CET Cell directory + custom colleges
  // ---------------------------------------------------------------------------

  /// GET /colleges?q=&city=&allow_custom= - ranked CET college search for the
  /// picker sheet. [allowCustom] echoes unmatched typed text back as a
  /// pickable "custom college" entry so unlisted institutes can sign up.
  Future<CollegeSearchResult> searchColleges({
    String q = '',
    String city = '',
    bool allowCustom = false,
  }) async {
    final params = <String, String>{
      if (q.trim().isNotEmpty) 'q': q.trim(),
      if (city.trim().isNotEmpty && city.trim() != 'All') 'city': city.trim(),
      if (allowCustom) 'allow_custom': 'true',
    };
    final path = params.isEmpty
        ? '/colleges'
        : '/colleges?${params.entries.map((e) => '${Uri.encodeQueryComponent(e.key)}=${Uri.encodeQueryComponent(e.value)}').join('&')}';
    final response = await _get(path);
    if (response.statusCode != 200) throw _apiError(response);
    return CollegeSearchResult.fromJson(_decodeMap(response));
  }

  /// PATCH /users/me - update my profile college (Profile tab editor).
  Future<UserProfile> updateMyCollege({
    required String token,
    String? collegeName,
    String? collegeCode,
  }) async {
    final response = await _send(
      'PATCH',
      '/users/me',
      body: <String, dynamic>{
        'college_name': (collegeName ?? '').trim(),
        'college_code': (collegeCode ?? '').trim(),
      },
      token: token,
    );
    if (response.statusCode != 200) throw _apiError(response);
    return UserProfile.fromJson(_decodeMap(response));
  }

  // ---------------------------------------------------------------------------
  // Action OTP (verify before publish / purchase)
  // ---------------------------------------------------------------------------

  /// POST /auth/send-action-otp - email a 6-digit code for a sell/purchase.
  /// Offline-safe: when Brevo is unkeyed the response carries
  /// `fallback_otp_code` which the sheet shows for instant verification.
  Future<Map<String, dynamic>> sendActionOtp({
    required String actionType, // 'sell' | 'purchase'
    required String token,
    String? itemTitle,
  }) async {
    final response = await _post(
      '/auth/send-action-otp',
      body: <String, dynamic>{
        'action_type': actionType,
        if (itemTitle != null && itemTitle.trim().isNotEmpty)
          'item_title': itemTitle.trim(),
      },
      token: token,
    );
    if (response.statusCode != 200) throw _apiError(response);
    return _decodeMap(response);
  }

  /// POST /auth/verify-action-otp - validate the code, mint an action token.
  Future<ActionOtpResult> verifyActionOtp({
    required String otpCode,
    required String token,
    String actionType = 'purchase',
  }) async {
    final response = await _post(
      '/auth/verify-action-otp',
      body: <String, dynamic>{
        'otp_code': otpCode.trim(),
        'action_type': actionType,
      },
      token: token,
    );
    if (response.statusCode != 200) throw _apiError(response);
    final body = _decodeMap(response);
    return ActionOtpResult(
      verified: body['verified'] == true,
      actionToken: body['action_token']?.toString() ?? '',
    );
  }

  // ---------------------------------------------------------------------------
  // Notifications (bell icon)
  // ---------------------------------------------------------------------------

  /// GET /notifications/ - newest-first feed + unread badge count.
  Future<NotificationFeed> fetchNotifications({
    required String token,
    bool markPushed = false,
  }) async {
    final path = markPushed ? '/notifications/?mark_pushed=true' : '/notifications/';
    final response = await _get(path, token: token);
    if (response.statusCode != 200) throw _apiError(response);
    return NotificationFeed.fromJson(_decodeMap(response));
  }

  /// POST /notifications/{id}/read - mark one alert as read.
  Future<void> markNotificationRead({
    required String notificationId,
    required String token,
  }) async {
    final response = await _post(
      '/notifications/$notificationId/read',
      body: const <String, dynamic>{},
      token: token,
    );
    if (response.statusCode != 200) throw _apiError(response);
  }

  /// POST /notifications/read-all - clear the unread badge.
  Future<void> markAllNotificationsRead({required String token}) async {
    final response = await _post(
      '/notifications/read-all',
      body: const <String, dynamic>{},
      token: token,
    );
    if (response.statusCode != 200) throw _apiError(response);
  }

  // ---------------------------------------------------------------------------
  // Cart
  // ---------------------------------------------------------------------------

  /// GET /cart/ - my cart with full product cards + ₹ total.
  Future<CartSummary> fetchCart({required String token}) async {
    final response = await _get('/cart/', token: token);
    if (response.statusCode != 200) throw _apiError(response);
    return CartSummary.fromJson(_decodeMap(response));
  }

  /// POST /cart/{product_id} - park a listing in the cart (idempotent).
  Future<CartSummary> addToCart({
    required String productId,
    required String token,
  }) async {
    final response = await _post(
      '/cart/$productId',
      body: const <String, dynamic>{},
      token: token,
    );
    if (response.statusCode != 201) throw _apiError(response);
    return CartSummary.fromJson(_decodeMap(response));
  }

  /// DELETE /cart/{product_id} - remove one listing (idempotent).
  Future<CartSummary> removeFromCart({
    required String productId,
    required String token,
  }) async {
    final response = await _delete('/cart/$productId', token: token);
    if (response.statusCode != 200) throw _apiError(response);
    return CartSummary.fromJson(_decodeMap(response));
  }

  // ---------------------------------------------------------------------------
  // Ask-AI saved sessions (history drawer)
  // ---------------------------------------------------------------------------

  /// GET /ai/sessions - my saved conversations, newest first.
  Future<List<AiSession>> fetchAiSessions({required String token}) async {
    final response = await _get('/ai/sessions', token: token);
    if (response.statusCode != 200) throw _apiError(response);
    return _decodeList(response)
        .whereType<Map<String, dynamic>>()
        .map(AiSession.fromJson)
        .toList(growable: false);
  }

  /// POST /ai/sessions - start a fresh conversation row.
  Future<AiSession> createAiSession({required String token}) async {
    final response = await _post(
      '/ai/sessions',
      body: const <String, dynamic>{},
      token: token,
    );
    if (response.statusCode != 201) throw _apiError(response);
    return AiSession.fromJson(_decodeMap(response));
  }

  /// GET /ai/sessions/{id} - full transcript for replay.
  Future<AiSessionDetail> fetchAiSession({
    required String sessionId,
    required String token,
  }) async {
    final response = await _get('/ai/sessions/$sessionId', token: token);
    if (response.statusCode != 200) throw _apiError(response);
    return AiSessionDetail.fromJson(_decodeMap(response));
  }

  /// DELETE /ai/sessions/{id} - remove a saved conversation.
  Future<void> deleteAiSession({
    required String sessionId,
    required String token,
  }) async {
    final response = await _delete('/ai/sessions/$sessionId', token: token);
    if (response.statusCode != 204 && response.statusCode != 200) {
      throw _apiError(response);
    }
  }

  // ---------------------------------------------------------------------------
  // In-app calls
  // ---------------------------------------------------------------------------

  /// POST /chats/call-event - log a finished call into the product thread.
  Future<ChatMessage> recordCallEvent({
    required String productId,
    required String receiverId,
    required String callType, // 'voice' | 'video'
    required String token,
    String status = 'completed',
    int durationSeconds = 0,
  }) async {
    final response = await _post(
      '/chats/call-event',
      body: <String, dynamic>{
        'product_id': productId,
        'receiver_id': receiverId,
        'call_type': callType,
        'status': status,
        'duration_seconds': durationSeconds,
      },
      token: token,
    );
    if (response.statusCode != 201) throw _apiError(response);
    return ChatMessage.fromJson(_decodeMap(response));
  }

  // ---------------------------------------------------------------------------
  // Calls & Signaling
  // ---------------------------------------------------------------------------
  Future<CallSession> initiateCall({
    required String receiverId,
    String? productId,
    String callType = 'voice',
    String? sdpOffer,
    required String token,
  }) async {
    final response = await _post(
      '/calls/initiate',
      body: <String, dynamic>{
        'receiver_id': receiverId,
        if (productId != null) 'product_id': productId,
        'call_type': callType,
        if (sdpOffer != null) 'sdp_offer': sdpOffer,
      },
      token: token,
    );
    if (response.statusCode != 201 && response.statusCode != 200) {
      throw _apiError(response);
    }
    return CallSession.fromJson(_decodeMap(response));
  }

  Future<CallSession?> fetchIncomingCall({required String token}) async {
    final response = await _get('/calls/incoming', token: token);
    if (response.statusCode == 200) {
      final text = response.body.trim();
      if (text.isEmpty || text == 'null') return null;
      return CallSession.fromJson(_decodeMap(response));
    }
    return null;
  }

  Future<CallSession> fetchCallSession(String callId, {required String token}) async {
    final response = await _get('/calls/$callId', token: token);
    if (response.statusCode != 200) throw _apiError(response);
    return CallSession.fromJson(_decodeMap(response));
  }

  Future<CallSession> answerCall(
    String callId, {
    String? sdpAnswer,
    required String token,
  }) async {
    final response = await _post(
      '/calls/$callId/answer',
      body: <String, dynamic>{
        if (sdpAnswer != null) 'sdp_answer': sdpAnswer,
      },
      token: token,
    );
    if (response.statusCode != 200) throw _apiError(response);
    return CallSession.fromJson(_decodeMap(response));
  }

  Future<CallSession> cancelCall(String callId, {required String token}) async {
    final response = await _post(
      '/calls/$callId/cancel',
      body: <String, dynamic>{},
      token: token,
    );
    if (response.statusCode != 200) throw _apiError(response);
    return CallSession.fromJson(_decodeMap(response));
  }

  Future<CallSession> declineCall(String callId, {required String token}) async {
    final response = await _post(
      '/calls/$callId/decline',
      body: <String, dynamic>{},
      token: token,
    );
    if (response.statusCode != 200) throw _apiError(response);
    return CallSession.fromJson(_decodeMap(response));
  }

  Future<CallSession> endCall(String callId, {required String token}) async {
    final response = await _post(
      '/calls/$callId/end',
      body: <String, dynamic>{},
      token: token,
    );
    if (response.statusCode != 200) throw _apiError(response);
    return CallSession.fromJson(_decodeMap(response));
  }

  Future<Map<String, dynamic>> signalCall(
    String callId, {
    String? sdpOffer,
    String? sdpAnswer,
    String? iceCandidate,
    bool? isCaller,
    String? audioChunk,
    required String token,
  }) async {
    final response = await _post(
      '/calls/$callId/signal',
      body: <String, dynamic>{
        if (sdpOffer != null) 'sdp_offer': sdpOffer,
        if (sdpAnswer != null) 'sdp_answer': sdpAnswer,
        if (iceCandidate != null) 'ice_candidate': iceCandidate,
        if (isCaller != null) 'is_caller': isCaller,
        if (audioChunk != null) 'audio_chunk': audioChunk,
      },
      token: token,
    );
    if (response.statusCode != 200) throw _apiError(response);
    return _decodeMap(response);
  }

  Future<Map<String, dynamic>> fetchCallSignal(
    String callId, {
    required String token,
  }) async {
    final response = await _get('/calls/$callId/signal', token: token);
    if (response.statusCode != 200) throw _apiError(response);
    return _decodeMap(response);
  }

  // ---------------------------------------------------------------------------
  // Want to Buy (WTB) Campus Request Board
  // ---------------------------------------------------------------------------
  Future<List<WantedRequest>> fetchWantedRequests({
    String? collegeName,
    String? category,
    String? branch,
    String? academicYear,
  }) async {
    final params = <String, String>{};
    if (collegeName != null && collegeName.trim().isNotEmpty) {
      params['college_name'] = collegeName.trim();
    }
    if (category != null && category.trim().isNotEmpty && category != 'All') {
      params['category'] = category.trim();
    }
    if (branch != null && branch.trim().isNotEmpty && branch != 'All Branches') {
      params['branch'] = branch.trim();
    }
    if (academicYear != null && academicYear.trim().isNotEmpty && academicYear != 'All Years') {
      params['academic_year'] = academicYear.trim();
    }
    final path = params.isEmpty
        ? '/wanted/'
        : '/wanted/?${params.entries.map((e) => '${Uri.encodeQueryComponent(e.key)}=${Uri.encodeQueryComponent(e.value)}').join('&')}';
    final response = await _get(path);
    if (response.statusCode != 200) throw _apiError(response);
    final items = _decodeList(response);
    return items
        .map((dynamic item) =>
            WantedRequest.fromJson(item! as Map<String, dynamic>))
        .toList();
  }

  Future<WantedRequest> createWantedRequest(
    Map<String, dynamic> data, {
    required String token,
  }) async {
    final response = await _post(
      '/wanted/',
      body: data,
      token: token,
    );
    if (response.statusCode != 201 && response.statusCode != 200) {
      throw _apiError(response);
    }
    return WantedRequest.fromJson(_decodeMap(response));
  }

  Future<Map<String, dynamic>> draftWantedWithAi(
    String prompt, {
    required String token,
  }) async {
    final response = await _post(
      '/wanted/ai-draft',
      body: <String, dynamic>{'prompt': prompt},
      token: token,
    );
    if (response.statusCode != 200) throw _apiError(response);
    return _decodeMap(response);
  }

  Future<WantedRequest> fulfillWantedRequest(
    String id,
    String productId, {
    required String token,
  }) async {
    final response = await _post(
      '/wanted/$id/fulfill?product_id=$productId',
      body: <String, dynamic>{},
      token: token,
    );
    if (response.statusCode != 200) throw _apiError(response);
    return WantedRequest.fromJson(_decodeMap(response));
  }

  Future<void> deleteWantedRequest(String id, {required String token}) async {
    final response = await _delete('/wanted/$id', token: token);
    if (response.statusCode != 200 && response.statusCode != 204) {
      throw _apiError(response);
    }
  }

  // ---------------------------------------------------------------------------
  // Viral WhatsApp Share Card
  // ---------------------------------------------------------------------------
  Future<Map<String, dynamic>> fetchProductShareCard(String productId) async {
    final response = await _get('/products/$productId/share-card');
    if (response.statusCode != 200) throw _apiError(response);
    return _decodeMap(response);
  }
}

/// Result of POST /auth/verify-action-otp (proof of email verification).
class ActionOtpResult {
  const ActionOtpResult({required this.verified, required this.actionToken});

  final bool verified;
  final String actionToken;
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
    this.sellerId,
    this.sellerName,
    this.orderStatus = 'Requested / Processing',
    this.autoChatMessageId,
  });

  factory PurchaseResult.fromJson(Map<String, dynamic> json) {
    final sellerId = json['seller_id']?.toString();
    final chatId = json['auto_chat_message_id']?.toString();
    return PurchaseResult(
      transactionId: json['transaction_id']?.toString() ?? '',
      productId: json['product_id']?.toString() ?? '',
      finalPrice: (json['final_price'] as num?)?.toDouble() ?? 0,
      productStatus: json['product_status']?.toString() ?? 'sold',
      sellerId: (sellerId == null || sellerId.isEmpty) ? null : sellerId,
      sellerName: json['seller_name']?.toString(),
      orderStatus:
          json['order_status']?.toString() ?? 'Requested / Processing',
      autoChatMessageId: (chatId == null || chatId.isEmpty) ? null : chatId,
    );
  }

  final String transactionId;
  final String productId;
  final double finalPrice;
  final String productStatus;

  /// Seller identity for the success sheet ("💬 Open Chat with Seller").
  final String? sellerId;
  final String? sellerName;

  /// Fulfilment headline ("Requested / Processing").
  final String orderStatus;

  /// Order Card auto-message posted into the buyer→seller thread.
  final String? autoChatMessageId;
}

/// One row of GET /transactions/my (mirrors the backend `TransactionRead`).
class TransactionRecord {
  const TransactionRecord({
    required this.id,
    required this.productId,
    required this.buyerId,
    required this.finalPrice,
    required this.status,
    required this.timestamp,
    this.productTitle,
    this.productImageUrl,
    this.productStatus,
    this.buyerName,
    this.sellerName,
    this.orderStatus,
    this.paymentMethod,
    this.hostelOrLandmark,
    this.deliveryAddress,
    this.contactPhone,
  });

  factory TransactionRecord.fromJson(Map<String, dynamic> json) {
    return TransactionRecord(
      id: json['id']?.toString() ?? '',
      productId: json['product_id']?.toString() ?? '',
      buyerId: json['buyer_id']?.toString() ?? '',
      finalPrice: (json['final_price'] as num?)?.toDouble() ?? 0,
      status: json['status']?.toString() ?? 'completed',
      timestamp: DateTime.tryParse(json['timestamp']?.toString() ?? '') ??
          DateTime.now(),
      productTitle: json['product_title']?.toString(),
      productImageUrl: json['product_image_url']?.toString(),
      productStatus: json['product_status']?.toString(),
      buyerName: json['buyer_name']?.toString(),
      sellerName: json['seller_name']?.toString(),
      orderStatus: json['order_status']?.toString(),
      paymentMethod: json['payment_method']?.toString(),
      hostelOrLandmark: json['hostel_or_landmark']?.toString(),
      deliveryAddress: json['delivery_address']?.toString(),
      contactPhone: json['contact_phone']?.toString(),
    );
  }

  final String id;
  final String productId;
  final String buyerId;
  final double finalPrice;
  final String status;
  final DateTime timestamp;
  final String? productTitle;
  final String? productImageUrl;
  final String? productStatus;
  final String? buyerName;
  final String? sellerName;

  /// Structured checkout context for the Orders screen ("Requested /
  /// Processing", payment chip, meetup landmark).
  final String? orderStatus;
  final String? paymentMethod;
  final String? hostelOrLandmark;
  final String? deliveryAddress;
  final String? contactPhone;
}

/// Response body of GET /transactions/my: bought + sold history.
class TransactionHistory {
  const TransactionHistory({required this.bought, required this.sold});

  factory TransactionHistory.fromJson(Map<String, dynamic> json) {
    List<TransactionRecord> parse(String key) =>
        (json[key] as List<dynamic>? ?? const <dynamic>[])
            .whereType<Map<String, dynamic>>()
            .map(TransactionRecord.fromJson)
            .toList(growable: false);

    return TransactionHistory(bought: parse('bought'), sold: parse('sold'));
  }

  final List<TransactionRecord> bought;
  final List<TransactionRecord> sold;
}
