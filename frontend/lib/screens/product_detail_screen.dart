import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/product.dart';
import '../providers/auth_provider.dart';
import '../providers/product_provider.dart';
import '../providers/wishlist_provider.dart';
import '../services/api_service.dart';
import '../services/currency.dart';
import '../widgets/app_theme.dart';
import '../widgets/category_icon.dart';
import '../widgets/condition_badge.dart';
import '../widgets/trust_score_meter.dart';
import 'chat_thread_screen.dart';

/// Route pushed from the feed: full product presentation with Hero image,
/// the Multi-Agent AI Inspection Report, the live seller identity + trust
/// score, similar campus listings, and a pinned Buy bar wired to
/// POST /products/{id}/purchase.
class ProductDetailScreen extends StatefulWidget {
  const ProductDetailScreen({super.key, required this.product});

  final Product product;

  @override
  State<ProductDetailScreen> createState() => _ProductDetailScreenState();
}

class _ProductDetailScreenState extends State<ProductDetailScreen> {
  /// Local mirror of the lifecycle status so the button flips to "Sold"
  /// the instant a purchase succeeds, even before the feed refetches.
  late String _status = widget.product.status;
  bool _isPurchasing = false;

  Product get product => widget.product;

  bool get _isOwnListing =>
      context.read<AuthProvider>().profile?.id == product.sellerId;

  bool get _canBuy => _status == 'active' && !_isOwnListing && !_isPurchasing;

  Future<void> _purchase() async {
    if (!_canBuy) return;

    final auth = context.read<AuthProvider>();
    final messenger = ScaffoldMessenger.of(context);
    final feed = context.read<ProductProvider>();

    setState(() => _isPurchasing = true);
    try {
      final result = await ApiService.instance.purchaseProduct(
        productId: product.id,
        token: auth.token,
      );
      if (!mounted) return;
      setState(() => _status = result.productStatus);
      // Refresh the feed in the background so the sold badge appears on the
      // grid too (the provider keeps existing items visible during refresh).
      unawaited(feed.loadProducts());
      messenger.showSnackBar(
        SnackBar(
          backgroundColor: AppColors.success.withOpacity(0.92),
          content: Text(
            'Purchase confirmed — ${product.title} is yours! '
            '${formatInr(result.finalPrice)} paid.',
            style: const TextStyle(
              color: Colors.black,
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      messenger.showSnackBar(
        SnackBar(
          backgroundColor: AppColors.danger.withOpacity(0.92),
          content: Text(
            error.message,
            style: const TextStyle(color: Colors.black),
          ),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      messenger.showSnackBar(
        SnackBar(
          backgroundColor: AppColors.danger.withOpacity(0.92),
          content: Text(
            'Purchase failed: $error',
            style: const TextStyle(color: Colors.black),
          ),
        ),
      );
    } finally {
      if (mounted) setState(() => _isPurchasing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final wishlist = context.watch<WishlistProvider>();
    final saved = wishlist.contains(product.id);

    return Scaffold(
      backgroundColor: AppColors.background,
      // Pinned action bar: price on the left, Buy / Reserve Now on the right.
      bottomNavigationBar: _BottomBuyBar(
        product: product,
        status: _status,
        isPurchasing: _isPurchasing,
        isOwnListing: _isOwnListing,
        canBuy: _canBuy,
        onBuy: _purchase,
        onChat: _openChatWithSeller,
      ),
      body: CustomScrollView(
        slivers: [
          SliverAppBar(
            expandedHeight: 320,
            pinned: true,
            backgroundColor: AppColors.background,
            surfaceTintColor: Colors.transparent,
            // Glass badges stay legible over bright photos AND dark ones.
            leading: _GlassCircleButton(
              icon: Icons.arrow_back,
              tooltip: 'Back',
              onTap: () => Navigator.of(context).maybePop(),
            ),
            actions: [
              _GlassCircleButton(
                icon: saved ? Icons.favorite : Icons.favorite_border,
                tint: saved ? AppColors.danger : Colors.white,
                tooltip: saved ? 'Remove from Saved' : 'Save listing',
                onTap: () {
                  final nowSaved =
                      context.read<WishlistProvider>().toggle(product.id);
                  ScaffoldMessenger.of(context)
                    ..hideCurrentSnackBar()
                    ..showSnackBar(
                      SnackBar(
                        backgroundColor: AppColors.surfaceHigh,
                        content: Text(
                          nowSaved
                              ? 'Saved to your wishlist'
                              : 'Removed from your wishlist',
                          style: const TextStyle(
                            color: AppColors.textPrimary,
                          ),
                        ),
                      ),
                    );
                },
              ),
              const SizedBox(width: 6),
            ],
            flexibleSpace: FlexibleSpaceBar(
              background: Stack(
                fit: StackFit.expand,
                children: [
                  // Same Hero tag as ProductCard for the shared-element anim.
                  Hero(
                    tag: 'product-image-${product.id}',
                    child: _HeroGallery(product: product),
                  ),
                ],
              ),
            ),
          ),
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(20, 20, 20, 28),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // --- Category tag + condition + status ------------------
                  Row(
                    children: [
                      _CategoryTag(label: product.category),
                      const SizedBox(width: 10),
                      ConditionBadge(condition: product.condition),
                      if (_status != 'active') ...[
                        const SizedBox(width: 10),
                        _StatusBadge(status: _status),
                      ],
                    ],
                  ),
                  const SizedBox(height: 14),
                  Text(
                    product.title,
                    style: const TextStyle(
                      fontFamily: 'Georgia',
                      color: AppColors.inkBlack,
                      fontSize: 24,
                      height: 1.25,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 18),
                  _AiInspectionReport(product: product, status: _status),
                  const SizedBox(height: 20),
                  Text(
                    product.description,
                    style: const TextStyle(
                      color: AppColors.textMuted,
                      fontSize: 14.5,
                      height: 1.55,
                    ),
                  ),
                  if (product.tagList.isNotEmpty) ...[
                    const SizedBox(height: 18),
                    _AiTagsBlock(tags: product.tagList),
                  ],
                  const SizedBox(height: 26),
                  _buildSellerCard(),
                  if (_similarListings().isNotEmpty) ...[
                    const SizedBox(height: 26),
                    _SimilarListingsSection(
                      products: _similarListings(),
                      onOpen: (similar) {
                        Navigator.of(context).push(
                          MaterialPageRoute<void>(
                            builder: (_) =>
                                ProductDetailScreen(product: similar),
                          ),
                        );
                      },
                    ),
                  ],
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  /// "Similar Campus Listings": same category first, then title-word overlap
  /// with the rest of the live feed (self excluded).
  List<Product> _similarListings() {
    final feed = context.read<ProductProvider>().products;
    final candidates =
        feed.where((item) => item.id != product.id).toList(growable: false);
    if (candidates.isEmpty) return const <Product>[];

    final words = product.title
        .toLowerCase()
        .split(RegExp(r'\s+'))
        .where((word) => word.length > 3)
        .toSet();

    int score(Product item) {
      var value = item.category == product.category ? 100 : 0;
      for (final word in words) {
        if (item.title.toLowerCase().contains(word)) value += 10;
      }
      return value;
    }

    final ranked = [...candidates]..sort((a, b) {
        final byScore = score(b).compareTo(score(a));
        if (byScore != 0) return byScore;
        return b.createdAt.compareTo(a.createdAt);
      });

    return ranked.take(8).toList(growable: false);
  }

  // ---------------------------------------------------------------------------
  // Seller trust card
  // ---------------------------------------------------------------------------
  void _openChatWithSeller() {
    final sellerName = (product.sellerName ?? '').trim();
    final displayName = sellerName.isEmpty ? 'Campus Seller' : sellerName;
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => ChatThreadScreen(
          productId: product.id,
          productTitle: product.title,
          productImageUrl: product.imageUrl,
          productPrice: product.listedPrice,
          otherUserId: product.sellerId,
          otherUserName: displayName,
        ),
      ),
    );
  }

  Widget _buildSellerCard() {
    final trustScore = product.sellerTrustScore ?? 5.0;
    final sellerName = (product.sellerName ?? '').trim();
    final displayName = sellerName.isEmpty ? 'Campus Seller' : sellerName;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.hairline),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              CircleAvatar(
                radius: 22,
                backgroundColor: AppColors.surfaceHigh,
                child: Text(
                  displayName.isEmpty
                      ? '?'
                      : displayName.trim()[0].toUpperCase(),
                  style: const TextStyle(
                    color: AppColors.royalBlue,
                    fontSize: 18,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      displayName,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: AppColors.textPrimary,
                        fontSize: 15,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 5),
                    const _VerifiedBadge(),
                  ],
                ),
              ),
              Text(
                '${trustScore.toStringAsFixed(1)} / 5.0',
                style: const TextStyle(
                  color: AppColors.inkBlack,
                  fontSize: 15,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          TrustScoreMeter(score: trustScore, label: 'Trust score'),
          // Task 5: buyer-seller chat entry point on every active listing
          // the signed-in student does not own.
          if (!_isOwnListing && _status == 'active') ...[
            const SizedBox(height: 16),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: _openChatWithSeller,
                icon: const Icon(Icons.chat_bubble_outline, size: 17),
                label: const Text(
                  'Message Seller',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppColors.royalBlue,
                  side: BorderSide(
                    color: AppColors.royalBlue.withOpacity(0.55),
                    width: 1.2,
                  ),
                  minimumSize: const Size.fromHeight(46),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(12),
                  ),
                  textStyle: const TextStyle(
                    fontWeight: FontWeight.w700,
                    fontSize: 14,
                  ),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// Dark circular glassmorphic button used over the product photo
/// (back arrow + wishlist heart).
class _GlassCircleButton extends StatelessWidget {
  const _GlassCircleButton({
    required this.icon,
    required this.onTap,
    this.tooltip,
    this.tint = Colors.white,
  });

  final IconData icon;
  final VoidCallback onTap;
  final String? tooltip;
  final Color tint;

  @override
  Widget build(BuildContext context) {
    final button = Material(
      color: Colors.transparent,
      child: InkWell(
        customBorder: const CircleBorder(),
        onTap: onTap,
        child: Container(
          width: 38,
          height: 38,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: Colors.black.withOpacity(0.52),
            border: Border.all(color: Colors.white24),
            boxShadow: const [
              BoxShadow(color: Colors.black38, blurRadius: 8),
            ],
          ),
          child: Icon(icon, size: 20, color: tint),
        ),
      ),
    );
    if (tooltip == null) return Padding(padding: const EdgeInsets.all(6), child: button);
    return Padding(
      padding: const EdgeInsets.all(6),
      child: Tooltip(message: tooltip!, child: button),
    );
  }
}

/// "✨ Multi-Agent AI Inspection Report" - what each LangGraph agent decided
/// about this listing before it was allowed into the feed.
class _AiInspectionReport extends StatelessWidget {
  const _AiInspectionReport({required this.product, required this.status});

  final Product product;
  final String status;

  @override
  Widget build(BuildContext context) {
    final suggested = product.suggestedPrice;
    final isSafe = status == 'active';

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.royalBlue.withOpacity(0.25)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.auto_awesome, size: 15, color: AppColors.royalBlue),
              SizedBox(width: 7),
              Expanded(
                child: Text(
                  'Multi-Agent AI Inspection Report',
                  style: TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 13.5,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),

          // 1. Listing Intelligence Agent -------------------------------------
          _ReportRow(
            icon: Icons.category_outlined,
            color: AppColors.royalBlue,
            agent: 'Listing Intelligence Agent',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Verified category: ${product.category} · Condition: '
                  '${product.condition}',
                  style: const TextStyle(
                    color: AppColors.textMuted,
                    fontSize: 12.5,
                    height: 1.4,
                  ),
                ),
                if ((product.aiConditionNotes ?? '').trim().isNotEmpty) ...[
                  const SizedBox(height: 6),
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Icon(
                        Icons.photo_camera_outlined,
                        size: 13,
                        color: AppColors.royalBlue,
                      ),
                      const SizedBox(width: 5),
                      Expanded(
                        child: Text(
                          product.aiConditionNotes!.trim(),
                          style: const TextStyle(
                            color: AppColors.royalBlue,
                            fontSize: 12,
                            height: 1.4,
                          ),
                        ),
                      ),
                    ],
                  ),
                ],
              ],
            ),
          ),
          const _ReportDivider(),

          // 2. Price Prediction Agent ----------------------------------------
          _ReportRow(
            icon: Icons.insights_outlined,
            color: AppColors.warning,
            agent: 'Price Prediction Agent',
            child: _PriceComparison(
              listed: product.listedPrice,
              suggested: suggested,
            ),
          ),
          const _ReportDivider(),

          // 3. Trust & Fraud Agent -------------------------------------------
          _ReportRow(
            icon: isSafe ? Icons.verified_user_outlined : Icons.gpp_maybe_outlined,
            color: isSafe ? AppColors.success : AppColors.danger,
            agent: 'Trust & Fraud Agent',
            child: Row(
              children: [
                Icon(
                  isSafe ? Icons.check_circle : Icons.error_outline,
                  size: 14,
                  color: isSafe ? AppColors.success : AppColors.danger,
                ),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    isSafe
                        ? 'Verified Safe Listing — passed scam & abuse screening'
                        : 'Held for review: '
                            '${product.trustReason ?? 'failed safety screening'}',
                    style: TextStyle(
                      color: isSafe ? AppColors.success : AppColors.danger,
                      fontSize: 12.5,
                      fontWeight: FontWeight.w700,
                      height: 1.4,
                    ),
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

/// One agent row: agent icon + name on top, its verdict below.
class _ReportRow extends StatelessWidget {
  const _ReportRow({
    required this.icon,
    required this.color,
    required this.agent,
    required this.child,
  });

  final IconData icon;
  final Color color;
  final String agent;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(icon, size: 14, color: color),
            const SizedBox(width: 6),
            Expanded(
              child: Text(
                agent.toUpperCase(),
                style: const TextStyle(
                  color: AppColors.textMuted,
                  fontSize: 10,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 0.9,
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 7),
        child,
      ],
    );
  }
}

class _ReportDivider extends StatelessWidget {
  const _ReportDivider();

  @override
  Widget build(BuildContext context) {
    return const Padding(
      padding: EdgeInsets.symmetric(vertical: 12),
      child: Divider(color: AppColors.hairline),
    );
  }
}

/// Visual Listed-vs-AI-Fair-Value comparison with a savings badge.
class _PriceComparison extends StatelessWidget {
  const _PriceComparison({required this.listed, required this.suggested});

  final double listed;
  final double? suggested;

  @override
  Widget build(BuildContext context) {
    if (suggested == null || suggested! <= 0) {
      return const Text(
        'AI fair value pending — pricing model will confirm on demand.',
        style: TextStyle(
          color: AppColors.textMuted,
          fontSize: 12.5,
          height: 1.4,
        ),
      );
    }

    final fair = suggested!;
    final below = listed < fair;
    final percent =
        ((fair - listed) / fair * 100).round().abs().clamp(0, 99).toInt();
    final maxPrice = listed > fair ? listed : fair;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                'Listed  ${formatInr(listed)}',
                style: const TextStyle(
                  color: AppColors.textPrimary,
                  fontSize: 13.5,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ),
            if (below)
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
                decoration: BoxDecoration(
                  color: AppColors.success.withOpacity(0.15),
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(color: AppColors.success.withOpacity(0.5)),
                ),
                child: Text(
                  '$percent% BELOW AI VALUE',
                  style: const TextStyle(
                    color: AppColors.success,
                    fontSize: 9.5,
                    fontWeight: FontWeight.w900,
                    letterSpacing: 0.3,
                  ),
                ),
              ),
          ],
        ),
        const SizedBox(height: 8),
        _PriceBar(
          label: 'Listed',
          value: listed,
          max: maxPrice,
          color: AppColors.royalBlue,
        ),
        const SizedBox(height: 6),
        _PriceBar(
          label: 'AI fair',
          value: fair,
          max: maxPrice,
          color: AppColors.warning,
        ),
        const SizedBox(height: 6),
        Text(
          below
              ? 'You save ${formatInr(fair - listed)} vs the AI fair value.'
              : 'AI fair value is ${formatInr(fair)} — '
                  '${formatInr(listed - fair)} above estimate.',
          style: TextStyle(
            color: below ? AppColors.success : AppColors.warning,
            fontSize: 12,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    );
  }
}

class _PriceBar extends StatelessWidget {
  const _PriceBar({
    required this.label,
    required this.value,
    required this.max,
    required this.color,
  });

  final String label;
  final double value;
  final double max;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final fraction = max <= 0 ? 0.0 : (value / max).clamp(0.0, 1.0).toDouble();
    return Row(
      children: [
        SizedBox(
          width: 56,
          child: Text(
            label,
            style: const TextStyle(
              color: AppColors.textMuted,
              fontSize: 11,
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
        Expanded(
          child: ClipRRect(
            borderRadius: BorderRadius.circular(999),
            child: LinearProgressIndicator(
              value: fraction,
              minHeight: 7,
              backgroundColor: AppColors.surfaceHigh,
              color: color,
            ),
          ),
        ),
        const SizedBox(width: 8),
        SizedBox(
          width: 66,
          child: Text(
            formatInr(value),
            textAlign: TextAlign.right,
            style: TextStyle(
              color: color,
              fontSize: 11.5,
              fontWeight: FontWeight.w800,
            ),
          ),
        ),
      ],
    );
  }
}

/// Horizontal "Similar Campus Listings" rail (no Hero tags - the same item
/// may also exist on the source route's grid).
class _SimilarListingsSection extends StatelessWidget {
  const _SimilarListingsSection({required this.products, required this.onOpen});

  final List<Product> products;
  final ValueChanged<Product> onOpen;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Row(
          children: [
            Icon(Icons.grid_view_outlined, size: 15, color: AppColors.royalBlue),
            SizedBox(width: 7),
            Text(
              'Similar Campus Listings',
              style: TextStyle(
                color: AppColors.textPrimary,
                fontSize: 14,
                fontWeight: FontWeight.w800,
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        SizedBox(
          height: 168,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            itemCount: products.length,
            separatorBuilder: (context, index) => const SizedBox(width: 10),
            itemBuilder: (context, index) {
              final item = products[index];
              return SizedBox(
                width: 132,
                child: Material(
                  color: AppColors.surface,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14),
                    side: const BorderSide(color: AppColors.hairline),
                  ),
                  clipBehavior: Clip.antiAlias,
                  child: InkWell(
                    onTap: () => onOpen(item),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(
                          child: item.imageUrl.isEmpty
                              ? ImageFallbackIcon(
                                  category: item.category,
                                  size: 28,
                                )
                              : Image.network(
                                  item.imageUrl,
                                  fit: BoxFit.cover,
                                  width: double.infinity,
                                  errorBuilder: (context, error, stack) =>
                                      ImageFallbackIcon(
                                    category: item.category,
                                    size: 28,
                                  ),
                                ),
                        ),
                        Padding(
                          padding: const EdgeInsets.fromLTRB(8, 8, 8, 9),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                item.title,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                  color: AppColors.textPrimary,
                                  fontSize: 11.5,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                              const SizedBox(height: 4),
                              Row(
                                children: [
                                  Expanded(
                                    child: Text(
                                      formatInr(item.listedPrice),
                                      maxLines: 1,
                                      overflow: TextOverflow.ellipsis,
                                      style: const TextStyle(
                                        color: AppColors.inkBlack,
                                        fontSize: 13,
                                        fontWeight: FontWeight.w800,
                                      ),
                                    ),
                                  ),
                                  const Icon(
                                    Icons.shield_outlined,
                                    size: 11,
                                    color: AppColors.royalBlue,
                                  ),
                                  const SizedBox(width: 2),
                                  Text(
                                    (item.sellerTrustScore ?? 5.0)
                                        .toStringAsFixed(1),
                                    style: const TextStyle(
                                      color: AppColors.textMuted,
                                      fontSize: 10,
                                      fontWeight: FontWeight.w700,
                                    ),
                                  ),
                                ],
                              ),
                            ],
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
      ],
    );
  }
}

/// Pinned bottom action bar: price summary left, primary Buy button right.
class _BottomBuyBar extends StatelessWidget {
  const _BottomBuyBar({
    required this.product,
    required this.status,
    required this.isPurchasing,
    required this.isOwnListing,
    required this.canBuy,
    required this.onBuy,
    this.onChat,
  });

  final Product product;
  final String status;
  final bool isPurchasing;
  final bool isOwnListing;
  final bool canBuy;
  final VoidCallback onBuy;
  final VoidCallback? onChat;

  String get _label {
    if (isPurchasing) return 'Processing...';
    if (status == 'sold') return 'Sold';
    if (status == 'flagged') return 'Under Review';
    if (isOwnListing) return 'Your Listing';
    return 'Buy / Reserve Now';
  }

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.paddingOf(context).bottom;
    final sold = status == 'sold';
    final showChat = !isOwnListing && status == 'active' && onChat != null;

    return Container(
      padding: EdgeInsets.fromLTRB(16, 12, 16, 12 + bottom),
      decoration: const BoxDecoration(
        color: AppColors.surface,
        border: Border(top: BorderSide(color: AppColors.hairline)),
      ),
      child: Row(
        children: [
          Expanded(
            flex: 4,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                const Text(
                  'YOUR PRICE',
                  style: TextStyle(
                    color: AppColors.textMuted,
                    fontSize: 9.5,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 1.0,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  formatInr(product.listedPrice),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    color: sold ? AppColors.textMuted : AppColors.inkBlack,
                    fontSize: 18.5,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ],
            ),
          ),
          if (showChat) ...[
            const SizedBox(width: 8),
            Expanded(
              flex: 5,
              child: OutlinedButton.icon(
                onPressed: onChat,
                icon: const Icon(Icons.chat_bubble_outline, size: 15),
                label: const Text(
                  'Chat with Seller',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppColors.royalBlue,
                  side: BorderSide(
                    color: AppColors.royalBlue.withOpacity(0.55),
                    width: 1.2,
                  ),
                  padding: const EdgeInsets.symmetric(horizontal: 6),
                  minimumSize: const Size(0, 46),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(12),
                  ),
                  textStyle: const TextStyle(
                    fontWeight: FontWeight.w700,
                    fontSize: 12,
                  ),
                ),
              ),
            ),
          ],
          const SizedBox(width: 8),
          Expanded(
            flex: 6,
            child: FilledButton(
              onPressed: canBuy ? onBuy : null,
              style: FilledButton.styleFrom(
                backgroundColor: AppColors.inkBlack,
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(horizontal: 10),
                minimumSize: const Size(0, 46),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
                textStyle: const TextStyle(
                  fontWeight: FontWeight.w700,
                  fontSize: 12.5,
                ),
              ),
              child: isPurchasing
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(
                        strokeWidth: 2.2,
                        color: Colors.white,
                      ),
                    )
                  : Text(
                      _label,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Sold / flagged lifecycle pill shown next to the condition badge.
class _StatusBadge extends StatelessWidget {
  const _StatusBadge({required this.status});

  final String status;

  @override
  Widget build(BuildContext context) {
    final color = status == 'sold' ? AppColors.warning : AppColors.danger;
    final label = status == 'sold' ? 'SOLD' : 'UNDER REVIEW';
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: color.withOpacity(0.12),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withOpacity(0.5)),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: color,
          fontSize: 10.5,
          fontWeight: FontWeight.w800,
          letterSpacing: 0.8,
        ),
      ),
    );
  }
}

/// Verified-student pill (a student badge is granted server-side in Phase 5;
/// shown for every verified marketplace seller meanwhile).
class _VerifiedBadge extends StatelessWidget {
  const _VerifiedBadge();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: AppColors.forestGreen.withOpacity(0.12),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: AppColors.forestGreen.withOpacity(0.4)),
      ),
      child: const Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.verified, size: 12, color: AppColors.forestGreen),
          SizedBox(width: 4),
          Text(
            'Verified Student',
            style: TextStyle(
              color: AppColors.forestGreen,
              fontSize: 10,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }
}

/// Outlined tag showing the AI-assigned marketplace category.
class _CategoryTag extends StatelessWidget {
  const _CategoryTag({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: AppColors.royalBlue.withOpacity(0.08),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: AppColors.royalBlue.withOpacity(0.35)),
      ),
      child: Text(
        label.toUpperCase(),
        style: const TextStyle(
          color: AppColors.royalBlue,
          fontSize: 10.5,
          fontWeight: FontWeight.w800,
          letterSpacing: 0.8,
        ),
      ),
    );
  }
}

/// Hero detail image with graceful empty/loading/error states - a missing
/// or blocked URL renders the category icon instead of a crash box.
class _DetailImage extends StatelessWidget {
  const _DetailImage({required this.url, required this.category});

  final String url;
  final String category;

  @override
  Widget build(BuildContext context) {
    if (url.isEmpty) {
      return ImageFallbackIcon(category: category, size: 56);
    }
    return Image.network(
      url,
      fit: BoxFit.cover,
      loadingBuilder: (context, child, loadingProgress) {
        if (loadingProgress == null) return child;
        return const ImageLoadingIndicator(size: 28);
      },
      errorBuilder: (context, error, stackTrace) =>
          ImageFallbackIcon(category: category, size: 56),
    );
  }
}

/// 4-angle photo gallery inside the Hero header: swipeable PageView over
/// [Product.photos] (front/back/side/label from the vision scan, else just
/// the cover) with a page counter + dot indicator and the app's signature
/// top/bottom scrim.
class _HeroGallery extends StatefulWidget {
  const _HeroGallery({required this.product});

  final Product product;

  @override
  State<_HeroGallery> createState() => _HeroGalleryState();
}

class _HeroGalleryState extends State<_HeroGallery> {
  late final PageController _controller;
  int _page = 0;

  @override
  void initState() {
    super.initState();
    _controller = PageController();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _openLightbox(int initialIndex, List<String> images) {
    if (images.isEmpty) return;
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        fullscreenDialog: true,
        builder: (_) => _LightboxViewer(
          images: images,
          initialIndex: initialIndex,
          category: widget.product.category,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final category = widget.product.category;
    final photos = widget.product.photos;

    return Stack(
      fit: StackFit.expand,
      children: [
        if (photos.isEmpty)
          GestureDetector(
            onTap: () {
              if (widget.product.imageUrl.isNotEmpty) {
                _openLightbox(0, [widget.product.imageUrl]);
              }
            },
            child: _DetailImage(url: widget.product.imageUrl, category: category),
          )
        else
          PageView.builder(
            controller: _controller,
            itemCount: photos.length,
            onPageChanged: (page) => setState(() => _page = page),
            itemBuilder: (context, index) => GestureDetector(
              onTap: () => _openLightbox(index, photos),
              child: _DetailImage(
                url: photos[index],
                category: category,
              ),
            ),
          ),
        const DecoratedBox(
          decoration: BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
              colors: [
                Color(0x55000000),
                Colors.transparent,
                Color(0xAA0A0E14),
              ],
              stops: [0.0, 0.45, 1.0],
            ),
          ),
        ),
        if (photos.length > 1) ...[
          Positioned(
            left: 14,
            bottom: 12,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              decoration: BoxDecoration(
                color: Colors.black.withOpacity(0.55),
                borderRadius: BorderRadius.circular(999),
                border: Border.all(color: Colors.white24),
              ),
              child: Text(
                '${_page + 1} / ${photos.length}',
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
          ),
          Positioned(
            right: 14,
            bottom: 14,
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                for (var index = 0; index < photos.length; index++)
                  AnimatedContainer(
                    duration: const Duration(milliseconds: 180),
                    margin: const EdgeInsets.only(left: 5),
                    width: index == _page ? 16 : 6,
                    height: 6,
                    decoration: BoxDecoration(
                      color: index == _page
                          ? AppColors.royalBlue
                          : Colors.white54,
                      borderRadius: BorderRadius.circular(999),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ],
    );
  }
}

/// "AI search tags" chips produced by the 4-photo vision scan - shows the
/// keywords buyers can discover this listing with.
class _AiTagsBlock extends StatelessWidget {
  const _AiTagsBlock({required this.tags});

  final List<String> tags;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Row(
          children: [
            Icon(Icons.tag, size: 14, color: AppColors.royalBlue),
            SizedBox(width: 6),
            Text(
              'AI Search Tags',
              style: TextStyle(
                color: AppColors.textMuted,
                fontSize: 11,
                fontWeight: FontWeight.w800,
                letterSpacing: 0.8,
              ),
            ),
          ],
        ),
        const SizedBox(height: 9),
        Wrap(
          spacing: 7,
          runSpacing: 7,
          children: [
            for (final tag in tags)
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
                decoration: BoxDecoration(
                  color: AppColors.surface,
                  borderRadius: BorderRadius.circular(999),
                  border: Border.all(color: AppColors.hairline),
                ),
                child: Text(
                  tag,
                  style: const TextStyle(
                    color: AppColors.textMuted,
                    fontSize: 11.5,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
          ],
        ),
      ],
    );
  }
}

/// Full-screen zoomable lightbox viewer for inspecting photos from all angles.
class _LightboxViewer extends StatefulWidget {
  const _LightboxViewer({
    required this.images,
    required this.initialIndex,
    required this.category,
  });

  final List<String> images;
  final int initialIndex;
  final String category;

  @override
  State<_LightboxViewer> createState() => _LightboxViewerState();
}

class _LightboxViewerState extends State<_LightboxViewer> {
  late final PageController _pageController;
  late int _currentIndex;

  @override
  void initState() {
    super.initState();
    _currentIndex = widget.initialIndex;
    _pageController = PageController(initialPage: widget.initialIndex);
  }

  @override
  void dispose() {
    _pageController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.black.withOpacity(0.85),
        foregroundColor: Colors.white,
        elevation: 0,
        title: Text(
          'Photo ${_currentIndex + 1} of ${widget.images.length}',
          style: const TextStyle(
            color: Colors.white,
            fontSize: 16,
            fontWeight: FontWeight.w700,
          ),
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.close, color: Colors.white),
            onPressed: () => Navigator.of(context).pop(),
          ),
        ],
      ),
      body: Stack(
        alignment: Alignment.bottomCenter,
        children: [
          PageView.builder(
            controller: _pageController,
            itemCount: widget.images.length,
            onPageChanged: (index) => setState(() => _currentIndex = index),
            itemBuilder: (context, index) {
              final url = widget.images[index];
              return InteractiveViewer(
                minScale: 1.0,
                maxScale: 4.0,
                child: Center(
                  child: url.isEmpty
                      ? ImageFallbackIcon(category: widget.category, size: 64)
                      : Image.network(
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
                          errorBuilder: (context, error, stack) =>
                              ImageFallbackIcon(category: widget.category, size: 64),
                        ),
                ),
              );
            },
          ),
          if (widget.images.length > 1)
            Padding(
              padding: const EdgeInsets.only(bottom: 24),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: List.generate(
                  widget.images.length,
                  (index) => Container(
                    margin: const EdgeInsets.symmetric(horizontal: 4),
                    width: index == _currentIndex ? 16 : 6,
                    height: 6,
                    decoration: BoxDecoration(
                      color: index == _currentIndex
                          ? AppColors.royalBlue
                          : Colors.white38,
                      borderRadius: BorderRadius.circular(999),
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}
