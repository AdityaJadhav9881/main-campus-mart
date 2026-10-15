import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/product.dart';
import '../providers/product_provider.dart';
import '../widgets/app_theme.dart';
import '../widgets/product_card.dart';
import 'product_detail_screen.dart';

/// Tab 1 - Discovery Feed.
///
/// Campus branding + search bar in the app bar, category filter chips below,
/// then a pull-to-refresh 2-column grid of active listings.
class FeedScreen extends StatefulWidget {
  const FeedScreen({super.key});

  @override
  State<FeedScreen> createState() => _FeedScreenState();
}

class _FeedScreenState extends State<FeedScreen> {
  /// Categories are client-side filters over the AI-assigned (or seeded)
  /// `category` field. "Lab Gear & Instruments" currently only matches
  /// seeded listings and shows the empty state until more AI categories land.
  static const List<String> _categories = <String>[
    'All',
    'Academic Material',
    'Lab Gear & Instruments',
    'Electronics',
  ];

  final TextEditingController _searchController = TextEditingController();
  String _query = '';
  String _category = 'All';

  @override
  void initState() {
    super.initState();
    // First load (skipped when data already exists, e.g. tab switches).
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final provider = context.read<ProductProvider>();
      if (provider.products.isEmpty && !provider.isLoading) {
        provider.loadProducts();
      }
    });
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  /// Applies the active category chip + search query to the provider list.
  List<Product> _applyFilters(List<Product> all) {
    final query = _query.trim().toLowerCase();
    return all.where((product) {
      final matchesCategory = _category == 'All' || product.category == _category;
      final matchesQuery = query.isEmpty ||
          product.title.toLowerCase().contains(query) ||
          product.description.toLowerCase().contains(query);
      return matchesCategory && matchesQuery;
    }).toList();
  }

  void _openDetail(Product product) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => ProductDetailScreen(product: product),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<ProductProvider>();
    final visible = _applyFilters(provider.products);

    return Scaffold(
      appBar: AppBar(
        titleSpacing: 16,
        title: const Row(
          children: [
            Icon(
              Icons.school_outlined,
              color: AppColors.cyanAccent,
              size: 26,
            ),
            SizedBox(width: 10),
            Text.rich(
              TextSpan(
                children: [
                  TextSpan(
                    text: 'Campus',
                    style: TextStyle(
                      color: AppColors.textPrimary,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  TextSpan(
                    text: 'Mart AI',
                    style: TextStyle(
                      color: AppColors.cyanAccent,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(64),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
            child: TextField(
              controller: _searchController,
              onChanged: (value) => setState(() => _query = value),
              style: const TextStyle(color: AppColors.textPrimary),
              decoration: InputDecoration(
                hintText: 'Search campus listings...',
                prefixIcon: const Icon(
                  Icons.search,
                  color: AppColors.textMuted,
                  size: 20,
                ),
                suffixIcon: _query.isEmpty
                    ? null
                    : IconButton(
                        icon: const Icon(
                          Icons.clear,
                          color: AppColors.textMuted,
                          size: 18,
                        ),
                        onPressed: () {
                          _searchController.clear();
                          setState(() => _query = '');
                        },
                      ),
              ),
            ),
          ),
        ),
      ),
      body: Column(
        children: [
          _buildCategoryChips(),
          Expanded(child: _buildBody(provider, visible)),
        ],
      ),
    );
  }

  /// Horizontal scrollable row of category filter chips.
  Widget _buildCategoryChips() {
    return SizedBox(
      height: 56,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
        itemCount: _categories.length,
        separatorBuilder: (context, index) => const SizedBox(width: 8),
        itemBuilder: (context, index) {
          final category = _categories[index];
          final selected = category == _category;
          return ChoiceChip(
            label: Text(category),
            selected: selected,
            showCheckmark: false,
            visualDensity: VisualDensity.compact,
            onSelected: (_) => setState(() => _category = category),
            selectedColor: AppColors.cyanAccent,
            backgroundColor: AppColors.surface,
            side: const BorderSide(color: AppColors.hairline),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(999),
            ),
            labelStyle: TextStyle(
              color: selected ? Colors.black : AppColors.textMuted,
              fontSize: 12,
              fontWeight: FontWeight.w700,
            ),
          );
        },
      ),
    );
  }

  /// Chooses between the initial loader, the error view, and the
  /// pull-to-refresh grid / empty states.
  Widget _buildBody(ProductProvider provider, List<Product> visible) {
    // Full-screen loader/error only appears before anything has loaded;
    // once data exists, refreshes keep the grid visible (pull-to-refresh).
    final showLoader = provider.isLoading && provider.products.isEmpty;
    final showError = provider.errorMessage != null &&
        provider.products.isEmpty &&
        !provider.isLoading;

    if (showLoader) {
      return const Center(
        child: CircularProgressIndicator(color: AppColors.cyanAccent),
      );
    }
    if (showError) {
      return _FeedMessage(
        icon: Icons.cloud_off_outlined,
        title: 'Could not reach the marketplace',
        message: provider.errorMessage ?? 'Unknown error',
        actionLabel: 'Retry',
        onAction: provider.loadProducts,
      );
    }

    final noMatches = visible.isEmpty;
    final filtersActive = _category != 'All' || _query.isNotEmpty;

    return RefreshIndicator(
      color: AppColors.cyanAccent,
      backgroundColor: AppColors.surface,
      onRefresh: provider.loadProducts,
      child: noMatches
          ? _FeedMessage(
              icon: Icons.search_off_outlined,
              title: filtersActive ? 'No listings match your filters' : 'No listings here yet',
              message: filtersActive
                  ? 'Nothing matches "$_category"$_queryHint right now. '
                      'Refresh to check for new campus listings.'
                  : 'Pull down to refresh, or sell the first item!',
              actionLabel: 'Refresh Feed',
              onAction: provider.loadProducts,
              secondaryLabel: 'Clear filters',
              onSecondaryAction: () {
                _searchController.clear();
                setState(() {
                  _query = '';
                  _category = 'All';
                });
              },
            )
          : GridView.builder(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
              gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                crossAxisCount: 2,
                mainAxisSpacing: 12,
                crossAxisSpacing: 12,
                childAspectRatio: 0.64,
              ),
              itemCount: visible.length,
              itemBuilder: (context, index) {
                final product = visible[index];
                return ProductCard(
                  product: product,
                  onTap: () => _openDetail(product),
                );
              },
            ),
    );
  }

  String get _queryHint => _query.isEmpty ? '' : ' "$_query"';
}

/// Scrollable empty/error content that still allows pull-to-refresh
/// (requires a scrollable child with AlwaysScrollableScrollPhysics).
class _FeedMessage extends StatelessWidget {
  const _FeedMessage({
    required this.icon,
    required this.title,
    required this.message,
    required this.actionLabel,
    required this.onAction,
    this.secondaryLabel,
    this.onSecondaryAction,
  });

  final IconData icon;
  final String title;
  final String message;
  final String actionLabel;
  final VoidCallback onAction;

  /// Optional second action (e.g. "Clear filters" alongside "Refresh Feed").
  final String? secondaryLabel;
  final VoidCallback? onSecondaryAction;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        return ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          children: [
            SizedBox(height: (constraints.maxHeight - 220) / 2),
            Icon(icon, size: 44, color: AppColors.textMuted),
            const SizedBox(height: 14),
            Text(
              title,
              textAlign: TextAlign.center,
              style: const TextStyle(
                color: AppColors.textPrimary,
                fontSize: 16,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: 8),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 40),
              child: Text(
                message,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  color: AppColors.textMuted,
                  fontSize: 13,
                  height: 1.4,
                ),
              ),
            ),
            const SizedBox(height: 18),
            Center(
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  TextButton(
                    onPressed: onAction,
                    child: Text(
                      actionLabel,
                      style: const TextStyle(
                        color: AppColors.cyanAccent,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                  if (secondaryLabel != null && onSecondaryAction != null)
                    TextButton(
                      onPressed: onSecondaryAction,
                      child: Text(
                        secondaryLabel!,
                        style: const TextStyle(
                          color: AppColors.textMuted,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                ],
              ),
            ),
          ],
        );
      },
    );
  }
}
