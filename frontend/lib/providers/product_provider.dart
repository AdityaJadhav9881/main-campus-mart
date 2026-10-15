import 'package:flutter/foundation.dart';

import '../models/product.dart';
import '../services/api_service.dart';
import 'auth_provider.dart';

/// Feed state for the discovery grid: loading flag, error message, and the
/// list of active products.
///
/// Wired into the widget tree via `ChangeNotifierProxyProvider` so it always
/// holds a reference to the current [AuthProvider] (for the bearer token used
/// by [addProduct]).
class ProductProvider extends ChangeNotifier {
  ProductProvider(this._auth);

  AuthProvider _auth;
  final ApiService _api = ApiService.instance;

  List<Product> _products = const [];
  bool _isLoading = false;
  String? _errorMessage;

  List<Product> get products => _products;
  bool get isLoading => _isLoading;
  String? get errorMessage => _errorMessage;

  /// Re-binds the auth source whenever the AuthProvider instance changes
  /// (called by ChangeNotifierProxyProvider.update).
  void bindAuth(AuthProvider auth) {
    _auth = auth;
  }

  /// GET /products/ - first load and pull-to-refresh.
  /// Existing items are kept visible during a refresh so the grid never
  /// flashes empty; the full-screen loader only appears when there is
  /// nothing to show yet.
  Future<void> loadProducts() async {
    _isLoading = true;
    _errorMessage = null;
    notifyListeners();
    try {
      _products = await _api.fetchActiveProducts();
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
