import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:provider/provider.dart';

import '../models/chat_models.dart';
import '../models/product.dart';
import '../providers/auth_provider.dart';
import '../providers/product_provider.dart';
import '../services/api_service.dart';
import '../services/currency.dart';
import '../widgets/app_theme.dart';
import 'in_app_call_screen.dart';
import 'product_detail_screen.dart';

/// One buyer-seller conversation on a product listing.
///
/// Loads the full thread (GET /chats/messages/{product}/{other}) which also
/// clears the caller's unread badge server-side, then polls every 15s while
/// the screen is open so replies land without a manual refresh.
class ChatThreadScreen extends StatefulWidget {
  const ChatThreadScreen({
    super.key,
    required this.productId,
    required this.productTitle,
    this.productImageUrl,
    this.productPrice,
    required this.otherUserId,
    required this.otherUserName,
  });

  final String productId;
  final String productTitle;
  final String? productImageUrl;
  final double? productPrice;
  final String otherUserId;
  final String otherUserName;

  @override
  State<ChatThreadScreen> createState() => _ChatThreadScreenState();
}

class _ChatThreadScreenState extends State<ChatThreadScreen> {
  final ApiService _api = ApiService.instance;
  final TextEditingController _input = TextEditingController();
  final ScrollController _scroll = ScrollController();

  List<ChatMessage> _messages = const <ChatMessage>[];
  bool _isLoading = true;
  bool _isSending = false;
  String? _error;
  Timer? _poll;

  @override
  void initState() {
    super.initState();
    _load();
    _poll = Timer.periodic(const Duration(seconds: 15), (_) {
      if (!mounted || _isSending) return;
      _load(silent: true);
    });
  }

  @override
  void dispose() {
    _poll?.cancel();
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _load({bool silent = false}) async {
    final token = context.read<AuthProvider>().token;
    if (token.isEmpty) return;
    if (!silent) {
      setState(() {
        _isLoading = _messages.isEmpty;
        _error = null;
      });
    }
    try {
      final rows = await _api.fetchThreadMessages(
        productId: widget.productId,
        otherUserId: widget.otherUserId,
        token: token,
      );
      if (!mounted) return;
      final changed = rows.length != _messages.length ||
          (rows.isNotEmpty &&
              (_messages.isEmpty ||
                  rows.last.createdAt != _messages.last.createdAt));
      setState(() {
        _messages = rows;
        _isLoading = false;
        _error = null;
      });
      if (changed) _scrollToBottom();
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
        if (!silent) _error = 'Could not load the thread: $error';
      });
    }
  }

  Future<void> _send() async {
    final text = _input.text.trim();
    if (text.isEmpty || _isSending) return;
    _input.clear();
    await _postMessage(text: text);
  }

  /// Camera/gallery picker -> upload the photo -> send it on the thread
  /// (with the composer text as optional caption, WhatsApp style).
  Future<void> _pickPhoto() async {
    if (_isSending) return;
    final source = await showModalBottomSheet<ImageSource>(
      context: context,
      backgroundColor: AppColors.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
      ),
      builder: (sheetContext) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const SizedBox(height: 8),
            ListTile(
              leading: const Icon(
                Icons.photo_camera_outlined,
                color: AppColors.royalBlue,
              ),
              title: const Text(
                'Take a photo',
                style: TextStyle(
                  color: AppColors.textPrimary,
                  fontWeight: FontWeight.w700,
                ),
              ),
              onTap: () => Navigator.pop(sheetContext, ImageSource.camera),
            ),
            ListTile(
              leading: const Icon(
                Icons.photo_library_outlined,
                color: AppColors.royalBlue,
              ),
              title: const Text(
                'Choose from gallery',
                style: TextStyle(
                  color: AppColors.textPrimary,
                  fontWeight: FontWeight.w700,
                ),
              ),
              onTap: () => Navigator.pop(sheetContext, ImageSource.gallery),
            ),
            const SizedBox(height: 6),
          ],
        ),
      ),
    );
    if (source == null || !mounted) return;

    try {
      final picked = await ImagePicker().pickImage(
        source: source,
        maxWidth: 1600,
        imageQuality: 85,
      );
      if (picked == null || !mounted) return;
      final bytes = await picked.readAsBytes();
      if (!mounted) return;
      final caption = _input.text.trim();
      _input.clear();
      await _postMessage(
        text: caption,
        photoBytes: bytes,
        photoName: picked.name,
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Could not open your photos: $error')),
      );
    }
  }

  /// Single send path for text and/or photo messages.
  Future<void> _postMessage({
    required String text,
    Uint8List? photoBytes,
    String photoName = 'chat_photo.jpg',
  }) async {
    if (_isSending) return;
    if (text.isEmpty && photoBytes == null) return;

    final auth = context.read<AuthProvider>();
    final myId = auth.profile?.id ?? '';
    final pendingId = 'pending-${DateTime.now().microsecondsSinceEpoch}';

    setState(() {
      _isSending = true;
      // Optimistic bubble so the send feels instant.
      _messages = <ChatMessage>[
        ..._messages,
        ChatMessage(
          id: pendingId,
          productId: widget.productId,
          senderId: myId,
          receiverId: widget.otherUserId,
          message: text.isNotEmpty ? text : 'Uploading photo...',
          createdAt: DateTime.now(),
        ),
      ];
    });
    _scrollToBottom();

    try {
      String? uploadedUrl;
      if (photoBytes != null) {
        uploadedUrl = await _api.uploadListingImage(
          bytes: photoBytes,
          filename: photoName,
          token: auth.token,
        );
      }
      final created = await _api.sendMessage(
        productId: widget.productId,
        receiverId: widget.otherUserId,
        message: text,
        imageUrl: uploadedUrl,
        token: auth.token,
      );
      if (!mounted) return;
      setState(() {
        _messages = <ChatMessage>[
          for (final message in _messages)
            if (message.id == pendingId) created else message,
        ];
        _isSending = false;
      });
    } on ApiException catch (error) {
      _handleSendFailure(pendingId, text, error.message);
    } catch (error) {
      _handleSendFailure(pendingId, text, '$error');
    }
  }

  void _handleSendFailure(String pendingId, String text, String reason) {
    if (!mounted) return;
    setState(() {
      _messages = _messages
          .where((message) => message.id != pendingId)
          .toList();
      _isSending = false;
    });
    if (text.isNotEmpty) _input.text = text;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('Message not sent: $reason')),
    );
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scroll.hasClients) return;
      _scroll.animateTo(
        _scroll.position.maxScrollExtent,
        duration: const Duration(milliseconds: 220),
        curve: Curves.easeOut,
      );
    });
  }

  void _openProduct() {
    final feed = context.read<ProductProvider>();
    Product? product;
    for (final candidate in feed.products) {
      if (candidate.id == widget.productId) {
        product = candidate;
        break;
      }
    }
    if (product == null || !mounted) return;
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => ProductDetailScreen(product: product!),
      ),
    );
  }

  /// Opens the in-app call screen (Task 6); on hang-up the outcome is logged
  /// via POST /chats/call-event so both sides see the call bubble.
  Future<void> _startCall({required bool video}) async {
    final outcome = await Navigator.of(context).push<CallOutcome>(
      MaterialPageRoute<CallOutcome>(
        builder: (_) => InAppCallScreen(
          receiverName: widget.otherUserName,
          initialVideo: video,
        ),
      ),
    );
    if (outcome == null || !mounted) return;
    try {
      final created = await _api.recordCallEvent(
        productId: widget.productId,
        receiverId: widget.otherUserId,
        callType: outcome.callType,
        status: outcome.status,
        durationSeconds: outcome.durationSeconds,
        token: context.read<AuthProvider>().token,
      );
      if (!mounted) return;
      setState(() {
        _messages = <ChatMessage>[..._messages, created];
      });
      _scrollToBottom();
    } catch (_) {
      // The call itself is done; failing to log it must not interrupt chat.
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        titleSpacing: 0,
        title: Row(
          children: [
            const Icon(Icons.person_outline,
                size: 20, color: AppColors.textMuted),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                widget.otherUserName,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: AppColors.textPrimary,
                  fontSize: 16,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ),
          ],
        ),
        actions: [
          // Task 6: in-app voice/video calls from the thread itself.
          IconButton(
            tooltip: 'Voice call',
            icon: const Icon(Icons.call_outlined, size: 20),
            onPressed: () => _startCall(video: false),
          ),
          IconButton(
            tooltip: 'Video call',
            icon: const Icon(Icons.videocam_outlined, size: 21),
            onPressed: () => _startCall(video: true),
          ),
        ],
      ),
      body: Column(
        children: [
          _ProductHeader(
            title: widget.productTitle,
            imageUrl: widget.productImageUrl,
            price: widget.productPrice,
            onTap: _openProduct,
          ),
          const Divider(),
          Expanded(child: _buildThread()),
          _Composer(
            controller: _input,
            onSend: _send,
            onPickPhoto: _pickPhoto,
            enabled: !_isSending,
          ),
        ],
      ),
    );
  }

  Widget _buildThread() {
    if (_isLoading && _messages.isEmpty) {
      return const Center(
        child: CircularProgressIndicator(color: AppColors.cyanAccent),
      );
    }
    if (_error != null && _messages.isEmpty) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.cloud_off_outlined,
                size: 40, color: AppColors.textMuted),
            const SizedBox(height: 12),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 36),
              child: Text(
                _error!,
                textAlign: TextAlign.center,
                style: const TextStyle(
                    color: AppColors.textMuted, fontSize: 13, height: 1.4),
              ),
            ),
            TextButton(
              onPressed: () => _load(),
              child: const Text('Retry',
                  style: TextStyle(
                      color: AppColors.cyanAccent,
                      fontWeight: FontWeight.w700)),
            ),
          ],
        ),
      );
    }
    if (_messages.isEmpty) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.symmetric(horizontal: 40),
          child: Text(
            'Say hi! Ask about the item\'s condition, price, or where to '
            'meet on campus.',
            textAlign: TextAlign.center,
            style: TextStyle(
                color: AppColors.textMuted, fontSize: 13.5, height: 1.45),
          ),
        ),
      );
    }

    final myId = context.read<AuthProvider>().profile?.id ?? '';
    return RefreshIndicator(
      color: AppColors.cyanAccent,
      backgroundColor: AppColors.surface,
      onRefresh: () => _load(),
      child: ListView.builder(
        controller: _scroll,
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
        itemCount: _messages.length,
        itemBuilder: (context, index) {
          final message = _messages[index];
          final mine = message.senderId == myId;
          final previous =
              index > 0 ? _messages[index - 1] : null;
          final showTime = previous == null ||
              message.createdAt.difference(previous.createdAt).inMinutes >= 5;
          return _MessageBubble(
            message: message,
            mine: mine,
            showTime: showTime,
            pending: message.id.startsWith('pending-'),
          );
        },
      ),
    );
  }
}

/// Tappable product strip pinned above the composer.
class _ProductHeader extends StatelessWidget {
  const _ProductHeader({
    required this.title,
    required this.imageUrl,
    required this.price,
    required this.onTap,
  });

  final String title;
  final String? imageUrl;
  final double? price;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
        child: Row(
          children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: Container(
                width: 40,
                height: 40,
                color: AppColors.surfaceHigh,
                child: (imageUrl == null || imageUrl!.isEmpty)
                    ? const Icon(Icons.sell_outlined,
                        size: 18, color: AppColors.textMuted)
                    : Image.network(imageUrl!,
                        fit: BoxFit.cover,
                        errorBuilder: (context, error, stack) => const Icon(
                            Icons.sell_outlined,
                            size: 18,
                            color: AppColors.textMuted)),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: AppColors.textPrimary,
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  if (price != null)
                    Text(
                      formatInr(price!),
                      style: const TextStyle(
                        color: AppColors.cyanAccent,
                        fontSize: 12,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                ],
              ),
            ),
            const Icon(Icons.chevron_right,
                size: 18, color: AppColors.textMuted),
          ],
        ),
      ),
    );
  }
}

/// Chat bubble (mine = cyan tinted right, theirs = surface left).
class _MessageBubble extends StatelessWidget {
  const _MessageBubble({
    required this.message,
    required this.mine,
    required this.showTime,
    required this.pending,
  });

  final ChatMessage message;
  final bool mine;
  final bool showTime;
  final bool pending;

  @override
  Widget build(BuildContext context) {
    final radius = BorderRadius.only(
      topLeft: const Radius.circular(14),
      topRight: const Radius.circular(14),
      bottomLeft: Radius.circular(mine ? 14 : 4),
      bottomRight: Radius.circular(mine ? 4 : 14),
    );
    final time =
        '${message.createdAt.toLocal().hour.toString().padLeft(2, '0')}:'
        '${message.createdAt.toLocal().minute.toString().padLeft(2, '0')}';

    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Column(
        crossAxisAlignment:
            mine ? CrossAxisAlignment.end : CrossAxisAlignment.start,
        children: [
          Container(
            constraints: const BoxConstraints(maxWidth: 300),
            padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 10),
            decoration: BoxDecoration(
              color: mine
                  ? AppColors.cyanAccent.withOpacity(0.16)
                  : AppColors.surface,
              borderRadius: radius,
              border: Border.all(
                color: mine
                    ? AppColors.cyanAccent.withOpacity(0.4)
                    : AppColors.hairline,
              ),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                if (message.imageUrl != null) ...[
                  GestureDetector(
                    onTap: () => Navigator.of(context).push(
                      MaterialPageRoute<void>(
                        fullscreenDialog: true,
                        builder: (_) =>
                            _ChatPhotoViewer(url: message.imageUrl!),
                      ),
                    ),
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(10),
                      child: Image.network(
                        message.imageUrl!,
                        width: 210,
                        height: 160,
                        fit: BoxFit.cover,
                        loadingBuilder: (context, child, progress) =>
                            progress == null
                                ? child
                                : Container(
                                    width: 210,
                                    height: 160,
                                    color: AppColors.surfaceHigh,
                                    child: const Center(
                                      child: SizedBox(
                                        width: 22,
                                        height: 22,
                                        child: CircularProgressIndicator(
                                          strokeWidth: 2.2,
                                          color: AppColors.cyanAccent,
                                        ),
                                      ),
                                    ),
                                  ),
                        errorBuilder: (context, error, stack) => Container(
                          width: 210,
                          height: 160,
                          color: AppColors.surfaceHigh,
                          child: const Icon(
                            Icons.broken_image_outlined,
                            size: 34,
                            color: AppColors.textMuted,
                          ),
                        ),
                      ),
                    ),
                  ),
                  if (message.message.trim().isNotEmpty)
                    const SizedBox(height: 6),
                ],
                if (message.message.trim().isNotEmpty)
                  Text(
                    message.message,
                    style: TextStyle(
                      color:
                          pending ? AppColors.textMuted : AppColors.textPrimary,
                      fontSize: 14,
                      height: 1.35,
                    ),
                  ),
                const SizedBox(height: 3),
                Text(
                  pending ? 'Sending...' : time,
                  style: TextStyle(
                    color: AppColors.textMuted.withOpacity(0.85),
                    fontSize: 9.5,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// Message composer strip: photo button + text field + cyan send button.
class _Composer extends StatelessWidget {
  const _Composer({
    required this.controller,
    required this.onSend,
    required this.onPickPhoto,
    required this.enabled,
  });

  final TextEditingController controller;
  final VoidCallback onSend;
  final VoidCallback onPickPhoto;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 8, 16, 12),
        child: Row(
          children: [
            Material(
              color: AppColors.surfaceHigh,
              shape: const CircleBorder(),
              child: Tooltip(
                message: 'Send a photo',
                child: InkWell(
                  customBorder: const CircleBorder(),
                  onTap: enabled ? onPickPhoto : null,
                  child: Padding(
                    padding: const EdgeInsets.all(10),
                    child: Icon(
                      Icons.add_a_photo_outlined,
                      size: 19,
                      color: enabled
                          ? AppColors.cyanAccent
                          : AppColors.textMuted,
                    ),
                  ),
                ),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: TextField(
                controller: controller,
                enabled: enabled,
                minLines: 1,
                maxLines: 4,
                textInputAction: TextInputAction.send,
                onSubmitted: (_) => onSend(),
                style:
                    const TextStyle(color: AppColors.textPrimary, fontSize: 14),
                decoration: const InputDecoration(
                  hintText: 'Type a message...',
                ),
              ),
            ),
            const SizedBox(width: 10),
            Material(
              color: AppColors.cyanAccent,
              shape: const CircleBorder(),
              child: InkWell(
                customBorder: const CircleBorder(),
                onTap: enabled ? onSend : null,
                child: Padding(
                  padding: const EdgeInsets.all(11),
                  child: Icon(
                    Icons.send_rounded,
                    size: 19,
                    color: enabled ? Colors.black : AppColors.textMuted,
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Fullscreen black photo viewer opened by tapping a chat photo bubble.
class _ChatPhotoViewer extends StatelessWidget {
  const _ChatPhotoViewer({required this.url});

  final String url;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.black,
        foregroundColor: Colors.white,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.close, color: Colors.white),
          onPressed: () => Navigator.of(context).pop(),
        ),
      ),
      body: Center(
        child: InteractiveViewer(
          minScale: 1.0,
          maxScale: 4.0,
          child: Image.network(
            url,
            fit: BoxFit.contain,
            loadingBuilder: (context, child, progress) {
              if (progress == null) return child;
              return const Center(
                child: CircularProgressIndicator(
                  color: Colors.white70,
                  strokeWidth: 2.5,
                ),
              );
            },
            errorBuilder: (context, error, stack) => const Center(
              child: Icon(
                Icons.broken_image_outlined,
                size: 56,
                color: Colors.white38,
              ),
            ),
          ),
        ),
      ),
    );
  }
}
