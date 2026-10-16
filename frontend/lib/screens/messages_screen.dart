import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/chat_models.dart';
import '../providers/auth_provider.dart';
import '../services/api_service.dart';
import '../services/currency.dart';
import '../widgets/app_theme.dart';
import 'chat_thread_screen.dart';

/// Tab 4 - Messages (buyer-seller inbox).
///
/// Lists every product thread the signed-in student participates in
/// (GET /chats/conversations), newest activity first, with an unread badge.
/// Refreshes every 20s while the tab is alive so incoming replies show up
/// without a manual pull.
class MessagesScreen extends StatefulWidget {
  const MessagesScreen({super.key});

  @override
  State<MessagesScreen> createState() => _MessagesScreenState();
}

class _MessagesScreenState extends State<MessagesScreen> {
  final ApiService _api = ApiService.instance;

  List<Conversation> _conversations = const <Conversation>[];
  bool _isLoading = true;
  String? _error;
  Timer? _poll;

  @override
  void initState() {
    super.initState();
    _load();
    _poll = Timer.periodic(const Duration(seconds: 20), (_) {
      if (!mounted || _isLoading) return;
      _load(silent: true);
    });
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  Future<void> _load({bool silent = false}) async {
    final token = context.read<AuthProvider>().token;
    if (token.isEmpty) return;
    if (!silent) {
      setState(() {
        _isLoading = _conversations.isEmpty;
        _error = null;
      });
    }
    try {
      final rows = await _api.fetchConversations(token: token);
      if (!mounted) return;
      setState(() {
        _conversations = rows;
        _isLoading = false;
        _error = null;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _isLoading = false;
        if (!silent) _error = error.message;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _isLoading = false;
        if (!silent) _error = 'Could not load messages: $error';
      });
    }
  }

  void _openThread(Conversation conversation) {
    Navigator.of(context)
        .push(
      MaterialPageRoute<void>(
        builder: (_) => ChatThreadScreen(
          productId: conversation.productId,
          productTitle: conversation.productTitle,
          productImageUrl: conversation.productImageUrl,
          productPrice: conversation.productPrice,
          otherUserId: conversation.otherUserId,
          otherUserName: conversation.otherUserName,
        ),
      ),
    )
        .then((_) {
      // Opening a thread clears its badge server-side - refresh on return.
      if (mounted) _load(silent: true);
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        titleSpacing: 16,
        title: const Text(
          'Messages',
          style: TextStyle(
            fontFamily: 'Georgia',
            color: AppColors.inkBlack,
            fontSize: 20,
            fontWeight: FontWeight.w700,
          ),
        ),
        actions: [
          IconButton(
            tooltip: 'Refresh',
            icon: const Icon(Icons.refresh, size: 20, color: AppColors.textMuted),
            onPressed: () => _load(),
          ),
        ],
      ),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_isLoading && _conversations.isEmpty) {
      return const Center(
        child: CircularProgressIndicator(color: AppColors.cyanAccent),
      );
    }
    if (_error != null && _conversations.isEmpty) {
      return _MessagesEmpty(
        icon: Icons.cloud_off_outlined,
        title: 'Could not load your messages',
        message: _error!,
        actionLabel: 'Retry',
        onAction: () => _load(),
      );
    }
    if (_conversations.isEmpty) {
      return const _MessagesEmpty(
        icon: Icons.chat_bubble_outline,
        title: 'No conversations yet',
        message: 'Open a listing and tap "Chat with Seller" to start a '
            'conversation - it will show up here.',
        actionLabel: null,
        onAction: null,
      );
    }

    return RefreshIndicator(
      color: AppColors.cyanAccent,
      backgroundColor: AppColors.surface,
      onRefresh: () => _load(),
      child: ListView.separated(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
        itemCount: _conversations.length,
        separatorBuilder: (context, index) => const SizedBox(height: 10),
        itemBuilder: (context, index) => _ConversationTile(
          conversation: _conversations[index],
          onOpen: () => _openThread(_conversations[index]),
        ),
      ),
    );
  }
}

/// One inbox row: product thumb, counterparty, last message, unread pill.
class _ConversationTile extends StatelessWidget {
  const _ConversationTile({
    required this.conversation,
    required this.onOpen,
  });

  final Conversation conversation;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) {
    final unread = conversation.hasUnread;
    return Material(
      color: AppColors.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: BorderSide(
          color: unread
              ? AppColors.cyanAccent.withOpacity(0.55)
              : AppColors.hairline,
          width: 1,
        ),
      ),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onOpen,
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _Thumb(url: conversation.productImageUrl),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            conversation.otherUserName,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                              color: AppColors.textPrimary,
                              fontSize: 14,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                        ),
                        Text(
                          _timeLabel(conversation.lastMessageAt),
                          style: TextStyle(
                            color:
                                unread ? AppColors.cyanAccent : AppColors.textMuted,
                            fontSize: 10.5,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 2),
                    Text(
                      conversation.productTitle,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: AppColors.textMuted,
                        fontSize: 11.5,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            '${conversation.lastMessageIsMine ? 'You: ' : ''}'
                            '${conversation.lastMessage}',
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                              color: unread
                                  ? AppColors.textPrimary
                                  : AppColors.textMuted,
                              fontSize: 12.5,
                              height: 1.3,
                              fontWeight:
                                  unread ? FontWeight.w700 : FontWeight.w500,
                            ),
                          ),
                        ),
                        if (unread) ...[
                          const SizedBox(width: 8),
                          Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 7, vertical: 2),
                            decoration: BoxDecoration(
                              color: AppColors.cyanAccent,
                              borderRadius: BorderRadius.circular(999),
                            ),
                            child: Text(
                              conversation.unreadCount > 9
                                  ? '9+'
                                  : '${conversation.unreadCount}',
                              style: const TextStyle(
                                color: Colors.black,
                                fontSize: 10,
                                fontWeight: FontWeight.w900,
                              ),
                            ),
                          ),
                        ],
                      ],
                    ),
                    if (conversation.productPrice != null) ...[
                      const SizedBox(height: 5),
                      Text(
                        formatInr(conversation.productPrice!),
                        style: const TextStyle(
                          color: AppColors.cyanAccent,
                          fontSize: 12,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  static String _timeLabel(DateTime time) {
    final local = time.toLocal();
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final day = DateTime(local.year, local.month, local.day);
    final hh = local.hour.toString().padLeft(2, '0');
    final mm = local.minute.toString().padLeft(2, '0');
    if (day == today) return '$hh:$mm';
    if (day == today.subtract(const Duration(days: 1))) return 'Yesterday';
    return '${local.day}/${local.month}';
  }
}

/// Small product thumbnail with an icon fallback.
class _Thumb extends StatelessWidget {
  const _Thumb({this.url});

  final String? url;

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(10),
      child: Container(
        width: 54,
        height: 54,
        color: AppColors.surfaceHigh,
        child: (url == null || url!.isEmpty)
            ? const Icon(Icons.sell_outlined,
                size: 22, color: AppColors.textMuted)
            : Image.network(
                url!,
                fit: BoxFit.cover,
                errorBuilder: (context, error, stack) => const Icon(
                    Icons.sell_outlined,
                    size: 22,
                    color: AppColors.textMuted),
              ),
      ),
    );
  }
}

/// Empty / error placeholder that supports pull-to-refresh layouts.
class _MessagesEmpty extends StatelessWidget {
  const _MessagesEmpty({
    required this.icon,
    required this.title,
    required this.message,
    this.actionLabel,
    this.onAction,
  });

  final IconData icon;
  final String title;
  final String message;
  final String? actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 40),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 44, color: AppColors.textMuted),
            const SizedBox(height: 14),
            Text(
              title,
              textAlign: TextAlign.center,
              style: const TextStyle(
                color: AppColors.textPrimary,
                fontSize: 16,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              message,
              textAlign: TextAlign.center,
              style: const TextStyle(
                color: AppColors.textMuted,
                fontSize: 13,
                height: 1.4,
              ),
            ),
            if (actionLabel != null && onAction != null) ...[
              const SizedBox(height: 14),
              TextButton(
                onPressed: onAction,
                child: Text(
                  actionLabel!,
                  style: const TextStyle(
                    color: AppColors.cyanAccent,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
