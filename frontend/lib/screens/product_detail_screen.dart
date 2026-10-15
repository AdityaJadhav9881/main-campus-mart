import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/product.dart';
import '../providers/auth_provider.dart';
import '../providers/product_provider.dart';
import '../services/api_service.dart';
import '../widgets/app_theme.dart';
import '../widgets/category_icon.dart';
import '../widgets/condition_badge.dart';
import '../widgets/trust_score_meter.dart';

/// Route pushed from the feed: full product presentation with Hero image,
/// AI price comparison, seller trust card, and the Phase 7 buy action wired
/// to POST /products/{id}/purchase.
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
            '\$${result.finalPrice.toStringAsFixed(2)} paid.',
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
    return Scaffold(
      body: CustomScrollView(
        slivers: [
          SliverAppBar(
            expandedHeight: 300,
            pinned: true,
            backgroundColor: AppColors.voidBlack,
            flexibleSpace: FlexibleSpaceBar(
              background: Stack(
                fit: StackFit.expand,
                children: [
                  // Same Hero tag as ProductCard for the shared-element anim.
                  Hero(
                    tag: 'product-image-${product.id}',
                    child: _DetailImage(
                      url: product.imageUrl,
                      category: product.category,
                    ),
                  ),
                  const DecoratedBox(
                    decoration: BoxDecoration(
                      gradient: LinearGradient(
                        begin: Alignment.topCenter,
                        end: Alignment.bottomCenter,
                        colors: [Colors.transparent, Color(0xAA0A0E14)],
                        stops: [0.55, 1.0],
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(20, 20, 20, 32),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // --- Category tag + condition -----------------------------
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
                      color: AppColors.textPrimary,
                      fontSize: 24,
                      height: 1.2,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  const SizedBox(height: 18),
                  _buildPriceSection(),
                  const SizedBox(height: 22),
                  Text(
                    product.description,
                    style: const TextStyle(
                      color: AppColors.textMuted,
                      fontSize: 14.5,
                      height: 1.55,
                    ),
                  ),
                  const SizedBox(height: 26),
                  _buildSellerCard(),
                  const SizedBox(height: 26),
                  FilledButton.icon(
                    icon: _isPurchasing
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.black,
                            ),
                          )
                        : Icon(
                            _status == 'sold'
                                ? Icons.check_circle_outline
                                : Icons.shopping_bag_outlined,
                            size: 20,
                          ),
                    label: Text(_buyButtonLabel()),
                    onPressed: _canBuy ? _purchase : null,
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  String _buyButtonLabel() {
    if (_isPurchasing) return 'Processing...';
    if (_status == 'sold') return 'Sold';
    if (_status == 'flagged') return 'Under Review';
    if (_isOwnListing) return 'Your Listing';
    return 'Buy Now — \$${product.listedPrice.toStringAsFixed(2)}';
  }

  // ---------------------------------------------------------------------------
  // Price + AI comparison
  // ---------------------------------------------------------------------------
  Widget _buildPriceSection() {
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
          const Text(
            'LISTED PRICE',
            style: TextStyle(
              color: AppColors.textMuted,
              fontSize: 10.5,
              fontWeight: FontWeight.w700,
              letterSpacing: 1.1,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            '\$${product.listedPrice.toStringAsFixed(2)}',
            style: const TextStyle(
              color: AppColors.cyanAccent,
              fontSize: 30,
              fontWeight: FontWeight.w800,
            ),
          ),
          if (product.suggestedPrice case final double? suggested
              when suggested != null) ...[
            const SizedBox(height: 12),
            _ComparisonTag(suggestedPrice: suggested, listedPrice: product.listedPrice),
          ],
        ],
      ),
    );
  }

  // ---------------------------------------------------------------------------
  // Seller trust card
  // ---------------------------------------------------------------------------
  Widget _buildSellerCard() {
    final trustScore = product.sellerTrustScore ?? 5.0;
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
          const Row(
            children: [
              CircleAvatar(
                radius: 22,
                backgroundColor: AppColors.surfaceHigh,
                child: Icon(
                  Icons.school_outlined,
                  color: AppColors.cyanAccent,
                  size: 22,
                ),
              ),
              SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Campus Seller',
                      style: TextStyle(
                        color: AppColors.textPrimary,
                        fontSize: 15,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    SizedBox(height: 5),
                    _VerifiedBadge(),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          TrustScoreMeter(score: trustScore, label: 'Trust score'),
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
        color: AppColors.cyanAccent.withOpacity(0.12),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: AppColors.cyanAccent.withOpacity(0.5)),
      ),
      child: const Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.verified, size: 12, color: AppColors.cyanAccent),
          SizedBox(width: 4),
          Text(
            'Verified Student',
            style: TextStyle(
              color: AppColors.cyanAccent,
              fontSize: 10,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }
}

/// Compares the seller's asking price against the AI fair value and renders
/// an explanatory tag ("Fair Resale Value confirmed by AI" when fair).
class _ComparisonTag extends StatelessWidget {
  const _ComparisonTag({
    required this.suggestedPrice,
    required this.listedPrice,
  });

  final double suggestedPrice;
  final double listedPrice;

  @override
  Widget build(BuildContext context) {
    final isFair = listedPrice <= suggestedPrice;
    final color = isFair ? AppColors.success : AppColors.warning;
    final text = isFair
        ? 'Fair Resale Value confirmed by AI '
            '(fair value \$${suggestedPrice.toStringAsFixed(2)})'
        : 'AI fair value is \$${suggestedPrice.toStringAsFixed(2)} - '
            'this listing is '
            '\$${(listedPrice - suggestedPrice).toStringAsFixed(2)} above estimate';

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: color.withOpacity(0.1),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withOpacity(0.45)),
      ),
      child: Row(
        children: [
          Icon(
            isFair ? Icons.verified_outlined : Icons.insights_outlined,
            size: 16,
            color: color,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              style: TextStyle(
                color: color,
                fontSize: 12.5,
                fontWeight: FontWeight.w700,
                height: 1.35,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Cyan outlined tag showing the AI-assigned marketplace category.
class _CategoryTag extends StatelessWidget {
  const _CategoryTag({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: AppColors.cyanAccent.withOpacity(0.1),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: AppColors.cyanAccent.withOpacity(0.45)),
      ),
      child: Text(
        label.toUpperCase(),
        style: const TextStyle(
          color: AppColors.cyanAccent,
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
