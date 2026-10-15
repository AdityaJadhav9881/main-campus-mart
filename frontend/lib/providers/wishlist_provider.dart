import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Wishlist (saved items) state, persisted in `shared_preferences` so hearts
/// survive app restarts without needing a backend table.
///
/// Key design points:
///  * Stores product IDs only (tiny payload, safe to write on every toggle).
///  * In-memory `Set<String>` is the source of truth; storage writes are
///    fire-and-forget best effort so a storage failure never blocks the UI.
///  * Lives alongside AuthProvider/ProductProvider in the root MultiProvider
///    so the Discover grid and the Profile "Saved" tab observe the same state.
class WishlistProvider extends ChangeNotifier {
  static const String _storageKey = 'wishlist_product_ids';

  final Set<String> _ids = <String>{};
  bool _loaded = false;

  /// True once [load] has completed (drives first-frame placeholder states).
  bool get isLoaded => _loaded;

  /// Unmodifiable view of saved product IDs.
  Set<String> get ids => Set<String>.unmodifiable(_ids);

  bool get isEmpty => _ids.isEmpty;
  int get count => _ids.length;

  bool contains(String productId) => _ids.contains(productId);

  /// Restores the persisted wishlist (called once during bootstrap).
  Future<void> load() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final saved = prefs.getStringList(_storageKey) ?? const <String>[];
      _ids
        ..clear()
        ..addAll(saved);
    } catch (_) {
      // Storage unavailable -> start with an empty wishlist, never crash.
    } finally {
      _loaded = true;
      notifyListeners();
    }
  }

  /// Returns the NEW saved state after toggling (handy for optimistic UI).
  bool toggle(String productId) {
    final nowSaved = !_ids.remove(productId);
    if (nowSaved) _ids.add(productId);
    notifyListeners();
    unawaitedPersist();
    return nowSaved;
  }

  void remove(String productId) {
    if (_ids.remove(productId)) {
      notifyListeners();
      unawaitedPersist();
    }
  }

  /// Best-effort persistence - failures are silent because the in-memory
  /// state already matches what the user sees.
  Future<void> unawaitedPersist() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setStringList(_storageKey, _ids.toList(growable: false));
    } catch (_) {
      // Intentionally ignored: wishlist is a convenience, not critical data.
    }
  }
}
