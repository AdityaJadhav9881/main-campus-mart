import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/product.dart';
import '../providers/wishlist_provider.dart';
import '../services/currency.dart';
import 'app_theme.dart';
import 'category_icon.dart';
import 'condition_badge.dart';

/// Grid card used by the discovery feed.
///
/// Surfaces everything a buyer needs to judge a listing at a glance:
///  * photo with an **"N% BELOW AI VALUE"** discount badge when the asking
///    price beats the AI fair-value estimate,
///  * a **wishlist heart** (top-right) persisted through [WishlistProvider],
///  * AI category chip + condition badge,
///  * listed price alongside the strikethrough AI fair price,
///  * seller trust shield.
class ProductCard extends StatelessWidget {
  const ProductCard({
    super.key,
    required this.product,
    required this.onTap,
  });

  final Product product;
  final VoidCallback onTap;

  /// Discount vs the AI fair value, or null when there is nothing to show
  /// (no AI estimate, or the item is priced at/above fair value).
  int? get _discountPercent {
    final suggested = product.suggestedPrice;
    if (suggested == null || suggested <= 0) return null;
    if (product.listedPrice >= suggested) return null;
    final percent = ((suggested - product.listedPrice) / suggested * 100).round();
    if (percent < 1) return null;
    return percent;
  }

  @override
  Widget build(BuildContext context) {
    final wishlist = context.watch<WishlistProvider>();
    final saved = wishlist.contains(product.id);
    final suggested = product.suggestedPrice;
    final discount = _discountPercent;

    return Material(
      color: AppColors.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(18),
        side: const BorderSide(color: AppColors.hairline, width: 1),
      ),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              // Hero tag must match product_detail_screen.dart.
              child: Stack(
                fit: StackFit.expand,
                children: [
                  Hero(
                    tag: 'product-image-${product.id}',
                    child: _ProductImage(
                      url: product.imageUrl,
                      category: product.category,
                    ),
                  ),
                  if (discount != null)
                    Positioned(
                      top: 8,
                      left: 8,
                      child: _DiscountBadge(percent: discount),
                    ),
                  Positioned(top: 6, right: 6, child: _WishlistButton(
                    productId: product.id,
                    saved: saved,
                  )),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    product.title,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: AppColors.textPrimary,
                      fontSize: 13.5,
                      height: 1.25,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      Flexible(
                        child: _CategoryChip(label: product.category),
                      ),
                      const SizedBox(width: 6),
                      ConditionBadge(condition: product.condition, compact: true),
                    ],
                  ),
                  const SizedBox(height: 10),
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          formatInr(product.listedPrice),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            color: AppColors.inkBlack,
                            fontSize: 16.5,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                      ),
                      const SizedBox(width: 6),
                      _TrustPill(score: product.sellerTrustScore),
                    ],
                  ),
                  if (suggested != null && suggested > 0) ...[
                    const SizedBox(height: 4),
                    _AiFairPriceLine(
                      suggested: suggested,
                      listed: product.listedPrice,
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Discount callout painted over the photo ("30% BELOW AI VALUE").
class _DiscountBadge extends StatelessWidget {
  const _DiscountBadge({required this.percent});

  final int percent;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 4),
      decoration: BoxDecoration(
        color: AppColors.success.withOpacity(0.95),
        borderRadius: BorderRadius.circular(7),
        boxShadow: const [
          BoxShadow(color: Color(0x22000000), blurRadius: 4, offset: Offset(0, 2)),
        ],
      ),
      child: Text(
        '$percent% BELOW AI VALUE',
        style: const TextStyle(
          color: Colors.white,
          fontSize: 8.5,
          fontWeight: FontWeight.w900,
          letterSpacing: 0.3,
        ),
      ),
    );
  }
}

/// Glassmorphic heart toggle persisted in shared_preferences.
class _WishlistButton extends StatelessWidget {
  const _WishlistButton({required this.productId, required this.saved});

  final String productId;
  final bool saved;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        customBorder: const CircleBorder(),
        onTap: () => context.read<WishlistProvider>().toggle(productId),
        child: Container(
          padding: const EdgeInsets.all(6),
          decoration: BoxDecoration(
            color: Colors.black.withOpacity(0.55),
            shape: BoxShape.circle,
            border: Border.all(color: Colors.white24),
          ),
          child: Icon(
            saved ? Icons.favorite : Icons.favorite_border,
            size: 17,
            color: saved ? AppColors.danger : Colors.white,
          ),
        ),
      ),
    );
  }
}

/// Compact AI-category pill (single line, ellipsised for long labels).
class _CategoryChip extends StatelessWidget {
  const _CategoryChip({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: AppColors.royalBlue.withOpacity(0.08),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: AppColors.royalBlue.withOpacity(0.25)),
      ),
      child: Text(
        label.toUpperCase(),
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: const TextStyle(
          color: AppColors.royalBlue,
          fontSize: 10,
          fontWeight: FontWeight.w800,
          letterSpacing: 0.5,
        ),
      ),
    );
  }
}

/// Listed price vs AI fair value: "AI ₹80" struck through next to the ask.
class _AiFairPriceLine extends StatelessWidget {
  const _AiFairPriceLine({required this.suggested, required this.listed});

  final double suggested;
  final double listed;

  @override
  Widget build(BuildContext context) {
    final below = listed < suggested;
    return Row(
      children: [
        Flexible(
          child: Text(
            'AI fair ${formatInr(suggested)}',
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              color: AppColors.textMuted,
              fontSize: 11,
              fontWeight: FontWeight.w600,
              decoration: TextDecoration.lineThrough,
              decorationColor: AppColors.textMuted,
            ),
          ),
        ),
        const SizedBox(width: 6),
        Icon(
          below ? Icons.trending_down : Icons.trending_flat,
          size: 12,
          color: below ? AppColors.success : AppColors.warning,
        ),
        const SizedBox(width: 2),
        Text(
          below ? 'Deal' : 'Over',
          style: TextStyle(
            color: below ? AppColors.success : AppColors.warning,
            fontSize: 10,
            fontWeight: FontWeight.w800,
          ),
        ),
      ],
    );
  }
}

/// Compact trust indicator for the card's price row (shield icon + score).
class _TrustPill extends StatelessWidget {
  const _TrustPill({this.score});

  final double? score;

  @override
  Widget build(BuildContext context) {
    final hasScore = score != null;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(
          Icons.shield_outlined,
          size: 13,
          color: hasScore ? AppColors.cyanAccent : AppColors.textMuted,
        ),
        const SizedBox(width: 3),
        Text(
          hasScore ? score!.toStringAsFixed(1) : 'New',
          style: TextStyle(
            color: hasScore ? AppColors.textPrimary : AppColors.textMuted,
            fontSize: 11,
            fontWeight: FontWeight.w700,
          ),
        ),
      ],
    );
  }
}

/// Listing photo with graceful empty/error/loading states so the grid never
/// renders a broken image box - missing or blocked URLs fall back to a
/// category icon (book / flask / chip).
class _ProductImage extends StatelessWidget {
  const _ProductImage({required this.url, required this.category});

  final String url;
  final String category;

  @override
  Widget build(BuildContext context) {
    if (url.isEmpty) {
      return ImageFallbackIcon(category: category, size: 34);
    }
    return Image.network(
      url,
      width: double.infinity,
      fit: BoxFit.cover,
      loadingBuilder: (context, child, loadingProgress) {
        if (loadingProgress == null) return child;
        return const ImageLoadingIndicator(size: 22);
      },
      errorBuilder: (context, error, stackTrace) =>
          ImageFallbackIcon(category: category, size: 34),
    );
  }
}
