import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/product.dart';
import '../providers/auth_provider.dart';
import '../providers/product_provider.dart';
import '../providers/wishlist_provider.dart';
import '../services/api_service.dart';
import '../services/currency.dart';
import '../widgets/app_theme.dart';
import '../widgets/category_icon.dart';
import 'product_detail_screen.dart';

/// My Listings (Part B Task 7): the student's own active posts (from
/// GET /products/) plus sold items (from GET /transactions/my -> sold), each
/// with a Delete action wired to DELETE /products/{id}.
class MyListingsScreen extends StatefulWidget {
  const MyListingsScreen({super.key});

  @override
  State<MyListingsScreen> createState() => _MyListingsScreenState();
}

class _MyListingsScreenState extends State<MyListingsScreen> {
  TransactionHistory? _history;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _reload();
    });
  }

  Future<void> _reload() async {
    final auth = context.read<AuthProvider>();
    final feed = context.read<ProductProvider>();
    if (auth.token.isEmpty) return;

    setState(() => _loading = _history == null);
    final feedFuture = feed.products.isEmpty ? feed.loadProducts() : null;
    try {
      final history = await ApiService.instance.fetchMyTransactions(
        token: auth.token,
      );
      if (!mounted) return;
      setState(() {
        _history = history;
        _loading = false;
        _error = null;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _error = error.message;
        _loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _error = 'Could not load your listings right now.';
        _loading = false;
      });
    }
    if (feedFuture != null) await feedFuture;
  }

  Future<void> _deleteListing(Product product) async {
    final auth = context.read<AuthProvider>();
    final feed = context.read<ProductProvider>();
    if (!mounted) return;

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: AppColors.surface,
        title: const Text(
          'Delete this listing?',
          style: TextStyle(
            color: AppColors.textPrimary,
            fontWeight: FontWeight.w800,
          ),
        ),
        content: Text(
          '"${product.title}" will be removed from the marketplace. '
          'This cannot be undone.',
          style: const TextStyle(color: AppColors.textMuted, fontSize: 13.5),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text(
              'Cancel',
              style: TextStyle(color: AppColors.textMuted),
            ),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            style: FilledButton.styleFrom(backgroundColor: AppColors.danger),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    final messenger = ScaffoldMessenger.of(context);
    try {
      await ApiService.instance.deleteProduct(
        productId: product.id,
        token: auth.token,
      );
      if (!mounted) return;
      context.read<WishlistProvider>().remove(product.id);
      await feed.loadProducts();
      if (!mounted) return;
      messenger.showSnackBar(
        SnackBar(
          backgroundColor: AppColors.success.withOpacity(0.92),
          content: Text(
            '"${product.title}" deleted',
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
    } catch (_) {
      if (!mounted) return;
      messenger.showSnackBar(
        const SnackBar(content: Text('Could not delete that listing.')),
      );
    }
  }

  void _openProduct(Product product) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => ProductDetailScreen(product: product),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final myUid = context.select<AuthProvider, String>(
      (auth) => auth.profile?.id ?? '',
    );
    final feed = context.watch<ProductProvider>();

    final activeListings =
        feed.products.where((p) => p.sellerId == myUid).toList();

    // Sold items come from the transaction history (never in the feed).
    final soldProducts = <String, Product>{};
    for (final tx in _history?.sold ?? const <TransactionRecord>[]) {
      if (tx.productTitle == null) continue;
      soldProducts[tx.productId] = Product(
        id: tx.productId,
        sellerId: myUid,
        title: tx.productTitle!,
        createdAt: tx.timestamp,
        imageUrl: tx.productImageUrl ?? '',
        listedPrice: tx.finalPrice,
        status: tx.productStatus ?? 'sold',
      );
    }
    final sold = soldProducts.values
        .where((s) => !activeListings.any((a) => a.id == s.id))
        .toList();

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        titleSpacing: 16,
        title: const Text(
          'My Listings',
          style: TextStyle(
            fontFamily: 'Georgia',
            fontSize: 20,
            fontWeight: FontWeight.w700,
            color: AppColors.inkBlack,
          ),
        ),
      ),
      body: _buildBody(activeListings, sold),
    );
  }

  Widget _buildBody(List<Product> active, List<Product> sold) {
    if (_loading && active.isEmpty && sold.isEmpty) {
      return const Center(
        child: CircularProgressIndicator(color: AppColors.royalBlue),
      );
    }
    if (_error != null && active.isEmpty && sold.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(28),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.storefront_outlined,
                  size: 42, color: AppColors.textMuted),
              const SizedBox(height: 12),
              Text(
                _error!,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  color: AppColors.textMuted,
                  fontSize: 13,
                  height: 1.45,
                ),
              ),
              const SizedBox(height: 12),
              FilledButton.tonal(
                onPressed: _reload,
                child: const Text('Retry'),
              ),
            ],
          ),
        ),
      );
    }
    if (active.isEmpty && sold.isEmpty) {
      return ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        children: const [
          SizedBox(height: 110),
          Icon(Icons.storefront_outlined,
              size: 42, color: AppColors.textMuted),
          SizedBox(height: 12),
          Text(
            'No listings yet.\nHead to the Sell tab to post your first item!',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: AppColors.textMuted,
              fontSize: 13,
              height: 1.5,
            ),
          ),
        ],
      );
    }

    return RefreshIndicator(
      color: AppColors.royalBlue,
      backgroundColor: AppColors.surface,
      onRefresh: _reload,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 28),
        children: [
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Text(
                'Could not refresh order history — pull down to retry.',
                style: TextStyle(
                  color: AppColors.warning.withOpacity(0.9),
                  fontSize: 11.5,
                ),
              ),
            ),
          if (active.isNotEmpty) ...[
            _SectionHeader(label: 'ACTIVE (${active.length})'),
            for (final product in active)
              Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: _ListingRow(
                  product: product,
                  onOpen: () => _openProduct(product),
                  onDelete: () => _deleteListing(product),
                ),
              ),
          ],
          if (sold.isNotEmpty) ...[
            const SizedBox(height: 8),
            _SectionHeader(label: 'SOLD (${sold.length})'),
            for (final product in sold)
              Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: _ListingRow(
                  product: product,
                  onOpen: () => _openProduct(product),
                ),
              ),
          ],
        ],
      ),
    );
  }
}

class _SectionHeader extends StatelessWidget {
  const _SectionHeader({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Text(
        label,
        style: const TextStyle(
          color: AppColors.textMuted,
          fontSize: 10.5,
          fontWeight: FontWeight.w800,
          letterSpacing: 1.1,
        ),
      ),
    );
  }
}

/// One listing row with image, title, price and optional Delete action.
class _ListingRow extends StatelessWidget {
  const _ListingRow({
    required this.product,
    required this.onOpen,
    this.onDelete,
  });

  final Product product;
  final VoidCallback onOpen;
  final VoidCallback? onDelete;

  @override
  Widget build(BuildContext context) {
    final isSold = product.status == 'sold';
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.hairline),
      ),
      child: Row(
        children: [
          InkWell(
            borderRadius: BorderRadius.circular(10),
            onTap: onOpen,
            child: ClipRRect(
              borderRadius: BorderRadius.circular(10),
              child: SizedBox(
                width: 52,
                height: 52,
                child: product.imageUrl.isEmpty
                    ? ImageFallbackIcon(
                        category: product.category,
                        size: 24,
                      )
                    : Image.network(
                        product.imageUrl,
                        fit: BoxFit.cover,
                        errorBuilder: (_, __, ___) => ImageFallbackIcon(
                          category: product.category,
                          size: 24,
                        ),
                      ),
              ),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: InkWell(
              onTap: onOpen,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    product.title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: AppColors.textPrimary,
                      fontSize: 13.5,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Row(
                    children: [
                      Text(
                        '${formatInr(product.listedPrice)}'
                        ' · ${product.condition}',
                        style: const TextStyle(
                          color: AppColors.textMuted,
                          fontSize: 12,
                        ),
                      ),
                      if (isSold) ...[
                        const SizedBox(width: 6),
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 6,
                            vertical: 2,
                          ),
                          decoration: BoxDecoration(
                            color: AppColors.warning.withOpacity(0.15),
                            borderRadius: BorderRadius.circular(5),
                          ),
                          child: const Text(
                            'SOLD',
                            style: TextStyle(
                              color: AppColors.warning,
                              fontSize: 9,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                        ),
                      ],
                    ],
                  ),
                ],
              ),
            ),
          ),
          if (onDelete != null)
            IconButton(
              tooltip: 'Delete listing',
              icon: const Icon(
                Icons.delete_outline,
                size: 20,
                color: AppColors.danger,
              ),
              onPressed: onDelete,
            )
          else
            const Padding(
              padding: EdgeInsets.only(right: 10),
              child: Icon(
                Icons.check_circle_outline,
                size: 19,
                color: AppColors.success,
              ),
            ),
        ],
      ),
    );
  }
}
