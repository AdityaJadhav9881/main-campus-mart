import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/cart_models.dart';
import '../providers/cart_provider.dart';
import '../services/currency.dart';
import '../widgets/app_theme.dart';
import 'checkout_sheet.dart';
import 'product_detail_screen.dart';

/// Shopping cart (Part B Task 7): items parked from product detail, each
/// checkoutable through the 4-step sheet. Checkout clears that line
/// server-side (the purchase endpoint empties the cart).
class CartScreen extends StatefulWidget {
  const CartScreen({super.key});

  @override
  State<CartScreen> createState() => _CartScreenState();
}

class _CartScreenState extends State<CartScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) context.read<CartProvider>().load();
    });
  }

  Future<void> _buyNow(CartLine line) async {
    final cart = context.read<CartProvider>();
    final result = await showCheckoutSheet(context, product: line.product);
    if (result == null || !mounted) return;
    // The server empties this product from the cart on purchase; mirror it.
    cart.removeLocal(line.product.id);
  }

  Future<void> _remove(CartLine line) async {
    final cart = context.read<CartProvider>();
    final ok = await cart.remove(line.product.id);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          ok
              ? '"${line.product.title}" removed from your cart.'
              : (cart.errorMessage ?? 'Could not remove that item.'),
        ),
        duration: const Duration(seconds: 2),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final cart = context.watch<CartProvider>();

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        titleSpacing: 16,
        title: Text(
          cart.count == 0 ? 'My Cart' : 'My Cart (${cart.count})',
          style: const TextStyle(
            fontFamily: 'Georgia',
            fontSize: 20,
            fontWeight: FontWeight.w700,
            color: AppColors.inkBlack,
          ),
        ),
      ),
      body: cart.items.isEmpty && !cart.isLoading
          ? _buildEmpty()
          : RefreshIndicator(
              color: AppColors.royalBlue,
              backgroundColor: AppColors.surface,
              onRefresh: cart.load,
              child: cart.items.isEmpty
                  ? ListView(children: const [SizedBox(height: 200)])
                  : ListView.separated(
                      physics: const AlwaysScrollableScrollPhysics(),
                      padding: const EdgeInsets.fromLTRB(16, 12, 16, 120),
                      itemCount: cart.items.length,
                      separatorBuilder: (_, __) => const SizedBox(height: 10),
                      itemBuilder: (context, index) {
                        final line = cart.items[index];
                        return _CartLineTile(
                          line: line,
                          onOpen: () {
                            Navigator.of(context).push(
                              MaterialPageRoute<void>(
                                builder: (_) =>
                                    ProductDetailScreen(product: line.product),
                              ),
                            );
                          },
                          onRemove: () => _remove(line),
                          onBuy: () => _buyNow(line),
                        );
                      },
                    ),
            ),
      bottomNavigationBar: cart.items.isEmpty
          ? null
          : SafeArea(
              child: Container(
                padding: const EdgeInsets.fromLTRB(20, 12, 20, 14),
                decoration: const BoxDecoration(
                  color: AppColors.surface,
                  border: Border(top: BorderSide(color: AppColors.hairline)),
                ),
                child: Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const Text(
                            'CART TOTAL',
                            style: TextStyle(
                              color: AppColors.textMuted,
                              fontSize: 10,
                              fontWeight: FontWeight.w800,
                              letterSpacing: 1.1,
                            ),
                          ),
                          const SizedBox(height: 3),
                          Text(
                            formatInr(cart.totalPrice),
                            style: const TextStyle(
                              color: AppColors.inkBlack,
                              fontSize: 19,
                              fontWeight: FontWeight.w900,
                            ),
                          ),
                        ],
                      ),
                    ),
                    const Text(
                      'Each item checks out\nwith OTP verification',
                      textAlign: TextAlign.right,
                      style: TextStyle(
                        color: AppColors.textMuted,
                        fontSize: 10.5,
                        height: 1.4,
                      ),
                    ),
                  ],
                ),
              ),
            ),
    );
  }

  Widget _buildEmpty() {
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      children: const [
        SizedBox(height: 120),
        Icon(Icons.shopping_cart_outlined,
            size: 46, color: AppColors.textMuted),
        SizedBox(height: 14),
        Text(
          'Your cart is empty',
          textAlign: TextAlign.center,
          style: TextStyle(
            color: AppColors.textPrimary,
            fontSize: 16,
            fontWeight: FontWeight.w700,
          ),
        ),
        SizedBox(height: 8),
        Text(
          'Tap "Add to Cart" on any listing to park it here\nbefore you check out.',
          textAlign: TextAlign.center,
          style: TextStyle(
            color: AppColors.textMuted,
            fontSize: 12.5,
            height: 1.5,
          ),
        ),
      ],
    );
  }
}

/// One cart row: thumb, title, price, condition chip + Buy/Remove actions.
class _CartLineTile extends StatelessWidget {
  const _CartLineTile({
    required this.line,
    required this.onOpen,
    required this.onRemove,
    required this.onBuy,
  });

  final CartLine line;
  final VoidCallback onOpen;
  final VoidCallback onRemove;
  final VoidCallback onBuy;

  @override
  Widget build(BuildContext context) {
    final product = line.product;
    return Material(
      color: AppColors.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: const BorderSide(color: AppColors.hairline),
      ),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onOpen,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  ClipRRect(
                    borderRadius: BorderRadius.circular(11),
                    child: SizedBox(
                      width: 62,
                      height: 62,
                      child: product.imageUrl.isEmpty
                          ? const ColoredBox(color: AppColors.surfaceHigh)
                          : Image.network(
                              product.imageUrl,
                              fit: BoxFit.cover,
                              errorBuilder: (context, error, stack) =>
                                  const ColoredBox(
                                      color: AppColors.surfaceHigh),
                            ),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          product.title,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            color: AppColors.textPrimary,
                            fontSize: 13,
                            fontWeight: FontWeight.w700,
                            height: 1.25,
                          ),
                        ),
                        const SizedBox(height: 5),
                        Text(
                          '${product.condition} · ${product.category}',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            color: AppColors.textMuted,
                            fontSize: 11,
                          ),
                        ),
                      ],
                    ),
                  ),
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      Text(
                        formatInr(product.listedPrice),
                        style: const TextStyle(
                          color: AppColors.inkBlack,
                          fontSize: 15,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                      const SizedBox(height: 4),
                      InkWell(
                        customBorder: const CircleBorder(),
                        onTap: onRemove,
                        child: const Padding(
                          padding: EdgeInsets.all(4),
                          child: Icon(
                            Icons.delete_outline,
                            size: 18,
                            color: AppColors.textMuted,
                          ),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
              const SizedBox(height: 10),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: onRemove,
                      icon: const Icon(Icons.remove_shopping_cart_outlined,
                          size: 15),
                      label: const Text('Remove'),
                      style: OutlinedButton.styleFrom(
                        foregroundColor: AppColors.textMuted,
                        minimumSize: const Size.fromHeight(38),
                        side: const BorderSide(color: AppColors.hairline),
                        textStyle: const TextStyle(
                            fontSize: 12, fontWeight: FontWeight.w700),
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: FilledButton.icon(
                      onPressed: onBuy,
                      icon: const Icon(Icons.bolt, size: 16),
                      label: const Text('Buy Now'),
                      style: FilledButton.styleFrom(
                        minimumSize: const Size.fromHeight(38),
                        textStyle: const TextStyle(
                            fontSize: 12, fontWeight: FontWeight.w800),
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
