import 'package:flutter/material.dart';

import 'app_theme.dart';

/// Horizontal trust-score meter on the API's **0.0 - 5.0** scale with a
/// numeric label.
///
/// The backend caps trust at 5.0 (neutral start 5.0, admin approve +0.2,
/// sale +0.1, moderation -0.8), so the meter must read "4.9 / 5.0" and fill
/// with `score / 5.0` - the old "/10" render made every profile look 50% full.
///
/// Used on the product card (compact), the seller card, and the Profile tab.
class TrustScoreMeter extends StatelessWidget {
  const TrustScoreMeter({
    super.key,
    required this.score,
    this.label = 'Seller trust',
    this.compact = false,
  });

  /// Trust score on the 0-5.0 scale (values above 5.0 are clamped).
  final double score;
  final String label;
  final bool compact;

  /// Upper bound of the trust scale - matches the backend's cap.
  static const double maxScore = 5.0;

  @override
  Widget build(BuildContext context) {
    // Normalise onto 0..1 for the bar; clamp both ends so an out-of-range
    // value can never overflow the track.
    final fraction = (score / maxScore).clamp(0.0, 1.0).toDouble();
    // 4.5+ is outstanding, >= neutral 4.0 is healthy, below warns.
    final healthy = score >= 4.0;

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
                '$label ${score.toStringAsFixed(1)} / ${maxScore.toStringAsFixed(1)}',
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

/// Tier badge derived from a 0-5.0 trust score, used on the Profile tab.
String trustTierLabel(double score) {
  if (score >= 4.8) return 'Elite Trusted Student';
  if (score >= 4.5) return 'Highly Trusted Student';
  if (score >= 4.0) return 'Verified Student';
  if (score >= 3.0) return 'Rising Seller';
  return 'New Seller';
}

/// Accent colour that matches [trustTierLabel]'s tier.
Color trustTierColor(double score) {
  if (score >= 4.5) return const Color(0xFF34D399);
  if (score >= 4.0) return const Color(0xFF22D3EE);
  if (score >= 3.0) return const Color(0xFFFBBF24);
  return const Color(0xFFF87171);
}
