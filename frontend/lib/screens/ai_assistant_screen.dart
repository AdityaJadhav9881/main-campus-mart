import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/chat_models.dart';
import '../models/product.dart';
import '../providers/auth_provider.dart';
import '../providers/product_provider.dart';
import '../services/api_service.dart';
import '../services/currency.dart';
import '../widgets/app_theme.dart';
import 'product_detail_screen.dart';

/// Tab 3 - Ask CampusMart AI.
///
/// A catalog-aware assistant (POST /ai/chat): the backend answers with the
/// configured LLM when a key is present, or falls back to a rule-based local
/// assistant that can still recommend real listings. Recommended items come
/// back as `recommended_product_ids` and render as tappable mini-cards.
class AiAssistantScreen extends StatefulWidget {
  const AiAssistantScreen({super.key});

  @override
  State<AiAssistantScreen> createState() => _AiAssistantScreenState();
}

class _AssistantTurn {
  _AssistantTurn(this.role, this.content, {this.recommendedIds});

  final String role; // 'user' | 'assistant'
  final String content;
  final List<String>? recommendedIds;
}

const List<String> _suggestions = <String>[
  'Show me the best deals right now',
  'I need a calculator for engineering',
  'What should I know before selling?',
  'Any lab gear under ₹500?',
];

class _AiAssistantScreenState extends State<AiAssistantScreen> {
  final ApiService _api = ApiService.instance;
  final TextEditingController _input = TextEditingController();
  final ScrollController _scroll = ScrollController();

  final List<_AssistantTurn> _turns = <_AssistantTurn>[];
  bool _isThinking = false;

  @override
  void dispose() {
    _input.dispose();
    _scroll.dispose();
    super.dispose();
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

  Future<void> _ask(String raw) async {
    final message = raw.trim();
    if (message.isEmpty || _isThinking) return;
    _input.clear();
    setState(() {
      _turns.add(_AssistantTurn('user', message));
      _isThinking = true;
    });
    _scrollToBottom();

    // Transcript sent as history (oldest first; at most the last 10 turns,
    // excluding the message being sent right now).
    final prior = _turns.length > 1
        ? _turns.sublist(0, _turns.length - 1)
        : const <_AssistantTurn>[];
    final start = prior.length > 10 ? prior.length - 10 : 0;
    final history = <AiChatTurn>[
      for (final turn in prior.skip(start))
        AiChatTurn(role: turn.role, content: turn.content),
    ];

    try {
      final reply = await _api.askAi(
        message: message,
        history: history,
        token: context.read<AuthProvider>().token,
      );
      if (!mounted) return;
      setState(() {
        _turns.add(_AssistantTurn(
          'assistant',
          reply.reply,
          recommendedIds: reply.recommendedProductIds,
        ));
        _isThinking = false;
      });
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

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        titleSpacing: 16,
        title: const Row(
          children: [
            Icon(Icons.auto_awesome, size: 20, color: AppColors.royalBlue),
            SizedBox(width: 10),
            Text(
              'Ask CampusMart AI',
              style: TextStyle(
                fontFamily: 'Georgia',
                color: AppColors.inkBlack,
                fontSize: 19,
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
        ),
      ),
      body: Column(
        children: [
          Expanded(child: _buildTranscript()),
          if (_turns.isEmpty) _SuggestionChips(onPick: _ask),
          _Composer(controller: _input, onSend: () => _ask(_input.text)),
        ],
      ),
    );
  }

  Widget _buildTranscript() {
    if (_turns.isEmpty) {
      return ListView(
        padding: const EdgeInsets.fromLTRB(24, 12, 24, 8),
        children: const [
          SizedBox(height: 40),
          Icon(Icons.chat_bubble_outline,
              size: 44, color: AppColors.textMuted),
          SizedBox(height: 16),
          Text(
            'Your campus marketplace copilot',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: AppColors.textPrimary,
              fontSize: 17,
              fontWeight: FontWeight.w800,
            ),
          ),
          SizedBox(height: 10),
          Text(
            'Ask about items for sale, fair prices, selling tips, or what is '
            'trending on campus. I know the live catalog.',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: AppColors.textMuted,
              fontSize: 13.5,
              height: 1.5,
            ),
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
          onOpenProduct: _openProduct,
        );
      },
    );
  }
}

/// Opening greeting + quick-start chips (visible only on an empty chat).
class _SuggestionChips extends StatelessWidget {
  const _SuggestionChips({required this.onPick});

  final ValueChanged<String> onPick;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
      child: Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          for (final suggestion in _suggestions)
            ActionChip(
              label: Text(suggestion),
              onPressed: () => onPick(suggestion),
              backgroundColor: AppColors.surface,
              side: BorderSide(color: AppColors.royalBlue.withOpacity(0.35)),
              labelStyle: const TextStyle(
                color: AppColors.textPrimary,
                fontSize: 12,
                fontWeight: FontWeight.w600,
              ),
            ),
        ],
      ),
    );
  }
}

/// Assistant reply (or user question) bubble with optional product picks.
class _TurnBubble extends StatelessWidget {
  const _TurnBubble({
    required this.content,
    required this.mine,
    required this.recommendedIds,
    required this.onOpenProduct,
  });

  final String content;
  final bool mine;
  final List<String>? recommendedIds;
  final ValueChanged<String> onOpenProduct;

  @override
  Widget build(BuildContext context) {
    final picks = recommendedIds ?? const <String>[];
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
            child: Text(
              content,
              style: TextStyle(
                color: AppColors.textPrimary,
                fontSize: 14,
                height: 1.45,
                fontWeight: mine ? FontWeight.w600 : FontWeight.w400,
              ),
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

/// Bottom input row for the assistant.
class _Composer extends StatelessWidget {
  const _Composer({required this.controller, required this.onSend});

  final TextEditingController controller;
  final VoidCallback onSend;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 12),
        child: Row(
          children: [
            Expanded(
              child: TextField(
                controller: controller,
                minLines: 1,
                maxLines: 4,
                textInputAction: TextInputAction.send,
                onSubmitted: (_) => onSend(),
                style:
                    const TextStyle(color: AppColors.textPrimary, fontSize: 14),
                decoration: const InputDecoration(
                  hintText: 'Ask about items, prices, selling tips...',
                ),
              ),
            ),
            const SizedBox(width: 10),
            Material(
              color: AppColors.royalBlue,
              shape: const CircleBorder(),
              child: InkWell(
                customBorder: const CircleBorder(),
                onTap: onSend,
                child: const Padding(
                  padding: EdgeInsets.all(11),
                  child: Icon(Icons.arrow_upward_rounded,
                      size: 19, color: Colors.black),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
