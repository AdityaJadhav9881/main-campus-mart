// Bell-icon notification models (mirror the FastAPI `NotificationRead` /
// `NotificationListResponse` schemas served by GET /notifications/).

/// One in-app notification row.
class AppNotification {
  const AppNotification({
    required this.id,
    required this.title,
    required this.body,
    required this.type,
    required this.createdAt,
    this.referenceId,
    this.isRead = false,
  });

  factory AppNotification.fromJson(Map<String, dynamic> json) {
    return AppNotification(
      id: json['id']?.toString() ?? '',
      title: json['title']?.toString() ?? '',
      body: json['body']?.toString() ?? '',
      type: json['type']?.toString() ?? 'system',
      referenceId: json['reference_id']?.toString(),
      isRead: json['is_read'] == true,
      createdAt: DateTime.tryParse(json['created_at']?.toString() ?? '') ??
          DateTime.now(),
    );
  }

  final String id;
  final String title;
  final String body;

  /// 'college_listing' | 'order_placed' | 'item_sold' | 'chat_message'
  /// | 'call' | 'system'.
  final String type;

  /// Deep-link target: product id (college_listing), counterpart user id
  /// (chat_message/call), or transaction id (order_placed/item_sold).
  final String? referenceId;

  final bool isRead;
  final DateTime createdAt;

  AppNotification copyWith({bool? isRead}) {
    return AppNotification(
      id: id,
      title: title,
      body: body,
      type: type,
      referenceId: referenceId,
      isRead: isRead ?? this.isRead,
      createdAt: createdAt,
    );
  }
}

/// GET /notifications/ payload: newest-first rows + unread badge count.
class NotificationFeed {
  const NotificationFeed({required this.notifications, this.unreadCount = 0});

  factory NotificationFeed.fromJson(Map<String, dynamic> json) {
    return NotificationFeed(
      notifications:
          (json['notifications'] as List<dynamic>? ?? const <dynamic>[])
              .whereType<Map<String, dynamic>>()
              .map(AppNotification.fromJson)
              .toList(growable: false),
      unreadCount: (json['unread_count'] as num?)?.toInt() ?? 0,
    );
  }

  final List<AppNotification> notifications;
  final int unreadCount;
}
