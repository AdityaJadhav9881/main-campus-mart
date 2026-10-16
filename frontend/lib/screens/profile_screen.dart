import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../models/product.dart';
import '../providers/auth_provider.dart';
import '../providers/product_provider.dart';
import '../providers/wishlist_provider.dart';
import '../services/api_service.dart';
import '../services/currency.dart';
import '../widgets/app_theme.dart';
import '../widgets/category_icon.dart';
import '../widgets/trust_score_meter.dart';
import 'product_detail_screen.dart';

/// Tab 3 - Profile & Campus Trust.
///
/// Shows the real logged-in student's identity, the live trust score on the
/// API's 0-5.0 scale with a dynamic tier badge, a Log Out action, and a
/// 3-tab activity view wired to live data:
///   * **My Listings** - own active items (from GET /products/) plus items
///     already sold (from GET /transactions/my), each with a Delete action
///     wired to DELETE /products/{id}.
///   * **Purchased** - GET /transactions/my -> `bought`.
///   * **Saved** - wishlist hearts persisted by WishlistProvider.
class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  TransactionHistory? _history;
  bool _historyLoading = false;
  String? _historyError;
  bool _didBootstrap = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_didBootstrap) return;
    _didBootstrap = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _reload();
    });
  }

  Future<void> _reload() async {
    final auth = context.read<AuthProvider>();
    final feed = context.read<ProductProvider>();
    if (auth.token.isEmpty) return;

    setState(() {
      _historyLoading = true;
      _historyError = null;
    });

    // Refresh the feed in parallel with the transaction history.
    final feedFuture = feed.products.isEmpty ? feed.loadProducts() : null;

    try {
      final history = await ApiService.instance.fetchMyTransactions(
        token: auth.token,
      );
      if (!mounted) return;
      setState(() {
        _history = history;
        _historyLoading = false;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _historyError = error.message;
        _historyLoading = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _historyError = 'Could not load activity: $error';
        _historyLoading = false;
      });
    }
    if (feedFuture != null) await feedFuture;
  }

  Future<void> _confirmLogout(BuildContext context, AuthProvider auth) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: AppColors.surface,
        title: const Text(
          'Log out?',
          style: TextStyle(
            color: AppColors.textPrimary,
            fontWeight: FontWeight.w800,
          ),
        ),
        content: const Text(
          'You will need your campus email and password to sign back in.',
          style: TextStyle(color: AppColors.textMuted, fontSize: 13.5),
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
            child: const Text('Log Out'),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      await auth.logout();
    }
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

    try {
      await ApiService.instance.deleteProduct(
        productId: product.id,
        token: auth.token,
      );
      if (!mounted) return;
      context.read<WishlistProvider>().remove(product.id);
      await feed.loadProducts();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
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
      await _reload();
    } on ApiException catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          backgroundColor: AppColors.danger.withOpacity(0.92),
          content: Text(
            error.message,
            style: const TextStyle(color: Colors.black),
          ),
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthProvider>();
    final feed = context.watch<ProductProvider>();
    final wishlist = context.watch<WishlistProvider>();
    final profile = auth.profile;

    final myUid = profile?.id ?? '';
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
    final myListings = <Product>[
      ...activeListings,
      ...soldProducts.values.where(
        (sold) => !activeListings.any((active) => active.id == sold.id),
      ),
    ];

    final purchased = _history?.bought ?? const <TransactionRecord>[];
    final savedProducts = feed.products
        .where((product) => wishlist.contains(product.id))
        .toList();

    return Scaffold(
      appBar: AppBar(
        titleSpacing: 16,
        title: const Text(
          'Profile & Campus Trust',
          style: TextStyle(
            fontFamily: 'Georgia',
            fontSize: 19,
            fontWeight: FontWeight.w700,
            color: AppColors.textPrimary,
          ),
        ),
        actions: [
          IconButton(
            tooltip: 'Log out',
            icon: const Icon(Icons.logout, size: 21, color: AppColors.danger),
            onPressed:
                auth.isLoading ? null : () => _confirmLogout(context, auth),
          ),
          const SizedBox(width: 6),
        ],
      ),
      body: RefreshIndicator(
        color: AppColors.cyanAccent,
        backgroundColor: AppColors.surface,
        onRefresh: () async {
          await auth.refreshProfile();
          await feed.loadProducts();
          await _reload();
        },
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
          children: [
            if (auth.isLoading && profile == null) ...[
              const SizedBox(height: 120),
              const Center(
                child: CircularProgressIndicator(
                  color: AppColors.cyanAccent,
                ),
              ),
            ] else if (profile == null) ...[
              const SizedBox(height: 80),
              const Icon(
                Icons.person_off_outlined,
                size: 44,
                color: AppColors.textMuted,
              ),
              const SizedBox(height: 12),
              Text(
                auth.errorMessage ?? 'Profile unavailable',
                textAlign: TextAlign.center,
                style: const TextStyle(color: AppColors.textMuted),
              ),
              const SizedBox(height: 16),
              Center(
                child: FilledButton.tonal(
                  onPressed: auth.refreshProfile,
                  child: const Text('Retry'),
                ),
              ),
            ] else ...[
              _ProfileHeader(
                name: profile.name,
                email: profile.email,
                memberSince: profile.createdAt,
                status: profile.status,
              ),
              const SizedBox(height: 16),
              _TrustCard(score: profile.trustScore),
              const SizedBox(height: 16),
              _ActivitySection(
                myListings: myListings,
                purchased: purchased,
                savedProducts: savedProducts,
                historyLoading: _historyLoading,
                historyError: _historyError,
                onDeleteListing: _deleteListing,
                onRetryHistory: _reload,
                onOpenProduct: (product) {
                  Navigator.of(context).push(
                    MaterialPageRoute<void>(
                      builder: (_) => ProductDetailScreen(product: product),
                    ),
                  );
                },
              ),
              const SizedBox(height: 20),
              const _HelpAndSupportCard(),
              const SizedBox(height: 20),
              SizedBox(
                width: double.infinity,
                child: OutlinedButton.icon(
                  icon: const Icon(Icons.logout, size: 18),
                  label: const Text('Log Out'),
                  onPressed: () => _confirmLogout(context, auth),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AppColors.danger,
                    side: BorderSide(
                      color: AppColors.danger.withOpacity(0.5),
                    ),
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _ProfileHeader extends StatelessWidget {
  const _ProfileHeader({
    required this.name,
    required this.email,
    required this.memberSince,
    required this.status,
  });

  final String name;
  final String email;
  final DateTime memberSince;
  final String status;

  @override
  Widget build(BuildContext context) {
    final isBlocked = status == 'blocked';
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(
          color: isBlocked ? AppColors.danger : AppColors.hairline,
        ),
      ),
      child: Row(
        children: [
          CircleAvatar(
            radius: 30,
            backgroundColor: AppColors.surfaceHigh,
            child: Text(
              name.trim().isEmpty ? '?' : name.trim()[0].toUpperCase(),
              style: TextStyle(
                color: isBlocked ? AppColors.danger : AppColors.cyanAccent,
                fontSize: 24,
                fontWeight: FontWeight.w800,
              ),
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 17,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  email,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: AppColors.textMuted,
                    fontSize: 13,
                  ),
                ),
                const SizedBox(height: 8),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 8,
                    vertical: 3,
                  ),
                  decoration: BoxDecoration(
                    color: (isBlocked ? AppColors.danger : AppColors.cyanAccent)
                        .withOpacity(0.12),
                    borderRadius: BorderRadius.circular(999),
                    border: Border.all(
                      color: (isBlocked
                              ? AppColors.danger
                              : AppColors.cyanAccent)
                          .withOpacity(0.5),
                    ),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        isBlocked ? Icons.block : Icons.school_outlined,
                        size: 12,
                        color:
                            isBlocked ? AppColors.danger : AppColors.cyanAccent,
                      ),
                      const SizedBox(width: 4),
                      Text(
                        isBlocked ? 'Account Blocked' : 'Campus Student',
                        style: TextStyle(
                          color: isBlocked
                              ? AppColors.danger
                              : AppColors.cyanAccent,
                          fontSize: 10,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  'Member since '
                  '${memberSince.toLocal().toString().split(' ').first}',
                  style: const TextStyle(
                    color: AppColors.textMuted,
                    fontSize: 11.5,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// Trust card: `x.x / 5.0`, a `score / 5.0` progress bar, and a dynamic
/// tier badge (Elite Trusted Student / Verified Student / ...).
class _TrustCard extends StatelessWidget {
  const _TrustCard({required this.score});

  final double score;

  @override
  Widget build(BuildContext context) {
    final tier = trustTierLabel(score);
    final tierColor = trustTierColor(score);

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: AppColors.hairline),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Expanded(
                child: Text(
                  'CAMPUS TRUST SCORE',
                  style: TextStyle(
                    color: AppColors.textMuted,
                    fontSize: 10.5,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 1.1,
                  ),
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 9,
                  vertical: 4,
                ),
                decoration: BoxDecoration(
                  color: tierColor.withOpacity(0.13),
                  borderRadius: BorderRadius.circular(999),
                  border: Border.all(color: tierColor.withOpacity(0.5)),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      score >= 4.5
                          ? Icons.emoji_events_outlined
                          : Icons.verified_outlined,
                      size: 12,
                      color: tierColor,
                    ),
                    const SizedBox(width: 5),
                    Text(
                      tier,
                      style: TextStyle(
                        color: tierColor,
                        fontSize: 10.5,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                score.toStringAsFixed(1),
                style: const TextStyle(
                  color: AppColors.textPrimary,
                  fontSize: 30,
                  fontWeight: FontWeight.w800,
                  height: 1,
                ),
              ),
              const Padding(
                padding: EdgeInsets.only(bottom: 3, left: 6),
                child: Text(
                  '/ 5.0',
                  style: TextStyle(
                    color: AppColors.textMuted,
                    fontSize: 14,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          ClipRRect(
            borderRadius: BorderRadius.circular(999),
            child: LinearProgressIndicator(
              // Spec: (trustScore / 5.0).clamp(0.0, 1.0)
              value: (score / 5.0).clamp(0.0, 1.0).toDouble(),
              minHeight: 8,
              backgroundColor: AppColors.surfaceHigh,
              color: tierColor,
            ),
          ),
          const SizedBox(height: 14),
          const Text(
            'Trust grows with completed sales (+0.1) and admin-approved '
            'listings (+0.2), capped at 5.0. Moderation penalties lower it.',
            style: TextStyle(
              color: AppColors.textMuted,
              fontSize: 12.5,
              height: 1.45,
            ),
          ),
        ],
      ),
    );
  }
}

/// 3-tab activity view: My Listings / Purchased / Saved.
class _ActivitySection extends StatelessWidget {
  const _ActivitySection({
    required this.myListings,
    required this.purchased,
    required this.savedProducts,
    required this.historyLoading,
    required this.historyError,
    required this.onDeleteListing,
    required this.onRetryHistory,
    required this.onOpenProduct,
  });

  final List<Product> myListings;
  final List<TransactionRecord> purchased;
  final List<Product> savedProducts;
  final bool historyLoading;
  final String? historyError;
  final ValueChanged<Product> onDeleteListing;
  final Future<void> Function() onRetryHistory;
  final ValueChanged<Product> onOpenProduct;

  @override
  Widget build(BuildContext context) {
    final hasAnyActivity =
        myListings.isNotEmpty || purchased.isNotEmpty || savedProducts.isNotEmpty;

    return Container(
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: AppColors.hairline),
      ),
      clipBehavior: Clip.antiAlias,
      child: DefaultTabController(
        length: 3,
        child: Column(
          children: [
            const Material(
              color: Colors.transparent,
              child: TabBar(
                labelColor: AppColors.cyanAccent,
                unselectedLabelColor: AppColors.textMuted,
                indicatorColor: AppColors.cyanAccent,
                indicatorWeight: 2.5,
                labelStyle: TextStyle(
                  fontSize: 12.5,
                  fontWeight: FontWeight.w800,
                ),
                unselectedLabelStyle: TextStyle(
                  fontSize: 12.5,
                  fontWeight: FontWeight.w600,
                ),
                tabs: [
                  Tab(text: 'My Listings'),
                  Tab(text: 'Purchased'),
                  Tab(text: 'Saved'),
                ],
              ),
            ),
            if (historyError != null && hasAnyActivity) ...[
              Padding(
                padding: const EdgeInsets.fromLTRB(14, 10, 14, 0),
                child: Row(
                  children: [
                    const Icon(
                      Icons.sync_problem_outlined,
                      size: 14,
                      color: AppColors.warning,
                    ),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        'Purchase history unavailable — pull down to retry.',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          color: AppColors.warning.withOpacity(0.9),
                          fontSize: 11,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
            if (historyLoading && purchased.isEmpty && !hasAnyActivity)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 42),
                child: CircularProgressIndicator(
                  color: AppColors.cyanAccent,
                ),
              )
            else if (historyError != null && !hasAnyActivity)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 24, 16, 24),
                child: Column(
                  children: [
                    Text(
                      historyError!,
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                        color: AppColors.warning,
                        fontSize: 12.5,
                        height: 1.4,
                      ),
                    ),
                    const SizedBox(height: 10),
                    TextButton(
                      onPressed: onRetryHistory,
                      child: const Text(
                        'Retry',
                        style: TextStyle(
                          color: AppColors.cyanAccent,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                  ],
                ),
              )
            else
              SizedBox(
                // 3 tabs x ~240px content each is plenty; the rail itself
                // scrolls vertically inside each tab.
                height: 320,
                child: TabBarView(
                  children: [
                    _MyListingsTab(
                      listings: myListings,
                      onDelete: onDeleteListing,
                      onOpen: onOpenProduct,
                    ),
                    _PurchasedTab(records: purchased),
                    _SavedTab(products: savedProducts, onOpen: onOpenProduct),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// Tab 1 - the student's own listings with a Delete action.
class _MyListingsTab extends StatelessWidget {
  const _MyListingsTab({
    required this.listings,
    required this.onDelete,
    required this.onOpen,
  });

  final List<Product> listings;
  final ValueChanged<Product> onDelete;
  final ValueChanged<Product> onOpen;

  @override
  Widget build(BuildContext context) {
    if (listings.isEmpty) {
      return const _EmptyTab(
        icon: Icons.storefront_outlined,
        message: 'No listings yet. Head to the Sell tab to post your first '
            'item!',
      );
    }

    return ListView.builder(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 16),
      itemCount: listings.length,
      itemBuilder: (context, index) {
        final product = listings[index];
        final isSold = product.status == 'sold';
        return Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: AppColors.surfaceHigh,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: AppColors.hairline),
            ),
            child: Row(
              children: [
                InkWell(
                  borderRadius: BorderRadius.circular(10),
                  onTap: () => onOpen(product),
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
                    onTap: () => onOpen(product),
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
                if (!isSold)
                  IconButton(
                    tooltip: 'Delete listing',
                    icon: const Icon(
                      Icons.delete_outline,
                      size: 20,
                      color: AppColors.danger,
                    ),
                    onPressed: () => onDelete(product),
                  )
                else
                  const Icon(
                    Icons.check_circle_outline,
                    size: 19,
                    color: AppColors.success,
                  ),
              ],
            ),
          ),
        );
      },
    );
  }
}

/// Tab 2 - items bought by the student (GET /transactions/my -> bought).
class _PurchasedTab extends StatelessWidget {
  const _PurchasedTab({required this.records});

  final List<TransactionRecord> records;

  @override
  Widget build(BuildContext context) {
    if (records.isEmpty) {
      return const _EmptyTab(
        icon: Icons.shopping_bag_outlined,
        message: 'Nothing purchased yet. Your buys will appear here.',
      );
    }

    return ListView.builder(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 16),
      itemCount: records.length,
      itemBuilder: (context, index) {
        final record = records[index];
        final title = record.productTitle ?? 'Listing';
        return Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: AppColors.surfaceHigh,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: AppColors.hairline),
            ),
            child: Row(
              children: [
                ClipRRect(
                  borderRadius: BorderRadius.circular(10),
                  child: SizedBox(
                    width: 52,
                    height: 52,
                    child: (record.productImageUrl ?? '').isEmpty
                        ? const ColoredBox(color: AppColors.surface)
                        : Image.network(
                            record.productImageUrl!,
                            fit: BoxFit.cover,
                            errorBuilder: (_, __, ___) => const ColoredBox(
                              color: AppColors.surface,
                              child: Icon(
                                Icons.shopping_bag_outlined,
                                size: 22,
                                color: AppColors.textMuted,
                              ),
                            ),
                          ),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        title,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          color: AppColors.textPrimary,
                          fontSize: 13.5,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        'Paid ${formatInr(record.finalPrice)}'
                        '${record.sellerName == null ? '' : ' · from ${record.sellerName}'}',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          color: AppColors.textMuted,
                          fontSize: 12,
                        ),
                      ),
                      const SizedBox(height: 3),
                      Text(
                        record.timestamp.toLocal().toString().split(' ').first,
                        style: const TextStyle(
                          color: AppColors.textMuted,
                          fontSize: 10.5,
                        ),
                      ),
                    ],
                  ),
                ),
                const Icon(
                  Icons.check_circle,
                  size: 19,
                  color: AppColors.success,
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

/// Tab 3 - wishlist hearts (persisted by WishlistProvider).
class _SavedTab extends StatelessWidget {
  const _SavedTab({required this.products, required this.onOpen});

  final List<Product> products;
  final ValueChanged<Product> onOpen;

  @override
  Widget build(BuildContext context) {
    if (products.isEmpty) {
      return const _EmptyTab(
        icon: Icons.favorite_border,
        message: 'Tap the heart on any listing to save it here for later.',
      );
    }

    return GridView.builder(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 16),
      gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: 2,
        mainAxisSpacing: 10,
        crossAxisSpacing: 10,
        childAspectRatio: 0.78,
      ),
      itemCount: products.length,
      itemBuilder: (context, index) {
        final product = products[index];
        return Material(
          color: AppColors.surfaceHigh,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(14),
            side: const BorderSide(color: AppColors.hairline),
          ),
          clipBehavior: Clip.antiAlias,
          child: InkWell(
            onTap: () => onOpen(product),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Stack(
                    fit: StackFit.expand,
                    children: [
                      product.imageUrl.isEmpty
                          ? ImageFallbackIcon(
                              category: product.category,
                              size: 26,
                            )
                          : Image.network(
                              product.imageUrl,
                              fit: BoxFit.cover,
                              errorBuilder: (_, __, ___) => ImageFallbackIcon(
                                category: product.category,
                                size: 26,
                              ),
                            ),
                      const Positioned(
                        top: 6,
                        right: 6,
                        child: Icon(
                          Icons.favorite,
                          size: 16,
                          color: AppColors.danger,
                        ),
                      ),
                    ],
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(8, 8, 8, 9),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        product.title,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          color: AppColors.textPrimary,
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const SizedBox(height: 3),
                      Text(
                        formatInr(product.listedPrice),
                        style: const TextStyle(
                          color: AppColors.cyanAccent,
                          fontSize: 13,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

/// Shared empty-state used by the three activity tabs.
class _EmptyTab extends StatelessWidget {
  const _EmptyTab({required this.icon, required this.message});

  final IconData icon;
  final String message;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 40),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(icon, size: 36, color: AppColors.textMuted),
          const SizedBox(height: 12),
          Text(
            message,
            textAlign: TextAlign.center,
            style: const TextStyle(
              color: AppColors.textMuted,
              fontSize: 13,
              height: 1.45,
            ),
          ),
        ],
      ),
    );
  }
}

/// Official administration & student help support card.
class _HelpAndSupportCard extends StatelessWidget {
  const _HelpAndSupportCard();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.hairline),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: AppColors.royalBlue.withOpacity(0.1),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: const Icon(
                  Icons.support_agent_outlined,
                  size: 20,
                  color: AppColors.royalBlue,
                ),
              ),
              const SizedBox(width: 12),
              const Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Help & Official Support',
                      style: TextStyle(
                        fontFamily: 'Georgia',
                        color: AppColors.inkBlack,
                        fontSize: 15,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    SizedBox(height: 2),
                    Text(
                      'Direct line to marketplace administration',
                      style: TextStyle(
                        color: AppColors.textMuted,
                        fontSize: 12,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          const Divider(height: 1),
          const SizedBox(height: 12),
          InkWell(
            borderRadius: BorderRadius.circular(10),
            onTap: () {
              Clipboard.setData(
                const ClipboardData(text: 'martaicampus@gmail.com'),
              );
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(
                  content: Text(
                    'Support email copied: martaicampus@gmail.com',
                  ),
                ),
              );
            },
            child: const Padding(
              padding: EdgeInsets.symmetric(vertical: 6, horizontal: 4),
              child: Row(
                children: [
                  Icon(
                    Icons.email_outlined,
                    size: 16,
                    color: AppColors.royalBlue,
                  ),
                  SizedBox(width: 10),
                  Text(
                    'Support Email:',
                    style: TextStyle(
                      color: AppColors.textPrimary,
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      'martaicampus@gmail.com',
                      style: TextStyle(
                        color: AppColors.royalBlue,
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                  Icon(Icons.copy, size: 15, color: AppColors.textMuted),
                ],
              ),
            ),
          ),
          const SizedBox(height: 6),
          InkWell(
            borderRadius: BorderRadius.circular(10),
            onTap: () {
              Clipboard.setData(
                const ClipboardData(text: 'support@campusmart.in'),
              );
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(
                  content: Text(
                    'Support email copied: support@campusmart.in',
                  ),
                ),
              );
            },
            child: const Padding(
              padding: EdgeInsets.symmetric(vertical: 6, horizontal: 4),
              child: Row(
                children: [
                  Icon(
                    Icons.alternate_email,
                    size: 16,
                    color: AppColors.textMuted,
                  ),
                  SizedBox(width: 10),
                  Text(
                    'General Desk:',
                    style: TextStyle(
                      color: AppColors.textPrimary,
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      'support@campusmart.in',
                      style: TextStyle(
                        color: AppColors.textMuted,
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                  Icon(Icons.copy, size: 15, color: AppColors.textMuted),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

