import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import '../models/notification_item.dart';
import '../providers/auth_provider.dart';
import 'api_service.dart';

/// Campus-wide alert pump behind the Discover bell icon (Part B Task 1).
///
/// While a student is signed in it polls `GET /notifications/` every 15s,
/// mirrors the unread badge count into [unreadCount] for the bell, and raises
/// a real Android heads-up notification (via the `campusmart.ai/notifications`
/// MethodChannel) for every alert it has not announced yet. Failures are
/// swallowed - the in-app bell always remains the source of truth.
class NotificationService {
  NotificationService._();

  static final NotificationService instance = NotificationService._();

  static const MethodChannel _channel =
      MethodChannel('campusmart.ai/notifications');

  static const Duration _pollInterval = Duration(seconds: 15);

  final ApiService _api = ApiService.instance;

  /// Unread badge count for the bell icon (0 hides the badge).
  final ValueNotifier<int> unreadCount = ValueNotifier<int>(0);

  /// Most recent feed snapshot (NotificationsScreen seeds from this).
  final ValueNotifier<NotificationFeed?> latestFeed =
      ValueNotifier<NotificationFeed?>(null);

  Timer? _timer;
  String _token = '';
  bool _isFetching = false;
  bool _permissionAsked = false;
  AuthProvider? _boundAuth;

  /// Alert ids already raised as system notifications this app run (so a
  /// 15s poll never buzzes twice for the same row).
  final Set<String> _announcedIds = <String>{};

  /// Ties the poller to the session: starts on sign-in, stops on sign-out.
  void bindAuth(AuthProvider auth) {
    _boundAuth?.removeListener(_onAuthChanged);
    _boundAuth = auth;
    auth.addListener(_onAuthChanged);
    _onAuthChanged();
  }

  void _onAuthChanged() {
    final auth = _boundAuth;
    if (auth == null) return;
    if (auth.isLoggedIn && auth.token.isNotEmpty) {
      start(auth.token);
    } else {
      stop();
    }
  }

  /// Begin (or re-target) polling for [token].
  bool _initializedBaseline = false;

  /// Begin (or re-target) polling for [token].
  void start(String token) {
    if (token.isEmpty) return;
    if (_token == token && _timer != null) return;
    _token = token;
    _initializedBaseline = false;
    _timer?.cancel();
    _timer = Timer.periodic(_pollInterval, (_) => refresh(announce: true));
    // Initial fetch: seed existing notifications into announced set to avoid flooding alerts
    refresh(announce: false, isInitialBootstrap: true);
  }

  /// Stop polling and clear the badge (logout / terminated session).
  void stop() {
    _timer?.cancel();
    _timer = null;
    _token = '';
    _announcedIds.clear();
    _initializedBaseline = false;
    unreadCount.value = 0;
    latestFeed.value = null;
  }

  /// Fetch the feed now. [announce] posts Android notifications for any
  /// unread alert not yet surfaced (manual bell opens pass false).
  Future<void> refresh({bool announce = false, bool isInitialBootstrap = false}) async {
    final token = _token;
    if (token.isEmpty || _isFetching) return;
    _isFetching = true;
    try {
      final feed = await _api.fetchNotifications(token: token, markPushed: true);
      latestFeed.value = feed;
      unreadCount.value = feed.unreadCount;

      if (isInitialBootstrap || !_initializedBaseline) {
        for (final item in feed.notifications) {
          _announcedIds.add(item.id);
        }
        _initializedBaseline = true;
      } else if (announce) {
        for (final item in feed.notifications) {
          if (!item.isRead && !item.isPushed && _announcedIds.add(item.id)) {
            await _showSystemNotification(item);
          }
        }
      } else {
        for (final item in feed.notifications) {
          _announcedIds.add(item.id);
        }
      }
    } catch (_) {
      // Network hiccup - keep the previous badge; next poll retries.
    } finally {
      _isFetching = false;
    }
  }

  /// Re-pull after the student reads something (badge drops instantly).
  Future<void> refreshBadge() => refresh();

  /// Called by the bell screen once it has rendered [latestFeed]: everything
  /// currently listed has been seen in-app, so the poll loop must not buzz
  /// Android heads-up alerts for those rows afterwards.
  void silenceCurrentFeed() {
    final feed = latestFeed.value;
    if (feed == null) return;
    for (final item in feed.notifications) {
      _announcedIds.add(item.id);
    }
  }

  Future<void> _showSystemNotification(AppNotification item) async {
    if (defaultTargetPlatform != TargetPlatform.android) return;
    try {
      if (!_permissionAsked) {
        _permissionAsked = true;
        await _channel.invokeMethod<bool>('requestPermission');
      }
      await _channel.invokeMethod<bool>('showNotification', <String, dynamic>{
        'id': item.id.hashCode & 0x7FFFFFFF,
        'title': item.title,
        'body': item.body,
      });
    } on MissingPluginException {
      // Non-Android host (tests / desktop) - silently skip.
    } catch (_) {
      // Channel error must never break the poll loop.
    }
  }
}
