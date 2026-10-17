import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/product.dart';
import '../providers/auth_provider.dart';
import '../providers/cart_provider.dart';
import '../providers/product_provider.dart';
import '../services/currency.dart';
import '../services/notification_service.dart';
import '../services/recommendations.dart';
import '../widgets/animated_brand_logo.dart';
import '../widgets/app_theme.dart';
import '../widgets/college_picker_sheet.dart';
import '../widgets/product_card.dart';
import 'cart_screen.dart';
import 'notifications_screen.dart';
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
  const FeedScreen({super.key, this.onChromeVisibilityChanged});

  /// Notifies the tab shell to slide the bottom navigation bar away while
  /// the student is scrolling DOWN through products (and back on scroll-up).
  /// `true` = show the bottom nav, `false` = hide it.
  final ValueChanged<bool>? onChromeVisibilityChanged;

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

  /// Immersive browsing chrome: scrolling DOWN collapses the AI recommendation
  /// rail and slides the bottom navigation bar away; scrolling UP (or hitting
  /// the top of the feed) smoothly brings both back.
  bool _chromeVisible = true;

  /// College-network toggle: when ON, the feed shows only listings published
  /// by students of the signed-in student's own college (`?college=`).
  bool _myCollegeOnly = false;

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

  /// Auto-hide chrome while the student browses products.
  ///
  /// Only VERTICAL scrolls of the main product grid count (the horizontal
  /// category chips and AI rail notifications are ignored):
  ///   * scrolling DOWN  -> hide the bottom nav + collapse the AI rail,
  ///   * scrolling UP    -> bring both back,
  ///   * reaching the top -> always restore.
  bool _handleScrollNotification(ScrollNotification notification) {
    if (notification.metrics.axis != Axis.vertical) return false;

    final pixels = notification.metrics.pixels;
    if (pixels <= 0) {
      _setChromeVisible(true);
      return false;
    }

    if (notification is ScrollUpdateNotification) {
      final delta = notification.scrollDelta ?? 0;
      if (delta > 1.2) {
        if (pixels > 36) _setChromeVisible(false);
      } else if (delta < -1.2) {
        _setChromeVisible(true);
      }
    }
    return false;
  }

  void _setChromeVisible(bool visible) {
    if (!mounted || _chromeVisible == visible) return;
    setState(() => _chromeVisible = visible);
    widget.onChromeVisibilityChanged?.call(visible);
  }

  /// "🎓 My College" toggle: filters the feed to the student's campus.
  /// First tap on an account without a college opens the CET picker sheet.
  Widget _buildMyCollegeChip() {
    final auth = context.watch<AuthProvider>();
    final collegeName = auth.profile?.collegeName ?? '';
    final label = _myCollegeOnly && collegeName.isNotEmpty
        ? (auth.profile?.collegeBadge ?? 'My College')
        : 'My College';
    return ChoiceChip(
      avatar: Icon(
        Icons.school,
        size: 15,
        color: _myCollegeOnly ? Colors.white : AppColors.royalBlue,
      ),
      label: Text(label),
      selected: _myCollegeOnly,
      showCheckmark: false,
      visualDensity: VisualDensity.compact,
      onSelected: (_) => _toggleMyCollege(),
      selectedColor: AppColors.royalBlue,
      backgroundColor: AppColors.surface,
      side: BorderSide(
        color: _myCollegeOnly
            ? AppColors.royalBlue
            : AppColors.royalBlue.withOpacity(0.45),
      ),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(999),
      ),
      labelStyle: TextStyle(
        color: _myCollegeOnly ? Colors.white : AppColors.royalBlue,
        fontSize: 12,
        fontWeight: FontWeight.w700,
      ),
    );
  }

  /// Toggles the campus network filter (picking a college first if needed).
  Future<void> _toggleMyCollege() async {
    final auth = context.read<AuthProvider>();
    var collegeName = auth.profile?.collegeName ?? '';

    if (collegeName.isEmpty) {
      final picked = await showCollegePickerSheet(
        context,
        title: 'Set your college to join its network',
      );
      if (picked == null || !mounted) return;
      final saved = await auth.updateCollege(
        collegeName: picked.name,
        collegeCode: picked.code,
      );
      if (!saved || !mounted) return;
      collegeName = picked.name;
    }

    setState(() => _myCollegeOnly = !_myCollegeOnly);
    await context.read<ProductProvider>().loadProducts(
          college: _myCollegeOnly ? collegeName : '',
        );
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

  /// Opens the alert center; the poller keeps running while it is open.
  Future<void> _openNotifications() async {
    await NotificationService.instance.refresh();
    if (!mounted) return;
    await Navigator.of(context).push(
      MaterialPageRoute<void>(builder: (_) => const NotificationsScreen()),
    );
    // The screen may have marked rows read - re-sync the badge on return.
    NotificationService.instance.refreshBadge();
  }

  /// Opens the cart (Part B Task 7); refresh the snapshot on return so the
  /// header badge reflects purchases made from checkout.
  Future<void> _openCart() async {
    await Navigator.of(context).push(
      MaterialPageRoute<void>(builder: (_) => const CartScreen()),
    );
    if (!mounted) return;
    context.read<CartProvider>().load();
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
        titleSpacing: 12,
        title: Row(
          children: [
            const ClipRRect(
              borderRadius: BorderRadius.all(Radius.circular(8)),
              child: Image(
                image: AssetImage('assets/logo.png'),
                width: 34,
                height: 34,
                fit: BoxFit.cover,
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              // ClipRRect keeps EVERYTHING inside the pill: the theme's
              // filled input decoration can no longer leak square corners
              // over the rounded search border.
              child: ClipRRect(
                borderRadius: BorderRadius.circular(999),
                child: Container(
                  height: 42,
                  decoration: BoxDecoration(
                    color: AppColors.surfaceHigh,
                    borderRadius: BorderRadius.circular(999),
                    border: Border.all(color: AppColors.hairline),
                  ),
                  child: TextField(
                    controller: _searchController,
                    onChanged: _onSearchChanged,
                    style: const TextStyle(
                        color: AppColors.textPrimary, fontSize: 13.5),
                    decoration: InputDecoration(
                      isDense: true,
                      // Explicitly override ThemeData.inputDecorationTheme
                      // (which is filled + rectangular): ZERO inner square
                      // fill or border may show inside the pill.
                      filled: false,
                      fillColor: Colors.transparent,
                      contentPadding: const EdgeInsets.symmetric(
                          horizontal: 12, vertical: 10),
                      hintText: 'Search campus listings...',
                      hintStyle: const TextStyle(
                          color: AppColors.textMuted, fontSize: 13),
                      border: InputBorder.none,
                      enabledBorder: InputBorder.none,
                      focusedBorder: InputBorder.none,
                      errorBorder: InputBorder.none,
                      focusedErrorBorder: InputBorder.none,
                      prefixIcon: const Icon(
                        Icons.search,
                        color: AppColors.textMuted,
                        size: 19,
                      ),
                      suffixIcon: _query.isEmpty
                          ? null
                          : IconButton(
                              icon: const Icon(
                                Icons.clear,
                                color: AppColors.textMuted,
                                size: 16,
                              ),
                              padding: EdgeInsets.zero,
                              onPressed: () {
                                _searchDebounce?.cancel();
                                _searchController.clear();
                                setState(() => _query = '');
                                context
                                    .read<ProductProvider>()
                                    .loadProducts(query: '');
                              },
                            ),
                    ),
                  ),
                ),
              ),
            ),
            const SizedBox(width: 4),
            // Cart with a live item-count badge (Part B Task 7).
            Consumer<CartProvider>(
              builder: (context, cart, _) {
                return Stack(
                  clipBehavior: Clip.none,
                  children: [
                    IconButton(
                      icon: const Icon(
                        Icons.shopping_cart_outlined,
                        color: AppColors.inkBlack,
                        size: 22,
                      ),
                      tooltip: 'My Cart',
                      onPressed: _openCart,
                    ),
                    if (cart.count > 0)
                      Positioned(
                        right: 5,
                        top: 5,
                        child: IgnorePointer(
                          child: Container(
                            constraints: const BoxConstraints(minWidth: 16),
                            height: 16,
                            padding:
                                const EdgeInsets.symmetric(horizontal: 4),
                            decoration: BoxDecoration(
                              color: AppColors.royalBlue,
                              borderRadius: BorderRadius.circular(999),
                              border: Border.all(
                                color: AppColors.background,
                                width: 1.4,
                              ),
                            ),
                            child: Center(
                              child: Text(
                                cart.count > 9 ? '9+' : '${cart.count}',
                                style: const TextStyle(
                                  color: Colors.white,
                                  fontSize: 9.5,
                                  fontWeight: FontWeight.w900,
                                  height: 1,
                                ),
                              ),
                            ),
                          ),
                        ),
                      ),
                  ],
                );
              },
            ),
            // Bell with live unread badge, fed by the 15s notification poller.
            ValueListenableBuilder<int>(
              valueListenable: NotificationService.instance.unreadCount,
              builder: (context, unread, _) {
                return Stack(
                  clipBehavior: Clip.none,
                  children: [
                    IconButton(
                      icon: const Icon(
                        Icons.notifications_none_rounded,
                        color: AppColors.inkBlack,
                        size: 23,
                      ),
                      tooltip: 'Notifications',
                      onPressed: _openNotifications,
                    ),
                    if (unread > 0)
                      Positioned(
                        right: 5,
                        top: 5,
                        child: IgnorePointer(
                          child: Container(
                            constraints: const BoxConstraints(minWidth: 16),
                            height: 16,
                            padding:
                                const EdgeInsets.symmetric(horizontal: 4),
                            decoration: BoxDecoration(
                              color: AppColors.danger,
                              borderRadius: BorderRadius.circular(999),
                              border: Border.all(
                                color: AppColors.background,
                                width: 1.4,
                              ),
                            ),
                            child: Center(
                              child: Text(
                                unread > 9 ? '9+' : '$unread',
                                style: const TextStyle(
                                  color: Colors.white,
                                  fontSize: 9.5,
                                  fontWeight: FontWeight.w900,
                                  height: 1,
                                ),
                              ),
                            ),
                          ),
                        ),
                      ),
                  ],
                );
              },
            ),
          ],
        ),
      ),
      body: Column(
        children: [
          if (showRecommendations) ...[
            // Collapses smoothly to zero height while the student scrolls
            // DOWN, and expands back the moment they scroll UP.
            AnimatedSize(
              duration: const Duration(milliseconds: 240),
              curve: Curves.easeOutCubic,
              alignment: Alignment.topCenter,
              child: _chromeVisible
                  ? _AiRecommendationRail(
                      products: provider.products,
                      onOpen: _openDetail,
                    )
                  : const SizedBox(width: double.infinity),
            ),
          ],
          _buildFilterRow(categories),
          Expanded(
            child: NotificationListener<ScrollNotification>(
              onNotification: _handleScrollNotification,
              child: _buildBody(provider, visible),
            ),
          ),
        ],
      ),
    );
  }

  /// Category chips (dynamic) + a Sort button that opens the sort sheet.
  ///
  /// The chip row leads with the "🎓 My College" campus-network toggle; when
  /// the profile has no college yet, tapping it opens the CET picker first.
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
              itemCount: categories.length + 1,
              separatorBuilder: (context, index) => const SizedBox(width: 8),
              itemBuilder: (context, index) {
                if (index == 0) return _buildMyCollegeChip();
                final category = categories[index - 1];
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
/// Task 4's Render warm-start UX + Task B4's animated brand mark and honest
/// phase steps - no server internals.
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
            AnimatedBrandLogo(size: 100),
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
            SizedBox(height: 16),
            WarmupStepIndicator(),
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
          padding: EdgeInsets.fromLTRB(16, 10, 16, 7),
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
          height: 112,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 2),
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

/// Compact horizontal card used inside the AI recommendation rail:
/// photo on the left, then title / price / savings stacked on the right.
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
    final trust = product.sellerTrustScore ?? 5.0;

    return SizedBox(
      width: 292,
      child: Material(
        color: AppColors.surface,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(14),
          side: const BorderSide(
            color: AppColors.hairline,
            width: 1.2,
          ),
        ),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              SizedBox(
                width: 104,
                child: product.imageUrl.isEmpty
                    ? const ColoredBox(color: AppColors.surfaceHigh)
                    : Image.network(
                        product.imageUrl,
                        fit: BoxFit.cover,
                        errorBuilder: (context, error, stack) =>
                            const ColoredBox(color: AppColors.surfaceHigh),
                        loadingBuilder: (context, child, progress) =>
                            progress == null
                                ? child
                                : const ColoredBox(
                                    color: AppColors.surfaceHigh,
                                    child: Center(
                                      child: SizedBox(
                                        width: 16,
                                        height: 16,
                                        child: CircularProgressIndicator(
                                          strokeWidth: 2,
                                          color: AppColors.royalBlue,
                                        ),
                                      ),
                                    ),
                                  ),
                      ),
              ),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(11, 9, 11, 9),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        product.title,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          color: AppColors.textPrimary,
                          fontSize: 12.5,
                          height: 1.25,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.baseline,
                        textBaseline: TextBaseline.alphabetic,
                        children: [
                          Text(
                            formatInr(product.listedPrice),
                            style: const TextStyle(
                              color: AppColors.inkBlack,
                              fontSize: 15.5,
                              fontWeight: FontWeight.w900,
                              letterSpacing: -0.2,
                            ),
                          ),
                          if (below) ...[
                            const SizedBox(width: 5),
                            Flexible(
                              child: Text(
                                formatInr(suggested),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                  color: AppColors.textMuted,
                                  fontSize: 11,
                                  decoration: TextDecoration.lineThrough,
                                  fontWeight: FontWeight.w500,
                                ),
                              ),
                            ),
                          ],
                        ],
                      ),
                      Row(
                        children: [
                          const Icon(
                            Icons.shield,
                            size: 11,
                            color: AppColors.forestGreen,
                          ),
                          const SizedBox(width: 3),
                          Text(
                            trust.toStringAsFixed(1),
                            style: const TextStyle(
                              color: AppColors.textMuted,
                              fontSize: 10.5,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                          const SizedBox(width: 6),
                          Expanded(
                            child: Text(
                              '${product.condition} · ${product.category}',
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                color: AppColors.textMuted,
                                fontSize: 10.5,
                                fontWeight: FontWeight.w500,
                              ),
                            ),
                          ),
                        ],
                      ),
                      if (below)
                        Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 7, vertical: 3),
                          decoration: BoxDecoration(
                            color: AppColors.forestGreen.withOpacity(0.12),
                            borderRadius: BorderRadius.circular(6),
                          ),
                          child: Text(
                            'SAVE ₹${(suggested - product.listedPrice).round()}',
                            style: const TextStyle(
                              color: AppColors.forestGreen,
                              fontSize: 9.5,
                              fontWeight: FontWeight.w900,
                              letterSpacing: 0.3,
                            ),
                          ),
                        )
                      else
                        const _AiPickBadge(),
                    ],
                  ),
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
