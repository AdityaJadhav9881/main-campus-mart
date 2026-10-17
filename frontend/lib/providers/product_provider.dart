import 'package:flutter/foundation.dart';

import '../models/product.dart';
import '../services/api_service.dart';
import 'auth_provider.dart';

import '../services/local_cache_service.dart';

/// Feed state for the discovery grid: loading flag, error message, and the
/// list of active products.
///
/// Wired into the widget tree via `ChangeNotifierProxyProvider` so it always
/// holds a reference to the current [AuthProvider] (for the bearer token used
/// by [addProduct]).
class ProductProvider extends ChangeNotifier {
  ProductProvider(this._auth) {
    _loadFromCache();
  }

  AuthProvider _auth;
  final ApiService _api = ApiService.instance;

  List<Product> _products = const [];
  bool _isLoading = false;
  String? _errorMessage;

  /// Last server-side search filters (kept so pull-to-refresh re-applies them).
  String _lastQuery = '';
  String _lastCategory = '';
  String _lastCollege = '';
  String _lastBranch = '';
  String _lastYear = '';

  List<Product> get products => _products;
  bool get isLoading => _isLoading;
  String? get errorMessage => _errorMessage;

  Future<void> _loadFromCache() async {
    try {
      final cached = await LocalCacheService.getCachedFeedProducts();
      if (cached != null && cached.isNotEmpty && _products.isEmpty) {
        _products = cached.map((map) => Product.fromJson(map)).toList();
        notifyListeners();
      }
    } catch (_) {}
  }

  /// Re-binds the auth source whenever the AuthProvider instance changes
  /// (called by ChangeNotifierProxyProvider.update).
  void bindAuth(AuthProvider auth) {
    _auth = auth;
  }

  /// GET /products/ - first load and pull-to-refresh.
  Future<void> loadProducts({
    String? query,
    String? category,
    String? college,
    String? branch,
    String? academicYear,
  }) async {
    if (query != null) _lastQuery = query.trim();
    if (category != null) _lastCategory = category.trim();
    if (college != null) _lastCollege = college.trim();
    if (branch != null) _lastBranch = branch.trim();
    if (academicYear != null) _lastYear = academicYear.trim();

    // If we have no cached items, show spinner. If cached items exist, load silently in background.
    if (_products.isEmpty) {
      _isLoading = true;
    }
    _errorMessage = null;
    notifyListeners();
    try {
      final fetched = await _api.fetchActiveProducts(
        query: _lastQuery.isEmpty ? null : _lastQuery,
        category: _lastCategory.isEmpty ? null : _lastCategory,
        college: _lastCollege.isEmpty ? null : _lastCollege,
        branch: _lastBranch.isEmpty ? null : _lastBranch,
        academicYear: _lastYear.isEmpty ? null : _lastYear,
      );
      _products = fetched;
      LocalCacheService.cacheFeedProducts(fetched.map((p) => p.toJson()).toList());
    } on ApiException catch (error) {
      _errorMessage = error.message;
    } catch (error) {
      _errorMessage = 'Could not load listings: $error';
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// POST /products/ - server runs the LangGraph AI pipeline (category,
  /// price suggestion, fraud check) before inserting.
  ///
  /// Returns the AI-processed [Product] on success, or null on failure with
  /// the cause in [errorMessage].
  Future<Product?> addProduct(Map<String, dynamic> data) async {
    _isLoading = true;
    _errorMessage = null;
    notifyListeners();
    try {
      final created = await _api.createProductListing(data, _auth.token);
      // Prepend so the feed shows the new listing first without a refetch.
      _products = <Product>[
        created,
        ..._products.where((existing) => existing.id != created.id),
      ];
      return created;
    } on ApiException catch (error) {
      _errorMessage = error.message;
      return null;
    } catch (error) {
      _errorMessage = 'Could not create listing: $error';
      return null;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }
}
