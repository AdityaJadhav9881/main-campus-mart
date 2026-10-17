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
import '../widgets/animated_brand_logo.dart';
import '../widgets/app_theme.dart';
import 'product_detail_screen.dart';

/// Tab 3 - Ask CampusMart AI (Part B Task 5 redesign).
///
/// Gemini/ChatGPT-style copilot over POST /ai/chat with saved conversations:
///   * history drawer (GET /ai/sessions) with reopen + delete,
///   * centered model badge under the title,
///   * "New chat" action,
///   * capability cards on the empty state,
///   * lightweight markdown rendering for assistant replies,
///   * product mini-cards for catalog matches,
///   * camera/gallery attach inside the pill composer.
class AiAssistantScreen extends StatefulWidget {
  const AiAssistantScreen({super.key});

  @override
  State<AiAssistantScreen> createState() => _AiAssistantScreenState();
}

class _AssistantTurn {
  _AssistantTurn(
    this.role,
    this.content, {
    this.recommendedIds,
    this.imageBytes,
    this.imageUrl,
  });

  final String role; // 'user' | 'assistant'
  final String content;
  final List<String>? recommendedIds;

  /// Local pixels of a photo the student attached (shown in their bubble);
  /// the Cloudinary URL itself is uploaded at send time.
  final Uint8List? imageBytes;

  /// Remote photo URL when a saved session is replayed from history.
  final String? imageUrl;
}

class _AiAssistantScreenState extends State<AiAssistantScreen> {
  final ApiService _api = ApiService.instance;
  final TextEditingController _input = TextEditingController();
  final ScrollController _scroll = ScrollController();

  final List<_AssistantTurn> _turns = <_AssistantTurn>[];
  bool _isThinking = false;

  /// Photo staged in the composer (removable preview chip) until sent.
  Uint8List? _pendingPhoto;
  String? _pendingPhotoName;

  /// Saved-conversation state (Task 5): null = a fresh, unsaved chat.
  String? _sessionId;
  String? _sessionTitle;
  List<AiSession> _sessions = const <AiSession>[];
  bool _sessionsLoading = false;
  String? _sessionsError;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _loadSessions();
    });
  }

  @override
  void dispose() {
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  // ---------------------------------------------------------------------------
  // Saved conversations
  // ---------------------------------------------------------------------------
  Future<void> _loadSessions() async {
    final token = context.read<AuthProvider>().token;
    if (token.isEmpty) return;
    setState(() {
      _sessionsLoading = _sessions.isEmpty;
      _sessionsError = null;
    });
    try {
      final rows = await _api.fetchAiSessions(token: token);
      if (!mounted) return;
      setState(() {
        _sessions = rows;
        _sessionsLoading = false;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _sessionsLoading = false;
        _sessionsError = error.message;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _sessionsLoading = false;
        _sessionsError = 'Could not load your chat history.';
      });
    }
  }

  Future<void> _openSession(AiSession session) async {
    final token = context.read<AuthProvider>().token;
    Navigator.of(context).pop(); // close the drawer
    setState(() => _sessionsLoading = true);
    try {
      final detail = await _api.fetchAiSession(
        sessionId: session.id,
        token: token,
      );
      if (!mounted) return;
      setState(() {
        _sessionId = detail.session.id;
        _sessionTitle = detail.session.title;
        _turns
          ..clear()
          ..addAll(
            detail.messages.map(
              (message) => _AssistantTurn(
                message.role,
                message.content,
                recommendedIds: message.matchedProductIds.isEmpty
                    ? null
                    : message.matchedProductIds,
                imageUrl: message.imageUrl,
              ),
            ),
          );
        _sessionsLoading = false;
      });
      _scrollToBottom();
    } catch (_) {
      if (!mounted) return;
      setState(() => _sessionsLoading = false);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Could not open that conversation.')),
      );
    }
  }

  Future<void> _deleteSession(AiSession session) async {
    final token = context.read<AuthProvider>().token;
    try {
      await _api.deleteAiSession(sessionId: session.id, token: token);
      if (!mounted) return;
      setState(() {
        _sessions = _sessions
            .where((row) => row.id != session.id)
            .toList(growable: false);
        if (_sessionId == session.id) {
          _sessionId = null;
          _sessionTitle = null;
          _turns.clear();
        }
      });
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Could not delete that conversation.')),
      );
    }
  }

  void _newChat() {
    setState(() {
      _sessionId = null;
      _sessionTitle = null;
      _turns.clear();
      _pendingPhoto = null;
      _pendingPhotoName = null;
    });
  }

  // ---------------------------------------------------------------------------
  // Composer / photo
  // ---------------------------------------------------------------------------
  Future<void> _pickPhoto() async {
    if (_isThinking) return;
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
      setState(() {
        _pendingPhoto = bytes;
        _pendingPhotoName = picked.name;
      });
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Could not open your photos: $error')),
      );
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scroll.hasClients) return;
      _scroll.animateTo(
        _scroll.position.maxScrollExtent,
        duration: const Duration(milliseconds: 250),
        curve: Curves.easeOut,
      );
    });
  }

  // ---------------------------------------------------------------------------
  // Ask
  // ---------------------------------------------------------------------------
  Future<void> _ask(String raw) async {
    final message = raw.trim();
    final photoBytes = _pendingPhoto;
    final photoName = _pendingPhotoName ?? 'assistant_photo.jpg';
    if ((message.isEmpty && photoBytes == null) || _isThinking) return;

    _input.clear();
    setState(() {
      _turns.add(_AssistantTurn('user', message, imageBytes: photoBytes));
      _pendingPhoto = null;
      _pendingPhotoName = null;
      _isThinking = true;
    });
    _scrollToBottom();

    // Transcript sent as history only for UNSAVED chats (the server owns the
    // transcript once a session exists, so history would double up).
    final history = <AiChatTurn>[];
    if (_sessionId == null) {
      final prior = _turns.length > 1
          ? _turns.sublist(0, _turns.length - 1)
          : const <_AssistantTurn>[];
      final start = prior.length > 10 ? prior.length - 10 : 0;
      for (final turn in prior.skip(start)) {
        if (turn.content.trim().isNotEmpty) {
          history.add(AiChatTurn(role: turn.role, content: turn.content));
        }
      }
    }

    final token = context.read<AuthProvider>().token;
    try {
      String? imageUrl;
      if (photoBytes != null) {
        imageUrl = await _api.uploadListingImage(
          bytes: photoBytes,
          filename: photoName,
          token: token,
        );
      }
      final reply = await _api.askAi(
        message: message,
        history: history,
        token: token,
        imageUrl: imageUrl,
        sessionId: _sessionId,
      );
      if (!mounted) return;
      setState(() {
        _turns.add(_AssistantTurn(
          'assistant',
          reply.reply,
          recommendedIds: reply.recommendedProductIds,
        ));
        if (reply.sessionId != null) _sessionId = reply.sessionId;
        if (reply.sessionTitle != null) _sessionTitle = reply.sessionTitle;
        _isThinking = false;
      });
      // Keep the drawer's history in sync (new row / fresh title / count).
      _loadSessions();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _turns.add(_AssistantTurn(
          'assistant',
          'I could not reach the assistant just now (${error.message}). '
          'Please try again.',
        ));
        _isThinking = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _turns.add(_AssistantTurn(
          'assistant',
          'Something went wrong talking to the assistant: $error',
        ));
        _isThinking = false;
      });
    }
    _scrollToBottom();
  }

  void _openProduct(String productId) {
    final feed = context.read<ProductProvider>();
    Product? product;
    for (final candidate in feed.products) {
      if (candidate.id == productId) {
        product = candidate;
        break;
      }
    }
    if (product == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('That listing is no longer in the live feed.'),
        ),
      );
      return;
    }
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => ProductDetailScreen(product: product!),
      ),
    );
  }

  // ---------------------------------------------------------------------------
  // Build
  // ---------------------------------------------------------------------------
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      drawer: _SessionDrawer(
        sessions: _sessions,
        loading: _sessionsLoading,
        error: _sessionsError,
        currentSessionId: _sessionId,
        onNewChat: () {
          Navigator.of(context).pop();
          _newChat();
        },
        onOpen: _openSession,
        onDelete: _deleteSession,
        onRefresh: _loadSessions,
      ),
      onDrawerChanged: (open) {
        if (open) _loadSessions();
      },
      appBar: AppBar(
        centerTitle: true,
        titleSpacing: 0,
        actions: [
          IconButton(
            tooltip: 'New chat',
            icon: const Icon(Icons.edit_square, size: 20),
            onPressed: _newChat,
          ),
        ],
        title: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              _sessionTitle ?? 'CampusMart AI',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                fontFamily: 'Georgia',
                color: AppColors.inkBlack,
                fontSize: 17,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: 3),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              decoration: BoxDecoration(
                color: AppColors.royalBlue.withOpacity(0.1),
                borderRadius: BorderRadius.circular(999),
                border: Border.all(
                  color: AppColors.royalBlue.withOpacity(0.3),
                ),
              ),
              child: const Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(Icons.auto_awesome, size: 9, color: AppColors.royalBlue),
                  SizedBox(width: 4),
                  Text(
                    'VISION + LIVE CAMPUS CATALOG',
                    style: TextStyle(
                      color: AppColors.royalBlue,
                      fontSize: 8,
                      fontWeight: FontWeight.w800,
                      letterSpacing: 0.6,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
      body: Column(
        children: [
          Expanded(child: _buildTranscript()),
          _Composer(
            controller: _input,
            onSend: () => _ask(_input.text),
            onPickPhoto: _pickPhoto,
            previewBytes: _pendingPhoto,
            onRemovePhoto: () => setState(() {
              _pendingPhoto = null;
              _pendingPhotoName = null;
            }),
          ),
        ],
      ),
    );
  }

  Widget _buildTranscript() {
    if (_turns.isEmpty) {
      return ListView(
        padding: const EdgeInsets.fromLTRB(20, 26, 20, 10),
        children: [
          const Center(child: AnimatedBrandLogo(size: 86)),
          const SizedBox(height: 18),
          const Text(
            'Your campus marketplace copilot',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: AppColors.textPrimary,
              fontSize: 17,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 8),
          const Text(
            'Search the live catalog, check fair prices, inspect a photo '
            'before you buy, or plan your next sale.',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: AppColors.textMuted,
              fontSize: 13,
              height: 1.5,
            ),
          ),
          const SizedBox(height: 22),
          _CapabilityGrid(
            onPrompt: _ask,
            onPhotoPrompt: _pickPhoto,
          ),
        ],
      );
    }

    return ListView.builder(
      controller: _scroll,
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
      itemCount: _turns.length + (_isThinking ? 1 : 0),
      itemBuilder: (context, index) {
        if (index == _turns.length) {
          return const _ThinkingBubble();
        }
        final turn = _turns[index];
        final mine = turn.role == 'user';
        return _TurnBubble(
          content: turn.content,
          mine: mine,
          recommendedIds: turn.recommendedIds,
          imageBytes: turn.imageBytes,
          imageUrl: turn.imageUrl,
          onOpenProduct: _openProduct,
        );
      },
    );
  }
}

// =============================================================================
// History drawer
// =============================================================================

/// Left drawer listing saved Ask-AI conversations, newest first.
class _SessionDrawer extends StatelessWidget {
  const _SessionDrawer({
    required this.sessions,
    required this.loading,
    required this.error,
    required this.currentSessionId,
    required this.onNewChat,
    required this.onOpen,
    required this.onDelete,
    required this.onRefresh,
  });

  final List<AiSession> sessions;
  final bool loading;
  final String? error;
  final String? currentSessionId;
  final VoidCallback onNewChat;
  final ValueChanged<AiSession> onOpen;
  final ValueChanged<AiSession> onDelete;
  final Future<void> Function() onRefresh;

  String _time(DateTime time) {
    final diff = DateTime.now().difference(time);
    if (diff.inMinutes < 1) return 'Just now';
    if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
    if (diff.inHours < 24) return '${diff.inHours}h ago';
    if (diff.inDays < 7) return '${diff.inDays}d ago';
    return '${time.day}/${time.month}/${time.year}';
  }

  @override
  Widget build(BuildContext context) {
    return Drawer(
      backgroundColor: AppColors.background,
      child: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 14, 16, 10),
              child: Row(
                children: [
                  const Icon(Icons.auto_awesome,
                      size: 18, color: AppColors.royalBlue),
                  const SizedBox(width: 8),
                  const Expanded(
                    child: Text(
                      'Chat history',
                      style: TextStyle(
                        fontFamily: 'Georgia',
                        color: AppColors.inkBlack,
                        fontSize: 17,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                  IconButton(
                    tooltip: 'New chat',
                    onPressed: onNewChat,
                    icon: const Icon(
                      Icons.edit_square,
                      size: 19,
                      color: AppColors.royalBlue,
                    ),
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: FilledButton.tonalIcon(
                onPressed: onNewChat,
                icon: const Icon(Icons.add, size: 17),
                label: const Text('New chat'),
                style: FilledButton.styleFrom(
                  minimumSize: const Size.fromHeight(42),
                  backgroundColor: AppColors.royalBlue.withOpacity(0.12),
                  foregroundColor: AppColors.royalBlue,
                ),
              ),
            ),
            const SizedBox(height: 8),
            Expanded(
              child: loading && sessions.isEmpty
                  ? const Center(
                      child: CircularProgressIndicator(
                        color: AppColors.royalBlue,
                        strokeWidth: 2.6,
                      ),
                    )
                  : error != null && sessions.isEmpty
                      ? Center(
                          child: Padding(
                            padding:
                                const EdgeInsets.symmetric(horizontal: 24),
                            child: Column(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                Text(
                                  error!,
                                  textAlign: TextAlign.center,
                                  style: const TextStyle(
                                    color: AppColors.textMuted,
                                    fontSize: 12.5,
                                  ),
                                ),
                                const SizedBox(height: 8),
                                TextButton(
                                  onPressed: onRefresh,
                                  child: const Text('Retry'),
                                ),
                              ],
                            ),
                          ),
                        )
                      : sessions.isEmpty
                          ? const Center(
                              child: Padding(
                                padding:
                                    EdgeInsets.symmetric(horizontal: 28),
                                child: Text(
                                  'No saved conversations yet.\nAsk something and it will be kept here.',
                                  textAlign: TextAlign.center,
                                  style: TextStyle(
                                    color: AppColors.textMuted,
                                    fontSize: 12.5,
                                    height: 1.5,
                                  ),
                                ),
                              ),
                            )
                          : RefreshIndicator(
                              color: AppColors.royalBlue,
                              backgroundColor: AppColors.surface,
                              onRefresh: onRefresh,
                              child: ListView.builder(
                                padding: const EdgeInsets.fromLTRB(
                                    10, 4, 10, 16),
                                itemCount: sessions.length,
                                itemBuilder: (context, index) {
                                  final session = sessions[index];
                                  final active =
                                      session.id == currentSessionId;
                                  return Material(
                                    color: active
                                        ? AppColors.royalBlue
                                            .withOpacity(0.09)
                                        : Colors.transparent,
                                    borderRadius: BorderRadius.circular(12),
                                    child: InkWell(
                                      borderRadius:
                                          BorderRadius.circular(12),
                                      onTap: () => onOpen(session),
                                      child: Padding(
                                        padding: const EdgeInsets.fromLTRB(
                                            10, 9, 4, 9),
                                        child: Row(
                                          children: [
                                            Icon(
                                              Icons.chat_bubble_outline,
                                              size: 16,
                                              color: active
                                                  ? AppColors.royalBlue
                                                  : AppColors.textMuted,
                                            ),
                                            const SizedBox(width: 10),
                                            Expanded(
                                              child: Column(
                                                crossAxisAlignment:
                                                    CrossAxisAlignment
                                                        .start,
                                                children: [
                                                  Text(
                                                    session.title,
                                                    maxLines: 1,
                                                    overflow: TextOverflow
                                                        .ellipsis,
                                                    style: TextStyle(
                                                      color: AppColors
                                                          .textPrimary,
                                                      fontSize: 13,
                                                      fontWeight: active
                                                          ? FontWeight.w800
                                                          : FontWeight.w600,
                                                    ),
                                                  ),
                                                  const SizedBox(height: 2),
                                                  Text(
                                                    '${session.messageCount} messages · ${_time(session.updatedAt)}',
                                                    style: const TextStyle(
                                                      color:
                                                          AppColors.textMuted,
                                                      fontSize: 10.5,
                                                    ),
                                                  ),
                                                ],
                                              ),
                                            ),
                                            IconButton(
                                              tooltip: 'Delete',
                                              onPressed: () =>
                                                  onDelete(session),
                                              icon: const Icon(
                                                Icons.delete_outline,
                                                size: 17,
                                                color: AppColors.textMuted,
                                              ),
                                            ),
                                          ],
                                        ),
                                      ),
                                    ),
                                  );
                                },
                              ),
                            ),
            ),
          ],
        ),
      ),
    );
  }
}

// =============================================================================
// Capability cards (empty state)
// =============================================================================

class _CapabilityGrid extends StatelessWidget {
  const _CapabilityGrid({
    required this.onPrompt,
    required this.onPhotoPrompt,
  });

  final ValueChanged<String> onPrompt;
  final VoidCallback onPhotoPrompt;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Row(
          children: [
            Expanded(
              child: _CapabilityCard(
                icon: Icons.local_offer_outlined,
                title: 'Best deals',
                subtitle: 'Find under-priced gear',
                onTap: () => onPrompt('Show me the best deals right now'),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: _CapabilityCard(
                icon: Icons.price_check,
                title: 'Fair price',
                subtitle: 'Is this price fair?',
                onTap: () => onPrompt(
                    'What is a fair price for a second-hand scientific calculator?'),
              ),
            ),
          ],
        ),
        const SizedBox(height: 10),
        Row(
          children: [
            Expanded(
              child: _CapabilityCard(
                icon: Icons.photo_camera_outlined,
                title: 'Photo inspect',
                subtitle: 'Analyse a photo first',
                onTap: onPhotoPrompt,
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: _CapabilityCard(
                icon: Icons.storefront_outlined,
                title: 'Sell smarter',
                subtitle: 'Tips to sell fast',
                onTap: () =>
                    onPrompt('What should I know before selling on campus?'),
              ),
            ),
          ],
        ),
      ],
    );
  }
}

class _CapabilityCard extends StatelessWidget {
  const _CapabilityCard({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: AppColors.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: const BorderSide(color: AppColors.hairline),
      ),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 32,
                height: 32,
                decoration: BoxDecoration(
                  color: AppColors.royalBlue.withOpacity(0.1),
                  borderRadius: BorderRadius.circular(9),
                ),
                child: Icon(icon, size: 17, color: AppColors.royalBlue),
              ),
              const SizedBox(height: 9),
              Text(
                title,
                style: const TextStyle(
                  color: AppColors.textPrimary,
                  fontSize: 12.5,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 2),
              Text(
                subtitle,
                style: const TextStyle(
                  color: AppColors.textMuted,
                  fontSize: 10.5,
                  height: 1.3,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// =============================================================================
// Markdown rendering (lightweight, no external package)
// =============================================================================

/// Minimal markdown block renderer for assistant replies: headings, bullets,
/// numbered lists, and inline **bold** / *italic* / `code`.
class _MarkdownText extends StatelessWidget {
  const _MarkdownText({required this.text, required this.baseStyle});

  final String text;
  final TextStyle baseStyle;

  static final RegExp _inline = RegExp(r'\*\*(.+?)\*\*|\*(.+?)\*|`([^`]+)`');

  List<InlineSpan> _spansFor(String line) {
    final spans = <InlineSpan>[];
    var index = 0;
    for (final match in _inline.allMatches(line)) {
      if (match.start > index) {
        spans.add(TextSpan(text: line.substring(index, match.start)));
      }
      final bold = match.group(1);
      final italic = match.group(2);
      final code = match.group(3);
      if (bold != null) {
        spans.add(TextSpan(
          text: bold,
          style: const TextStyle(fontWeight: FontWeight.w800),
        ));
      } else if (italic != null) {
        spans.add(TextSpan(
          text: italic,
          style: const TextStyle(fontStyle: FontStyle.italic),
        ));
      } else if (code != null) {
        spans.add(TextSpan(
          text: code,
          style: const TextStyle(
            fontFamily: 'monospace',
            backgroundColor: AppColors.surfaceHigh,
            color: AppColors.royalBlue,
          ),
        ));
      }
      index = match.end;
    }
    if (index < line.length) {
      spans.add(TextSpan(text: line.substring(index)));
    }
    return spans;
  }

  @override
  Widget build(BuildContext context) {
    final children = <Widget>[];
    for (final rawLine in text.split('\n')) {
      final line = rawLine.trimRight();
      final trimmed = line.trimLeft();

      if (trimmed.isEmpty) {
        children.add(const SizedBox(height: 6));
        continue;
      }

      if (trimmed.startsWith('### ')) {
        children.add(_line(
          trimmed.substring(4),
          baseStyle.copyWith(fontSize: 13.5, fontWeight: FontWeight.w800),
        ));
        continue;
      }
      if (trimmed.startsWith('## ')) {
        children.add(_line(
          trimmed.substring(3),
          baseStyle.copyWith(fontSize: 14.5, fontWeight: FontWeight.w800),
        ));
        continue;
      }
      if (trimmed.startsWith('# ')) {
        children.add(_line(
          trimmed.substring(2),
          baseStyle.copyWith(fontSize: 15.5, fontWeight: FontWeight.w800),
        ));
        continue;
      }

      if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
        children.add(Padding(
          padding: const EdgeInsets.only(bottom: 3),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('•  ', style: baseStyle),
              Expanded(
                child: Text.rich(
                  TextSpan(
                    style: baseStyle,
                    children: _spansFor(trimmed.substring(2)),
                  ),
                ),
              ),
            ],
          ),
        ));
        continue;
      }

      final numbered = RegExp(r'^(\d+)\.\s+(.*)$').firstMatch(trimmed);
      if (numbered != null) {
        children.add(Padding(
          padding: const EdgeInsets.only(bottom: 3),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('${numbered.group(1)}.  ', style: baseStyle),
              Expanded(
                child: Text.rich(
                  TextSpan(
                    style: baseStyle,
                    children: _spansFor(numbered.group(2) ?? ''),
                  ),
                ),
              ),
            ],
          ),
        ));
        continue;
      }

      children.add(
        Padding(
          padding: const EdgeInsets.only(bottom: 3),
          child: Text.rich(
            TextSpan(style: baseStyle, children: _spansFor(line)),
          ),
        ),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: children,
    );
  }

  Widget _line(String text, TextStyle style) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Text.rich(
        TextSpan(style: style, children: _spansFor(text)),
      ),
    );
  }
}

// =============================================================================
// Bubbles + composer
// =============================================================================

/// Assistant reply (or user question) bubble with optional photo + product
/// picks. Assistant text renders through the lightweight markdown renderer.
class _TurnBubble extends StatelessWidget {
  const _TurnBubble({
    required this.content,
    required this.mine,
    required this.recommendedIds,
    required this.onOpenProduct,
    this.imageBytes,
    this.imageUrl,
  });

  final String content;
  final bool mine;
  final List<String>? recommendedIds;
  final ValueChanged<String> onOpenProduct;
  final Uint8List? imageBytes;
  final String? imageUrl;

  @override
  Widget build(BuildContext context) {
    final picks = recommendedIds ?? const <String>[];
    final baseStyle = TextStyle(
      color: AppColors.textPrimary,
      fontSize: 14,
      height: 1.45,
      fontWeight: mine ? FontWeight.w600 : FontWeight.w400,
    );
    final hasRemotePhoto =
        imageBytes == null && (imageUrl ?? '').trim().isNotEmpty;

    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment:
            mine ? CrossAxisAlignment.end : CrossAxisAlignment.start,
        children: [
          Container(
            constraints: const BoxConstraints(maxWidth: 330),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
            decoration: BoxDecoration(
              color: mine
                  ? AppColors.royalBlue.withOpacity(0.16)
                  : AppColors.surface,
              borderRadius: BorderRadius.only(
                topLeft: const Radius.circular(14),
                topRight: const Radius.circular(14),
                bottomLeft: Radius.circular(mine ? 14 : 4),
                bottomRight: Radius.circular(mine ? 4 : 14),
              ),
              border: Border.all(
                color: mine
                    ? AppColors.royalBlue.withOpacity(0.4)
                    : AppColors.hairline,
              ),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (imageBytes != null) ...[
                  ClipRRect(
                    borderRadius: BorderRadius.circular(10),
                    child: Image.memory(
                      imageBytes!,
                      width: 210,
                      height: 160,
                      fit: BoxFit.cover,
                    ),
                  ),
                  if (content.trim().isNotEmpty) const SizedBox(height: 8),
                ] else if (hasRemotePhoto) ...[
                  ClipRRect(
                    borderRadius: BorderRadius.circular(10),
                    child: Image.network(
                      imageUrl!,
                      width: 210,
                      height: 160,
                      fit: BoxFit.cover,
                      errorBuilder: (context, error, stack) =>
                          const SizedBox.shrink(),
                    ),
                  ),
                  if (content.trim().isNotEmpty) const SizedBox(height: 8),
                ],
                if (content.trim().isNotEmpty)
                  mine
                      ? Text(content, style: baseStyle)
                      : _MarkdownText(text: content, baseStyle: baseStyle),
              ],
            ),
          ),
          if (picks.isNotEmpty)
            SizedBox(
              height: 104,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.only(top: 8),
                itemCount: picks.length,
                separatorBuilder: (context, index) => const SizedBox(width: 8),
                itemBuilder: (context, index) => _RecommendedCard(
                  productId: picks[index],
                  onOpen: onOpenProduct,
                ),
              ),
            ),
          if (picks.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                'Tap an item to open it',
                style: TextStyle(
                  color: AppColors.textMuted.withOpacity(0.9),
                  fontSize: 10.5,
                ),
              ),
            ),
        ],
      ),
    );
  }
}

/// Mini-card rendering one `recommended_product_ids` entry.
class _RecommendedCard extends StatelessWidget {
  const _RecommendedCard({
    required this.productId,
    required this.onOpen,
  });

  final String productId;
  final ValueChanged<String> onOpen;

  @override
  Widget build(BuildContext context) {
    final feed = context.watch<ProductProvider>();
    Product? product;
    for (final candidate in feed.products) {
      if (candidate.id == productId) {
        product = candidate;
        break;
      }
    }
    if (product == null) return const SizedBox.shrink();

    final resolved = product;
    return SizedBox(
      width: 150,
      child: Material(
        color: AppColors.surfaceHigh,
        borderRadius: BorderRadius.circular(12),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: () => onOpen(productId),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(
                height: 54,
                width: double.infinity,
                child: resolved.imageUrl.isEmpty
                    ? const ColoredBox(color: AppColors.surface)
                    : Image.network(
                        resolved.imageUrl,
                        fit: BoxFit.cover,
                        errorBuilder: (context, error, stack) =>
                            const ColoredBox(color: AppColors.surface),
                      ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(8, 6, 8, 8),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      resolved.title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: AppColors.textPrimary,
                        fontSize: 11.5,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      formatInr(resolved.listedPrice),
                      style: const TextStyle(
                        color: AppColors.royalBlue,
                        fontSize: 11.5,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Three-dot pulse shown while POST /ai/chat is in flight.
class _ThinkingBubble extends StatelessWidget {
  const _ThinkingBubble();

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Align(
        alignment: Alignment.centerLeft,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 13),
          decoration: BoxDecoration(
            color: AppColors.surface,
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: AppColors.hairline),
          ),
          child: const SizedBox(
            width: 34,
            height: 10,
            child: LinearProgressIndicator(
              backgroundColor: AppColors.surfaceHigh,
              color: AppColors.royalBlue,
              minHeight: 4,
            ),
          ),
        ),
      ),
    );
  }
}

/// Bottom pill composer: camera button, text field, send button - all inside
/// one rounded capsule like the modern AI chat apps (Task 5).
class _Composer extends StatelessWidget {
  const _Composer({
    required this.controller,
    required this.onSend,
    required this.onPickPhoto,
    required this.previewBytes,
    required this.onRemovePhoto,
  });

  final TextEditingController controller;
  final VoidCallback onSend;
  final VoidCallback onPickPhoto;
  final Uint8List? previewBytes;
  final VoidCallback onRemovePhoto;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 12),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (previewBytes != null) ...[
              Row(
                children: [
                  Stack(
                    clipBehavior: Clip.none,
                    children: [
                      ClipRRect(
                        borderRadius: BorderRadius.circular(10),
                        child: Image.memory(
                          previewBytes!,
                          width: 58,
                          height: 58,
                          fit: BoxFit.cover,
                        ),
                      ),
                      Positioned(
                        top: -7,
                        right: -7,
                        child: GestureDetector(
                          onTap: onRemovePhoto,
                          child: Container(
                            width: 20,
                            height: 20,
                            decoration: BoxDecoration(
                              color: AppColors.inkBlack,
                              shape: BoxShape.circle,
                              border: Border.all(color: Colors.white24),
                            ),
                            child: const Icon(
                              Icons.close,
                              size: 13,
                              color: Colors.white,
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(width: 10),
                  const Text(
                    'Photo ready - ask a question or send it as is',
                    style: TextStyle(
                      color: AppColors.textMuted,
                      fontSize: 11.5,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 8),
            ],
            Container(
              decoration: BoxDecoration(
                color: AppColors.surfaceHigh,
                borderRadius: BorderRadius.circular(26),
                border: Border.all(color: AppColors.hairline),
              ),
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Tooltip(
                    message: 'Attach a photo',
                    child: InkWell(
                      customBorder: const CircleBorder(),
                      onTap: onPickPhoto,
                      child: const Padding(
                        padding: EdgeInsets.all(9),
                        child: Icon(
                          Icons.photo_camera_outlined,
                          size: 20,
                          color: AppColors.royalBlue,
                        ),
                      ),
                    ),
                  ),
                  Expanded(
                    child: TextField(
                      controller: controller,
                      minLines: 1,
                      maxLines: 4,
                      textInputAction: TextInputAction.send,
                      onSubmitted: (_) => onSend(),
                      style: const TextStyle(
                        color: AppColors.textPrimary,
                        fontSize: 14,
                      ),
                      decoration: const InputDecoration(
                        isDense: true,
                        filled: false,
                        contentPadding:
                            EdgeInsets.symmetric(vertical: 10),
                        hintText: 'Ask anything...',
                        hintStyle: TextStyle(
                          color: AppColors.textMuted,
                          fontSize: 13.5,
                        ),
                        border: InputBorder.none,
                        enabledBorder: InputBorder.none,
                        focusedBorder: InputBorder.none,
                      ),
                    ),
                  ),
                  const SizedBox(width: 4),
                  Material(
                    color: AppColors.royalBlue,
                    shape: const CircleBorder(),
                    child: InkWell(
                      customBorder: const CircleBorder(),
                      onTap: onSend,
                      child: const Padding(
                        padding: EdgeInsets.all(9),
                        child: Icon(
                          Icons.arrow_upward_rounded,
                          size: 19,
                          color: Colors.black,
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
