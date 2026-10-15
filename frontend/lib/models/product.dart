/// Data model for a marketplace listing as returned by the FastAPI backend
/// (`ProductRead` schema).
///
/// Parsing is deliberately defensive: every field tolerates missing/malformed
/// JSON via null-safety defaults, so a single bad payload can never crash the
/// feed UI.
class Product {
  const Product({
    required this.id,
    required this.sellerId,
    required this.title,
    required this.createdAt,
    this.description = '',
    this.category = 'Uncategorized',
    this.condition = 'Unknown',
    this.imageUrl = '',
    this.suggestedPrice,
    this.listedPrice = 0,
    this.status = 'active',
    this.trustReason,
    this.sellerTrustScore,
  });

  /// Builds a [Product] from the snake_case JSON produced by FastAPI.
  factory Product.fromJson(Map<String, dynamic> json) {
    return Product(
      id: json['id']?.toString() ?? '',
      sellerId: json['seller_id']?.toString() ?? '',
      title: json['title']?.toString() ?? 'Untitled listing',
      createdAt: DateTime.tryParse(json['created_at']?.toString() ?? '') ??
          DateTime.now(),
      description: json['description']?.toString() ?? '',
      category: json['category']?.toString() ?? 'Uncategorized',
      condition: json['condition']?.toString() ?? 'Unknown',
      imageUrl: json['image_url']?.toString() ?? '',
      suggestedPrice: _toDouble(json['suggested_price']),
      listedPrice: _toDouble(json['listed_price']) ?? 0,
      status: json['status']?.toString() ?? 'active',
      trustReason: json['trust_reason']?.toString(),
      sellerTrustScore: _toDouble(json['seller_trust_score']),
    );
  }

  final String id;
  final String sellerId;
  final String title;
  final String description;
  final String category;
  final String condition;
  final String imageUrl;

  /// AI fair-value estimate produced by the LangGraph pipeline.
  /// Null until the price agent has processed the listing.
  final double? suggestedPrice;

  final double listedPrice;

  /// Lifecycle state: 'active' | 'sold' | 'flagged'.
  final String status;

  /// Trust & Fraud Agent's justification when flagged (admin moderation).
  final String? trustReason;

  final DateTime createdAt;

  /// Seller's trust score (0-10, neutral default 5.0) as of read time.
  final double? sellerTrustScore;

  /// Serializes back to the API's snake_case contract.
  Map<String, dynamic> toJson() => <String, dynamic>{
        'id': id,
        'seller_id': sellerId,
        'title': title,
        'description': description,
        'category': category,
        'condition': condition,
        'image_url': imageUrl,
        'suggested_price': suggestedPrice,
        'listed_price': listedPrice,
        'status': status,
        'trust_reason': trustReason,
        'created_at': createdAt.toIso8601String(),
        'seller_trust_score': sellerTrustScore,
      };

  /// Accepts num (int/double from JSON), numeric String, or null when reading
  /// price-like fields - keeps the model robust across server changes.
  static double? _toDouble(dynamic value) {
    if (value == null) return null;
    if (value is num) return value.toDouble();
    return double.tryParse(value.toString());
  }
}
