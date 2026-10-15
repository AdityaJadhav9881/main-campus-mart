import 'package:flutter/material.dart';

import 'app_theme.dart';

/// Maps a marketplace category (AI-assigned or seeded) to a representative
/// icon used by the network-image fallbacks across card and detail screens.
IconData categoryIconFor(String category) {
  final c = category.toLowerCase();
  if (c.contains('academic') ||
      c.contains('book') ||
      c.contains('textbook') ||
      c.contains('stationery') ||
      c.contains('notes')) {
    return Icons.menu_book_outlined;
  }
  if (c.contains('lab') ||
      c.contains('instrument') ||
      c.contains('science') ||
      c.contains('gear')) {
    return Icons.science_outlined;
  }
  if (c.contains('electronic') ||
      c.contains('gadget') ||
      c.contains('device') ||
      c.contains('calculator')) {
    return Icons.memory_outlined;
  }
  return Icons.category_outlined;
}

/// Elegant, category-aware placeholder shown when a listing image URL is
/// empty, still loading, or blocked by the network - never a crash box.
class ImageFallbackIcon extends StatelessWidget {
  const ImageFallbackIcon({
    super.key,
    required this.category,
    this.size = 40,
  });

  final String category;
  final double size;

  @override
  Widget build(BuildContext context) {
    return Container(
      color: AppColors.surfaceHigh,
      alignment: Alignment.center,
      child: Icon(
        categoryIconFor(category),
        size: size,
        color: AppColors.textMuted,
      ),
    );
  }
}

/// Thin cyan spinner used inside image loadingBuilders.
class ImageLoadingIndicator extends StatelessWidget {
  const ImageLoadingIndicator({super.key, this.size = 24});

  final double size;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: SizedBox(
        width: size,
        height: size,
        child: const CircularProgressIndicator(
          strokeWidth: 2.4,
          color: AppColors.cyanAccent,
        ),
      ),
    );
  }
}
