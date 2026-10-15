import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'providers/auth_provider.dart';
import 'providers/product_provider.dart';
import 'providers/wishlist_provider.dart';
import 'screens/auth_screen.dart';
import 'screens/create_listing_screen.dart';
import 'screens/feed_screen.dart';
import 'screens/profile_screen.dart';
import 'widgets/app_theme.dart';

void main() {
  runApp(const CampusMartApp());
}

/// Root application widget: registers the providers and applies the dark
/// "deep void" theme. Phase 7 gates the shell behind real campus auth —
/// logged-out users see AuthScreen; logged-in users get the 3-tab shell.
class CampusMartApp extends StatelessWidget {
  const CampusMartApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        // Session must be registered first - ProductProvider reads the
        // bearer token from it when creating listings.
        ChangeNotifierProvider<AuthProvider>(
          create: (_) => AuthProvider()..bootstrap(),
        ),
        // Wishlist hearts are independent of auth (persisted locally), so a
        // plain provider is enough - load() restores saved IDs on boot.
        ChangeNotifierProvider<WishlistProvider>(
          create: (_) => WishlistProvider()..load(),
        ),
        ChangeNotifierProxyProvider<AuthProvider, ProductProvider>(
          create: (context) => ProductProvider(context.read<AuthProvider>()),
          update: (_, auth, previous) =>
              (previous ?? ProductProvider(auth))..bindAuth(auth),
        ),
      ],
      child: MaterialApp(
        title: 'Campus Mart Ai',
        debugShowCheckedModeBanner: false,
        theme: AppTheme.dark,
        home: const _AuthGate(),
      ),
    );
  }
}

/// Watches the session and swaps between AuthScreen and the tab shell.
class _AuthGate extends StatelessWidget {
  const _AuthGate();

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthProvider>();

    if (auth.isRestoring) {
      return const Scaffold(
        backgroundColor: AppColors.voidBlack,
        body: Center(
          child: CircularProgressIndicator(color: AppColors.cyanAccent),
        ),
      );
    }

    if (!auth.isLoggedIn) {
      return const AuthScreen();
    }

    return const MainNavigationShell();
  }
}

/// Three-tab navigation shell (spec Task 5):
///  0. Discovery Feed
///  1. Sell / Create Listing
///  2. Profile & Campus Trust
class MainNavigationShell extends StatefulWidget {
  const MainNavigationShell({super.key});

  @override
  State<MainNavigationShell> createState() => _MainNavigationShellState();
}

class _MainNavigationShellState extends State<MainNavigationShell> {
  int _index = 0;

  /// Screens are built once so every tab keeps its own state while hidden
  /// (IndexedStack keeps offstage children alive).
  late final List<Widget> _screens;

  @override
  void initState() {
    super.initState();
    _screens = <Widget>[
      const FeedScreen(),
      // After a successful listing the shell jumps back to the feed tab.
      CreateListingScreen(onListingCreated: _showFeedTab),
      const ProfileScreen(),
    ];
  }

  void _showFeedTab() => setState(() => _index = 0);

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(
        index: _index,
        children: _screens,
      ),
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _index,
        onTap: (index) => setState(() => _index = index),
        items: const [
          BottomNavigationBarItem(
            icon: Icon(Icons.explore_outlined),
            activeIcon: Icon(Icons.explore),
            label: 'Discover',
          ),
          BottomNavigationBarItem(
            icon: Icon(Icons.add_box_outlined),
            activeIcon: Icon(Icons.add_box),
            label: 'Sell',
          ),
          BottomNavigationBarItem(
            icon: Icon(Icons.person_outline),
            activeIcon: Icon(Icons.person),
            label: 'Profile',
          ),
        ],
      ),
    );
  }
}
