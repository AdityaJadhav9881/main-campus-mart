import '../models/product.dart';

/// Client-side "Recommendation Agent" for the Discover screen.
///
/// Mirrors the spirit of the backend's multi-agent pipeline: rank listings by
/// how good a deal they are (listed price vs the AI fair-value estimate) and
/// how credible the seller is (live trust score), then return the best few
/// for the "✨ AI Recommended For You" carousel.
///
/// Scoring (0..1, higher is better):
///   * value  - discount vs AI fair price. Listed at/below the AI estimate
///              scores high; way above it scores low.
///   * trust  - seller trust normalised on the 0-5.0 scale used by the API.
///   * fresh  - newer listings get a small tie-break boost so the rail never
///              feels stale.
///   score = 0.55 * value + 0.40 * trust + 0.05 * fresh
abstract final class RecommendationEngine {
  static const double _valueWeight = 0.55;
  static const double _trustWeight = 0.40;
  static const double _freshWeight = 0.05;

  /// Product IDs already handed to the user, so repeated refreshes can still
  /// surface variety if a caller wants to rotate.
  static const int defaultLimit = 8;

  /// Returns up to [limit] listings ranked best-first.
  ///
  /// Only active listings with a usable price qualify; items the caller
  /// wants hidden (e.g. the viewer's own listing) can be excluded via
  /// [excludeIds].
  static List<Product> rankForYou(
    List<Product> products, {
    int limit = defaultLimit,
    Set<String> excludeIds = const <String>{},
  }) {
    final candidates = products.where(
      (product) =>
          product.status == 'active' &&
          product.listedPrice > 0 &&
          !excludeIds.contains(product.id),
    );

    final scored = <_ScoredProduct>[];
    for (final product in candidates) {
      scored.add(
        _ScoredProduct(product, score(product)),
      );
    }

    scored.sort((a, b) {
      final byScore = b.score.compareTo(a.score);
      if (byScore != 0) return byScore;
      // Newest first when scores tie.
      return b.product.createdAt.compareTo(a.product.createdAt);
    });

    return scored
        .take(limit < 0 ? 0 : limit)
        .map((entry) => entry.product)
        .toList(growable: false);
  }

  /// 0..1 quality score for a single listing (exported for badges/tooltips).
  static double score(Product product) {
    return _valueWeight * valueScore(product) +
        _trustWeight * trustScore(product) +
        _freshWeight * freshnessScore(product);
  }

  /// How far below the AI fair value the seller is asking (clamped 0..1).
  static double valueScore(Product product) {
    final suggested = product.suggestedPrice;
    if (suggested == null || suggested <= 0) {
      // No AI estimate yet - neutral, decided by trust instead.
      return 0.5;
    }
    // (suggested - listed) / suggested: 0 when asking price == AI value,
    // 0.3 when 30% below, negative when overpriced (clamped to 0).
    final delta = (suggested - product.listedPrice) / suggested;
    if (delta <= 0) {
      // Overpriced: scale the penalty so it can never beat a fair listing.
      return (0.5 + delta).clamp(0.0, 0.5).toDouble();
    }
    return delta.clamp(0.0, 1.0).toDouble();
  }

  /// Seller trust normalised onto the API's 0-5.0 scale.
  static double trustScore(Product product) {
    final score = product.sellerTrustScore ?? 5.0;
    return (score / 5.0).clamp(0.0, 1.0).toDouble();
  }

  /// 1.0 for a brand-new listing, decaying to 0 over ~30 days.
  static double freshnessScore(Product product) {
    final ageDays = DateTime.now().difference(product.createdAt).inDays;
    if (ageDays <= 0) return 1.0;
    if (ageDays >= 30) return 0.0;
    return 1.0 - (ageDays / 30.0);
  }

  /// Human-readable reason shown under a recommended card's badge.
  static String reasonFor(Product product) {
    final value = valueScore(product);
    final trust = trustScore(product);
    if (value >= 0.3) return 'Great AI-value deal';
    if (trust >= 0.9) return 'Top-rated campus seller';
    if (value >= 0.15) return 'Priced below AI fair value';
    return 'Recommended for you';
  }
}

class _ScoredProduct {
  const _ScoredProduct(this.product, this.score);

  final Product product;
  final double score;
}
