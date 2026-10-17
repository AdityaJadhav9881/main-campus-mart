// Shopping cart models (mirror the FastAPI `CartItemRead` / `CartResponse`
// schemas served by /cart/*).

import 'product.dart';

/// One product parked in the cart with its full listing card.
class CartLine {
  const CartLine({required this.id, required this.addedAt, required this.product});

  factory CartLine.fromJson(Map<String, dynamic> json) {
    return CartLine(
      id: json['id']?.toString() ?? '',
      addedAt: DateTime.tryParse(json['added_at']?.toString() ?? '') ??
          DateTime.now(),
      product: Product.fromJson(
        json['product'] as Map<String, dynamic>? ?? const <String, dynamic>{},
      ),
    );
  }

  final String id;
  final DateTime addedAt;
  final Product product;
}

/// GET /cart/ payload: items + count + ₹ total.
class CartSummary {
  const CartSummary({
    this.items = const <CartLine>[],
    this.count = 0,
    this.totalPrice = 0,
  });

  factory CartSummary.fromJson(Map<String, dynamic> json) {
    return CartSummary(
      items: (json['items'] as List<dynamic>? ?? const <dynamic>[])
          .whereType<Map<String, dynamic>>()
          .map(CartLine.fromJson)
          .toList(growable: false),
      count: (json['count'] as num?)?.toInt() ?? 0,
      totalPrice: (json['total_price'] as num?)?.toDouble() ?? 0,
    );
  }

  final List<CartLine> items;
  final int count;
  final double totalPrice;

  bool get isEmpty => items.isEmpty;
}
