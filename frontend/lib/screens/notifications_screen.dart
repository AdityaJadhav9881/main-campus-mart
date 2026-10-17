import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/notification_item.dart';
import '../providers/auth_provider.dart';
import '../services/api_service.dart';
import '../services/notification_service.dart';
import '../widgets/app_theme.dart';
import 'messages_screen.dart';
import 'orders_screen.dart';
import 'product_detail_screen.dart';

/// Bell-icon alert center (Part B Task 2).
///
/// Shows the full `GET /notifications/` feed grouped chronologically with
/// category icons (🎓 campus listings, 🎉/📦 orders, 💬 messages, 📞 calls),
/// relative timestamps, per-row read state and deep links: listing alerts
/// open the product card, message/call alerts open the inbox, order alerts
/// open My Orders.
class NotificationsScreen extends StatefulWidget {
  const NotificationsScreen({super.key});

  @override
  State<NotificationsScreen> createState() => _NotificationsScreenState();
}

class _NotificationsScreenState extends State<NotificationsScreen> {
  final ApiService _api = ApiService.instance;

  List<AppNotification> _items = const <AppNotification>[];
  bool _isLoading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    // Seed instantly from the poller's latest snapshot, then go fresh.
    final cached = NotificationService.instance.latestFeed.value;
    if (cached != null) {
      _items = cached.notifications;
      _isLoading = false;
    }
    _load();
  }

  Future<void> _load() async {
    final token = context.read<AuthProvider>().token;
    if (token.isEmpty) return;
    try {
      final feed = await _api.fetchNotifications(token: token);
      NotificationService.instance.latestFeed.value = feed;
      NotificationService.instance.unreadCount.value = feed.unreadCount;
      NotificationService.instance.silenceCurrentFeed();
      if (!mounted) return;
      setState(() {
        _items = feed.notifications;
        _isLoading = false;
        _error = null;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _isLoading = false;
        _error = error.message;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _isLoading = false;
        _error = 'Could not load notifications right now.';
      });
    }
  }

  Future<void> _markAllRead() async {
    final token = context.read<AuthProvider>().token;
    final unread = _items.where((item) => !item.isRead).toList();
    if (unread.isEmpty) return;
    setState(() {
      _items = _items
          .map((item) => item.isRead ? item : item.copyWith(isRead: true))
          .toList(growable: false);
    });
    NotificationService.instance.unreadCount.value = 0;
    try {
      await _api.markAllNotificationsRead(token: token);
    } catch (_) {
      // Best-effort: the local badge already updated; next poll reconciles.
    }
  }

  Future<void> _open(AppNotification item) async {
    final token = context.read<AuthProvider>().token;

    if (!item.isRead) {
      setState(() {
        _items = _items
            .map((row) =>
                row.id == item.id ? row.copyWith(isRead: true) : row)
            .toList(growable: false);
      });
      try {
        await _api.markNotificationRead(
          notificationId: item.id,
          token: token,
        );
        NotificationService.instance.refreshBadge();
      } catch (_) {
        // Keep going - the tap should still navigate.
      }
    }

    if (!mounted) return;
    switch (item.type) {
      case 'college_listing':
        await _openListing(item.referenceId);
      case 'chat_message':
      case 'call':
        await Navigator.of(context).push(
          MaterialPageRoute<void>(builder: (_) => const MessagesScreen()),
        );
      case 'order_placed':
      case 'item_sold':
        await Navigator.of(context).push(
          MaterialPageRoute<void>(builder: (_) => const OrdersScreen()),
        );
      default:
        break;
    }
  }

  Future<void> _openListing(String? productId) async {
    if (productId == null || productId.isEmpty) return;
    try {
      final product = await _api.fetchProductById(productId);
      if (!mounted) return;
      if (product == null) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('That listing is no longer available.'),
            duration: Duration(seconds: 2),
          ),
        );
        return;
      }
      await Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => ProductDetailScreen(product: product),
        ),
      );
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Could not open that listing right now.'),
          duration: Duration(seconds: 2),
        ),
      );
    }
  }

  String _relativeTime(DateTime time) {
    final diff = DateTime.now().difference(time);
    if (diff.inSeconds < 60) return 'Just now';
    if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
    if (diff.inHours < 24) return '${diff.inHours}h ago';
    if (diff.inDays < 7) return '${diff.inDays}d ago';
    return '${time.day}/${time.month}/${time.year}';
  }

  (IconData, Color) _metaFor(String type) {
    switch (type) {
      case 'college_listing':
        return (Icons.school_outlined, AppColors.royalBlue);
      case 'order_placed':
        return (Icons.receipt_long_outlined, AppColors.forestGreen);
      case 'item_sold':
        return (Icons.sell_outlined, AppColors.forestGreen);
      case 'chat_message':
        return (Icons.chat_bubble_outline, AppColors.royalBlue);
      case 'call':
        return (Icons.call_outlined, AppColors.royalBlue);
      default:
        return (Icons.notifications_none_rounded, AppColors.textMuted);
    }
  }

  @override
  Widget build(BuildContext context) {
    final hasUnread = _items.any((item) => !item.isRead);

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        titleSpacing: 16,
        title: const Text(
          'Notifications',
          style: TextStyle(
            fontFamily: 'Georgia',
            fontSize: 20,
            fontWeight: FontWeight.w700,
            color: AppColors.inkBlack,
          ),
        ),
        actions: [
          if (hasUnread)
            TextButton.icon(
              onPressed: _markAllRead,
              icon: const Icon(Icons.done_all, size: 17),
              label: const Text(
                'Mark all read',
                style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
              ),
              style: TextButton.styleFrom(foregroundColor: AppColors.royalBlue),
            ),
        ],
      ),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_isLoading && _items.isEmpty) {
      return const Center(
        child: CircularProgressIndicator(color: AppColors.royalBlue),
      );
    }

    if (_error != null && _items.isEmpty) {
      return ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        children: [
          const SizedBox(height: 120),
          const Icon(Icons.cloud_off_outlined,
              size: 42, color: AppColors.textMuted),
          const SizedBox(height: 14),
          const Text(
            'Could not reach your alerts',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: AppColors.textPrimary,
              fontSize: 15.5,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 6),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 40),
            child: Text(
              _error!,
              textAlign: TextAlign.center,
              style: const TextStyle(color: AppColors.textMuted, fontSize: 12.5),
            ),
          ),
          const SizedBox(height: 16),
          Center(
            child: TextButton(
              onPressed: () {
                setState(() => _isLoading = true);
                _load();
              },
              child: const Text(
                'Retry',
                style: TextStyle(
                    color: AppColors.royalBlue, fontWeight: FontWeight.w700),
              ),
            ),
          ),
        ],
      );
    }

    return RefreshIndicator(
      color: AppColors.royalBlue,
      backgroundColor: AppColors.surface,
      onRefresh: _load,
      child: _items.isEmpty
          ? ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              children: const [
                SizedBox(height: 140),
                Icon(Icons.notifications_none_rounded,
                    size: 46, color: AppColors.textMuted),
                SizedBox(height: 14),
                Text(
                  'All caught up!',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                SizedBox(height: 8),
                Text(
                  'College listings, orders, messages and calls\nwill appear here.',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: AppColors.textMuted,
                    fontSize: 12.5,
                    height: 1.5,
                  ),
                ),
              ],
            )
          : ListView.separated(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.fromLTRB(16, 10, 16, 28),
              itemCount: _items.length,
              separatorBuilder: (_, __) => const SizedBox(height: 10),
              itemBuilder: (context, index) {
                final item = _items[index];
                return _NotificationTile(
                  item: item,
                  timeLabel: _relativeTime(item.createdAt),
                  meta: _metaFor(item.type),
                  onTap: () => _open(item),
                );
              },
            ),
    );
  }
}

/// One alert row: category icon bubble, title + body, relative time, unread
/// dot and a soft blue tint while unread.
class _NotificationTile extends StatelessWidget {
  const _NotificationTile({
    required this.item,
    required this.timeLabel,
    required this.meta,
    required this.onTap,
  });

  final AppNotification item;
  final String timeLabel;
  final (IconData, Color) meta;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final (icon, color) = meta;
    return Material(
      color: item.isRead
          ? AppColors.surface
          : AppColors.royalBlue.withOpacity(0.06),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: BorderSide(
          color: item.isRead
              ? AppColors.hairline
              : AppColors.royalBlue.withOpacity(0.35),
        ),
      ),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 38,
                height: 38,
                decoration: BoxDecoration(
                  color: color.withOpacity(0.12),
                  shape: BoxShape.circle,
                ),
                child: Icon(icon, size: 19, color: color),
              ),
              const SizedBox(width: 11),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            item.title,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                              color: AppColors.textPrimary,
                              fontSize: 13.5,
                              fontWeight: item.isRead
                                  ? FontWeight.w600
                                  : FontWeight.w800,
                            ),
                          ),
                        ),
                        const SizedBox(width: 8),
                        Text(
                          timeLabel,
                          style: const TextStyle(
                            color: AppColors.textMuted,
                            fontSize: 10.5,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      item.body,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: AppColors.textMuted,
                        fontSize: 12,
                        height: 1.35,
                      ),
                    ),
                  ],
                ),
              ),
              if (!item.isRead) ...[
                const SizedBox(width: 8),
                Container(
                  width: 8,
                  height: 8,
                  margin: const EdgeInsets.only(top: 5),
                  decoration: const BoxDecoration(
                    color: AppColors.royalBlue,
                    shape: BoxShape.circle,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
