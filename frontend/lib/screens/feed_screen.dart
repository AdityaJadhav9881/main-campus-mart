import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/product.dart';
import '../providers/product_provider.dart';
import '../services/currency.dart';
import '../services/recommendations.dart';
import '../widgets/app_theme.dart';
import '../widgets/product_card.dart';
import 'product_detail_screen.dart';

/// Tab 1 - Discover (the complete marketplace home).
///
/// Top to bottom:
///   1. Branding AppBar (custom logo + `Campus Mart Ai`) with search field.
///   2. ✨ AI Recommended For You - a horizontal rail ranked by the
///      Recommendation Engine (value vs AI fair price + seller trust).
///   3. Category chips built from the categories ACTUALLY present in the feed,
///      plus a Sort bottom-sheet (Newest / Price / AI Value / Trust).
///   4. Pull-to-refresh 2-column grid of upgraded product cards.
class FeedScreen extends StatefulWidget {
  const FeedScreen({super.key});

  @override
  State<FeedScreen> createState() => _FeedScreenState();
}

/// Sort options offered in the Sort sheet (label -> id).
class _SortOption {
  const _SortOption(this.id, this.label, this.icon);

  final String id;
  final String label;
  final IconData icon;
}

const List<_SortOption> _sortOptions = <_SortOption>[
  _SortOption('newest', 'Newest', Icons.schedule_outlined),
  _SortOption('price_asc', 'Price: Low to High', Icons.arrow_upward),
  _SortOption('price_desc', 'Price: High to Low', Icons.arrow_downward),
  _SortOption('ai_value', 'Best AI Value', Icons.auto_awesome),
  _SortOption('trust', 'Highest Trust', Icons.shield_outlined),
];

/// Preferred display order for the marketplace's known categories; anything
/// else discovered in the feed is appended alphabetically.
const List<String> _knownCategories = <String>[
  'Electronics',
  'Academic Material',
  'Lab Gear & Instruments',
  'Other',
];

class _FeedScreenState extends State<FeedScreen> {
  final TextEditingController _searchController = TextEditingController();
  String _query = '';
  String _category = 'All';
  String _sort = 'newest';

  /// Debounce for the server-side `?q=` search (fires after typing pauses).
  Timer? _searchDebounce;

  /// Render-free warmup timer: if the very first load is still empty after
  /// 3s, swap the plain spinner for the "waking up our cloud AI server" card.
  Timer? _warmupTimer;
  bool _warmupVisible = false;

  @override
  void initState() {
    super.initState();
    // First load (skipped when data already exists, e.g. tab switches).
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final provider = context.read<ProductProvider>();
      if (provider.products.isEmpty && !provider.isLoading) {
        _scheduleWarmup();
        provider.loadProducts();
      }
    });
  }

  @override
  void dispose() {
    _searchDebounce?.cancel();
    _warmupTimer?.cancel();
    _searchController.dispose();
    super.dispose();
  }

  /// Starts the 3s warmup countdown for a cold feed request.
  void _scheduleWarmup() {
    _warmupTimer?.cancel();
    _warmupTimer = Timer(const Duration(seconds: 3), () {
      if (!mounted) return;
      final provider = context.read<ProductProvider>();
      if (provider.isLoading && provider.products.isEmpty) {
        setState(() => _warmupVisible = true);
      }
    });
  }

  /// Debounced server-side search: replaces the feed with matching listings
  /// (server `?q=` also matches AI tags + category, beyond the local filter).
  void _onSearchChanged(String value) {
    setState(() => _query = value);
    _searchDebounce?.cancel();
    _searchDebounce = Timer(const Duration(milliseconds: 400), () {
      if (!mounted) return;
      context.read<ProductProvider>().loadProducts(query: value);
    });
  }

  /// Categories for the chip row: `All` + every category actually present in
  /// the feed (known ones first, then any AI-assigned extras).
  List<String> _categoriesFor(List<Product> all) {
    final present = all
        .map((product) => product.category)
        .where((category) => category.trim().isNotEmpty)
        .toSet();

    final chips = <String>['All'];
    for (final known in _knownCategories) {
      if (present.contains(known)) chips.add(known);
    }
    final extras = present.where((c) => !_knownCategories.contains(c)).toList()
      ..sort();
    chips.addAll(extras);
    return chips;
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

  List<Product> _applySort(List<Product> items) {
    final sorted = List<Product>.from(items);
    switch (_sort) {
      case 'price_asc':
        sorted.sort((a, b) => a.listedPrice.compareTo(b.listedPrice));
      case 'price_desc':
        sorted.sort((a, b) => b.listedPrice.compareTo(a.listedPrice));
      case 'ai_value':
        sorted.sort(
          (a, b) => RecommendationEngine.valueScore(b)
              .compareTo(RecommendationEngine.valueScore(a)),
        );
      case 'trust':
        sorted.sort(
          (a, b) => (b.sellerTrustScore ?? 0).compareTo(a.sellerTrustScore ?? 0),
        );
      case 'newest':
      default:
        sorted.sort((a, b) => b.createdAt.compareTo(a.createdAt));
    }
    return sorted;
  }

  void _openDetail(Product product) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => ProductDetailScreen(product: product),
      ),
    );
  }

  Future<void> _openSortSheet() async {
    final selected = await showModalBottomSheet<String>(
      context: context,
      backgroundColor: AppColors.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (sheetContext) {
        return SafeArea(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Padding(
                padding: EdgeInsets.fromLTRB(20, 18, 20, 6),
                child: Text(
                  'SORT LISTINGS',
                  style: TextStyle(
                    color: AppColors.textMuted,
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 1.2,
                  ),
                ),
              ),
              for (final option in _sortOptions)
                ListTile(
                  dense: true,
                  leading: Icon(
                    option.icon,
                    size: 19,
                    color: option.id == _sort
                        ? AppColors.royalBlue
                        : AppColors.textMuted,
                  ),
                  title: Text(
                    option.label,
                    style: TextStyle(
                      color: option.id == _sort
                          ? AppColors.royalBlue
                          : AppColors.textPrimary,
                      fontSize: 14.5,
                      fontWeight: option.id == _sort
                          ? FontWeight.w700
                          : FontWeight.w500,
                    ),
                  ),
                  trailing: option.id == _sort
                      ? const Icon(Icons.check, size: 18, color: AppColors.royalBlue)
                      : null,
                  onTap: () => Navigator.of(sheetContext).pop(option.id),
                ),
              const SizedBox(height: 8),
            ],
          ),
        );
      },
    );
    if (selected != null && mounted) setState(() => _sort = selected);
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<ProductProvider>();
    final visible = _applySort(_applyFilters(provider.products));
    final categories = _categoriesFor(provider.products);

    // The rail is a browsing aid - hide it once the user starts narrowing.
    final showRecommendations =
        _category == 'All' && _query.trim().isEmpty && provider.products.length > 2;

    return Scaffold(
      appBar: AppBar(
        titleSpacing: 16,
        title: const Row(
          children: [
            ClipRRect(
              borderRadius: BorderRadius.all(Radius.circular(8)),
              child: Image(
                image: AssetImage('assets/logo.png'),
                width: 30,
                height: 30,
                fit: BoxFit.cover,
              ),
            ),
            SizedBox(width: 10),
            Text.rich(
              TextSpan(
                style: TextStyle(
                  fontFamily: 'Georgia',
                  fontSize: 22,
                  fontWeight: FontWeight.w700,
                  letterSpacing: -0.3,
                ),
                children: [
                  TextSpan(
                    text: 'Campus Mart',
                    style: TextStyle(
                      color: AppColors.inkBlack,
                    ),
                  ),
                  TextSpan(
                    text: ' Ai',
                    style: TextStyle(
                      color: AppColors.royalBlue,
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
              onChanged: _onSearchChanged,
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
                          _searchDebounce?.cancel();
                          _searchController.clear();
                          setState(() => _query = '');
                          context.read<ProductProvider>().loadProducts(query: '');
                        },
                      ),
              ),
            ),
          ),
        ),
      ),
      body: Column(
        children: [
          if (showRecommendations) ...[
            _AiRecommendationRail(
              products: provider.products,
              onOpen: _openDetail,
            ),
          ],
          _buildFilterRow(categories),
          Expanded(child: _buildBody(provider, visible)),
        ],
      ),
    );
  }

  /// Category chips (dynamic) + a Sort button that opens the sort sheet.
  Widget _buildFilterRow(List<String> categories) {
    final sortLabel =
        _sortOptions.firstWhere((option) => option.id == _sort).label;
    return SizedBox(
      height: 54,
      child: Row(
        children: [
          Expanded(
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.fromLTRB(16, 8, 8, 8),
              itemCount: categories.length,
              separatorBuilder: (context, index) => const SizedBox(width: 8),
              itemBuilder: (context, index) {
                final category = categories[index];
                final selected = category == _category;
                return ChoiceChip(
                  label: Text(category),
                  selected: selected,
                  showCheckmark: false,
                  visualDensity: VisualDensity.compact,
                  onSelected: (_) {
                    setState(() => _category = category);
                    context
                        .read<ProductProvider>()
                        .loadProducts(category: category == 'All' ? '' : category);
                  },
                  selectedColor: AppColors.inkBlack,
                  backgroundColor: AppColors.surface,
                  side: BorderSide(
                    color: selected ? AppColors.inkBlack : AppColors.hairline,
                  ),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(999),
                  ),
                  labelStyle: TextStyle(
                    color: selected ? Colors.white : AppColors.textPrimary,
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                  ),
                );
              },
            ),
          ),
          Container(
            width: 1,
            height: 24,
            margin: const EdgeInsets.symmetric(horizontal: 4),
            color: AppColors.hairline,
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(4, 8, 16, 8),
            child: Tooltip(
              message: 'Sorted by: $sortLabel',
              child: InkWell(
                borderRadius: BorderRadius.circular(999),
                onTap: _openSortSheet,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
                  decoration: BoxDecoration(
                    color: _sort == 'newest'
                        ? AppColors.surface
                        : AppColors.royalBlue.withOpacity(0.08),
                    borderRadius: BorderRadius.circular(999),
                    border: Border.all(
                      color: _sort == 'newest'
                          ? AppColors.hairline
                          : AppColors.royalBlue.withOpacity(0.4),
                    ),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        Icons.sort,
                        size: 16,
                        color: _sort == 'newest'
                            ? AppColors.textPrimary
                            : AppColors.royalBlue,
                      ),
                      const SizedBox(width: 5),
                      Text(
                        _sort == 'newest' ? 'Sort' : 'Sorted',
                        style: TextStyle(
                          color: _sort == 'newest'
                              ? AppColors.textPrimary
                              : AppColors.royalBlue,
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
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
      return _warmupVisible
          ? const _WakeUpCard()
          : const Center(
              child: CircularProgressIndicator(color: AppColors.royalBlue),
            );
    }
    if (showError) {
      return _FeedMessage(
        icon: Icons.cloud_off_outlined,
        title: 'Could not reach the marketplace',
        message: provider.errorMessage ?? 'Unknown error',
        actionLabel: 'Retry',
        onAction: () => _retryFeed(provider),
      );
    }

    final noMatches = visible.isEmpty;
    final filtersActive = _category != 'All' || _query.isNotEmpty;

    return RefreshIndicator(
      color: AppColors.royalBlue,
      backgroundColor: AppColors.surface,
      onRefresh: () async {
        _scheduleWarmup();
        await provider.loadProducts();
      },
      child: noMatches
          ? _FeedMessage(
              icon: Icons.search_off_outlined,
              title: filtersActive ? 'No listings match your filters' : 'No listings here yet',
              message: filtersActive
                  ? 'Nothing matches "$_category"$_queryHint right now. '
                      'Refresh to check for new campus listings.'
                  : 'Pull down to refresh, or sell the first item!',
              actionLabel: 'Refresh Feed',
              onAction: () => _retryFeed(provider),
              secondaryLabel: 'Clear filters',
              onSecondaryAction: () {
                _searchDebounce?.cancel();
                _searchController.clear();
                setState(() {
                  _query = '';
                  _category = 'All';
                });
                context
                    .read<ProductProvider>()
                    .loadProducts(query: '', category: '');
              },
            )
          : GridView.builder(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
              gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                crossAxisCount: 2,
                mainAxisSpacing: 12,
                crossAxisSpacing: 12,
                childAspectRatio: 0.60,
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

  /// Restarts the warmup countdown and refetches (all retry entry points).
  void _retryFeed(ProductProvider provider) {
    _scheduleWarmup();
    provider.loadProducts();
  }
}

/// Cold-start card shown while a slow first load (>3s) is still pending.
/// Task 4's Render warm-start UX: honest progress copy, no server internals.
class _WakeUpCard extends StatelessWidget {
  const _WakeUpCard();

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Padding(
        padding: EdgeInsets.symmetric(horizontal: 36),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            SizedBox(
              width: 46,
              height: 46,
              child: CircularProgressIndicator(
                strokeWidth: 3.5,
                color: AppColors.royalBlue,
              ),
            ),
            SizedBox(height: 22),
            Text(
              'Connecting to Campus Mart Ai Marketplace',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: AppColors.textPrimary,
                fontSize: 15.5,
                fontWeight: FontWeight.w800,
              ),
            ),
            SizedBox(height: 8),
            Text(
              'Hang tight! Waking up our cloud AI server (takes ~30-60 '
              'seconds on first launch)...',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: AppColors.textMuted,
                fontSize: 12.5,
                height: 1.45,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Horizontal "✨ AI Recommended For You" rail.
///
/// Ranking comes from [RecommendationEngine], which scores each listing on
/// value (listed price vs AI fair price) and the seller's live trust score.
class _AiRecommendationRail extends StatelessWidget {
  const _AiRecommendationRail({required this.products, required this.onOpen});

  final List<Product> products;
  final ValueChanged<Product> onOpen;

  @override
  Widget build(BuildContext context) {
    final picks = RecommendationEngine.rankForYou(products, limit: 6);
    if (picks.isEmpty) return const SizedBox.shrink();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Padding(
          padding: EdgeInsets.fromLTRB(16, 12, 16, 8),
          child: Row(
            children: [
              Icon(Icons.auto_awesome, size: 16, color: AppColors.royalBlue),
              SizedBox(width: 6),
              Text(
                'AI Recommended For You',
                style: TextStyle(
                  color: AppColors.inkBlack,
                  fontSize: 14,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ],
          ),
        ),
        SizedBox(
          height: 200,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 4),
            itemCount: picks.length,
            separatorBuilder: (context, index) => const SizedBox(width: 12),
            itemBuilder: (context, index) {
              final product = picks[index];
              return _RecommendationCard(
                product: product,
                onTap: () => onOpen(product),
              );
            },
          ),
        ),
      ],
    );
  }
}

/// Compact card used inside the AI recommendation rail.
class _RecommendationCard extends StatelessWidget {
  const _RecommendationCard({
    required this.product,
    required this.onTap,
  });

  final Product product;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final suggested = product.suggestedPrice;
    final below = suggested != null && suggested > 0 && product.listedPrice < suggested;

    return SizedBox(
      width: 156,
      child: Material(
        color: AppColors.surface,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: const BorderSide(
            color: AppColors.hairline,
            width: 1,
          ),
        ),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Stack(
                  fit: StackFit.expand,
                  children: [
                    product.imageUrl.isEmpty
                        ? const ColoredBox(color: AppColors.surfaceHigh)
                        : Image.network(
                            product.imageUrl,
                            fit: BoxFit.cover,
                            errorBuilder: (context, error, stack) =>
                                const ColoredBox(color: AppColors.surfaceHigh),
                            loadingBuilder: (context, child, progress) =>
                                progress == null
                                    ? child
                                    : const Center(
                                        child: SizedBox(
                                          width: 18,
                                          height: 18,
                                          child: CircularProgressIndicator(
                                            strokeWidth: 2,
                                            color: AppColors.royalBlue,
                                          ),
                                        ),
                                      ),
                          ),
                    if (below)
                      const Positioned(
                        top: 6,
                        left: 6,
                        child: _AiPickBadge(),
                      ),
                  ],
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(9, 8, 9, 10),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      product.title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: AppColors.textPrimary,
                        fontSize: 12,
                        height: 1.25,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            formatInr(product.listedPrice),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                              color: AppColors.inkBlack,
                              fontSize: 14.5,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                        ),
                        const Icon(
                          Icons.shield_outlined,
                          size: 13,
                          color: AppColors.royalBlue,
                        ),
                        const SizedBox(width: 2),
                        Text(
                          (product.sellerTrustScore ?? 5.0).toStringAsFixed(1),
                          style: const TextStyle(
                            color: AppColors.textPrimary,
                            fontSize: 11,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 6),
                    if (below)
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 2),
                        decoration: BoxDecoration(
                          color: AppColors.forestGreen.withOpacity(0.1),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: Text(
                          'Save ₹${(suggested - product.listedPrice).round()}',
                          style: const TextStyle(
                            color: AppColors.forestGreen,
                            fontSize: 10,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      )
                    else
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 2),
                        decoration: BoxDecoration(
                          color: AppColors.royalBlue.withOpacity(0.08),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: Text(
                          product.category,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            color: AppColors.royalBlue,
                            fontSize: 10,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Small "AI PICK" tag drawn over a recommended photo.
class _AiPickBadge extends StatelessWidget {
  const _AiPickBadge();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
      decoration: BoxDecoration(
        color: AppColors.royalBlue,
        borderRadius: BorderRadius.circular(6),
      ),
      child: const Text(
        'AI PICK',
        style: TextStyle(
          color: Colors.white,
          fontSize: 8,
          fontWeight: FontWeight.w900,
          letterSpacing: 0.4,
        ),
      ),
    );
  }
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
                        color: AppColors.royalBlue,
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
