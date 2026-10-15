import 'package:flutter/material.dart';

import '../models/product.dart';
import 'app_theme.dart';
import 'category_icon.dart';
import 'condition_badge.dart';

/// Grid card used by the discovery feed: image, title, condition badge,
/// listed price, and a compact seller trust-score indicator.
class ProductCard extends StatelessWidget {
  const ProductCard({
    super.key,
    required this.product,
    required this.onTap,
  });

  final Product product;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
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
              child: Hero(
                tag: 'product-image-${product.id}',
                child: _ProductImage(
                  url: product.imageUrl,
                  category: product.category,
                ),
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
                  ConditionBadge(condition: product.condition, compact: true),
                  const SizedBox(height: 10),
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          '\$${product.listedPrice.toStringAsFixed(2)}',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            color: AppColors.cyanAccent,
                            fontSize: 16,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                      ),
                      const SizedBox(width: 6),
                      _TrustPill(score: product.sellerTrustScore),
                    ],
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
