import 'package:flutter/material.dart';

import 'app_theme.dart';

/// Horizontal trust-score meter (0-10 scale) with a numeric label.
/// Used on the product card (compact) and the seller profile card (full).
class TrustScoreMeter extends StatelessWidget {
  const TrustScoreMeter({
    super.key,
    required this.score,
    this.label = 'Seller trust',
    this.compact = false,
  });

  final double score;
  final String label;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    // Trust >= 5.0 (neutral default) reads as healthy -> cyan;
    // anything lower warns in amber.
    final fraction = (score / 10.0).clamp(0.0, 1.0).toDouble();
    final healthy = score >= 5.0;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.verified_user_outlined,
              size: compact ? 13 : 15,
              color: healthy ? AppColors.cyanAccent : AppColors.warning,
            ),
            const SizedBox(width: 6),
            Flexible(
              child: Text(
                '$label ${score.toStringAsFixed(1)}/10',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  color: AppColors.textMuted,
                  fontSize: compact ? 10.5 : 12.5,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 6),
        ClipRRect(
          borderRadius: BorderRadius.circular(999),
          child: LinearProgressIndicator(
            value: fraction,
            minHeight: compact ? 4 : 6,
            backgroundColor: AppColors.surfaceHigh,
            color: healthy ? AppColors.cyanAccent : AppColors.warning,
          ),
        ),
      ],
    );
  }
}
