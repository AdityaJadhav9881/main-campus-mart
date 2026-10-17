import 'package:flutter/foundation.dart';

import '../models/cart_models.dart';
import '../services/api_service.dart';
import 'auth_provider.dart';

/// Shopping-cart state for the whole app (Part B Task 7).
///
/// Holds the latest `GET /cart/` snapshot so the Discover cart badge, the
/// product-detail "Add to Cart" button and the cart screen always agree.
/// Auto-loads once a session appears and clears itself on logout.
class CartProvider extends ChangeNotifier {
  CartProvider(this._auth) {
    _syncWithAuth();
  }

  AuthProvider _auth;
  final ApiService _api = ApiService.instance;

  CartSummary _summary = const CartSummary();
  bool _isLoading = false;
  String? _errorMessage;

  List<CartLine> get items => _summary.items;
  int get count => _summary.count;
  double get totalPrice => _summary.totalPrice;
  bool get isLoading => _isLoading;
  String? get errorMessage => _errorMessage;

  /// Re-binds the auth source (ChangeNotifierProxyProvider.update).
  void bindAuth(AuthProvider auth) {
    final tokenChanged = _auth.token != auth.token;
    _auth = auth;
    if (tokenChanged) _syncWithAuth();
  }

  void _syncWithAuth() {
    if (_auth.token.isEmpty) {
      if (_summary.count != 0) {
        _summary = const CartSummary();
        notifyListeners();
      }
      return;
    }
    if (_summary.count == 0 && !_isLoading) load();
  }

  /// GET /cart/ - refresh the snapshot (pull-to-refresh + boot).
  Future<void> load() async {
    final token = _auth.token;
    if (token.isEmpty) return;
    _isLoading = true;
    notifyListeners();
    try {
      _summary = await _api.fetchCart(token: token);
      _errorMessage = null;
    } on ApiException catch (error) {
      _errorMessage = error.message;
    } catch (_) {
      _errorMessage = 'Could not load your cart right now.';
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// POST /cart/{product_id} - park a listing (idempotent server-side).
  Future<bool> add(String productId) async {
    final token = _auth.token;
    if (token.isEmpty) return false;
    try {
      _summary = await _api.addToCart(productId: productId, token: token);
      _errorMessage = null;
      notifyListeners();
      return true;
    } on ApiException catch (error) {
      _errorMessage = error.message;
      notifyListeners();
      return false;
    } catch (_) {
      _errorMessage = 'Could not update your cart right now.';
      notifyListeners();
      return false;
    }
  }

  /// DELETE /cart/{product_id} - remove one listing (idempotent).
  Future<bool> remove(String productId) async {
    final token = _auth.token;
    if (token.isEmpty) return false;
    try {
      _summary = await _api.removeFromCart(productId: productId, token: token);
      _errorMessage = null;
      notifyListeners();
      return true;
    } on ApiException catch (error) {
      _errorMessage = error.message;
      notifyListeners();
      return false;
    } catch (_) {
      _errorMessage = 'Could not update your cart right now.';
      notifyListeners();
      return false;
    }
  }

  bool contains(String productId) =>
      _summary.items.any((line) => line.product.id == productId);

  /// Optimistically drop a line after its checkout succeeded.
  void removeLocal(String productId) {
    final remaining = _summary.items
        .where((line) => line.product.id != productId)
        .toList(growable: false);
    _summary = CartSummary(
      items: remaining,
      count: remaining.length,
      totalPrice: remaining.fold(0, (sum, line) => sum + line.product.listedPrice),
    );
    notifyListeners();
  }
}
