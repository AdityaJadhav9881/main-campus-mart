import 'package:flutter/services.dart';

/// Handles upfront device permission requests on Android (Camera, Mic,
/// Notifications, Media/Storage) to ensure smooth calling and selling.
class PermissionService {
  static const MethodChannel _channel = MethodChannel('campusmart.ai/native');
  static bool _requestedOnce = false;

  /// Requests all necessary permissions simultaneously on app launch.
  static Future<void> requestAllAppPermissions() async {
    if (_requestedOnce) return;
    _requestedOnce = true;
    try {
      await _channel.invokeMethod('requestAllAppPermissions');
    } catch (_) {
      // Platform channel fallback on non-Android or unsupported OS
    }
  }

  /// Plays incoming call ringtone and starts vibration pattern.
  static Future<void> startRingtone() async {
    try {
      await _channel.invokeMethod('startRingtone');
    } catch (_) {}
  }

  /// Stops incoming call ringtone and cancels vibration pattern.
  static Future<void> stopRingtone() async {
    try {
      await _channel.invokeMethod('stopRingtone');
    } catch (_) {}
  }

  /// Syncs user token and API base URL with native Android service.
  static Future<void> saveNativeCredentials({
    required String apiUrl,
    required String token,
    required String userId,
  }) async {
    try {
      await _channel.invokeMethod('saveNativeCredentials', {
        'apiUrl': apiUrl,
        'token': token,
        'userId': userId,
      });
    } catch (_) {}
  }

  /// Stops the background service when the user explicitly logs out.
  static Future<void> stopBackgroundService() async {
    try {
      await _channel.invokeMethod('stopBackgroundService');
    } catch (_) {}
  }

  /// Shares listing or request text via native Android share chooser (WhatsApp, Gmail, etc.)
  static Future<void> shareText({required String text, String title = 'Share via'}) async {
    try {
      await _channel.invokeMethod('shareText', {
        'text': text,
        'title': title,
      });
    } catch (_) {}
  }
}

