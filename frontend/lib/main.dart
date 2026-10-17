import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import 'providers/auth_provider.dart';
import 'providers/cart_provider.dart';
import 'providers/product_provider.dart';
import 'providers/wishlist_provider.dart';
import 'screens/ai_assistant_screen.dart';
import 'screens/auth_screen.dart';
import 'screens/create_listing_screen.dart';
import 'screens/feed_screen.dart';
import 'screens/messages_screen.dart';
import 'screens/profile_screen.dart';
import 'services/api_service.dart';
import 'services/local_cache_service.dart';
import 'services/notification_service.dart';
import 'services/permission_service.dart';
import 'widgets/animated_brand_logo.dart';
import 'widgets/app_theme.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await LocalCacheService.init();
  PermissionService.requestAllAppPermissions();
  runApp(const CampusMartApp());
}

/// Root application widget: registers the providers and applies the dark
/// "deep void" theme. The shell gates behind real campus auth - logged-out
/// users see AuthScreen; logged-in users get the 5-tab shell (with the
/// blocked-account and cold-start overlays layered on top).
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
        // Cart badge shared by the Discover header, product detail and the
        // cart screen (Part B Task 7).
        ChangeNotifierProxyProvider<AuthProvider, CartProvider>(
          create: (context) => CartProvider(context.read<AuthProvider>()),
          update: (_, auth, previous) =>
              (previous ?? CartProvider(auth))..bindAuth(auth),
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

/// Watches the session and swaps between AuthScreen and the tab shell, and
/// stacks the two cross-cutting gates on top:
///  * **Boot warmup** - after 3s of a slow restore, show the honest
///    "Connecting to Campus Mart Ai" card instead of an endless spinner.
///  * **Access terminated** - any `ACCOUNT_TERMINATED` 403 flips
///    [ApiService.accessTerminated] and this non-dismissible gate covers
///    every screen until the student signs out.
class _AuthGate extends StatefulWidget {
  const _AuthGate();

  @override
  State<_AuthGate> createState() => _AuthGateState();
}

class _AuthGateState extends State<_AuthGate> {
  Timer? _bootWarmupTimer;
  bool _bootWarmupVisible = false;
  bool _notificationBridgeAttached = false;
  String? _lastSyncedToken;

  void _syncNativeCredentials(AuthProvider auth) {
    if (auth.isLoggedIn && auth.token != _lastSyncedToken) {
      _lastSyncedToken = auth.token;
      PermissionService.saveNativeCredentials(
        apiUrl: ApiService.baseUrl,
        token: auth.token,
        userId: auth.profile?.id ?? '',
      );
    } else if (!auth.isLoggedIn && _lastSyncedToken != null) {
      _lastSyncedToken = null;
      PermissionService.stopBackgroundService();
    }
  }

  @override
  void initState() {
    super.initState();
    _bootWarmupTimer = Timer(const Duration(seconds: 3), () {
      if (!mounted) return;
      final auth = context.read<AuthProvider>();
      if (auth.isRestoring) setState(() => _bootWarmupVisible = true);
    });
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_notificationBridgeAttached) return;
    _notificationBridgeAttached = true;
    // Bell pump: starts polling /notifications/ on sign-in, stops on logout.
    NotificationService.instance.bindAuth(context.read<AuthProvider>());
  }

  @override
  void dispose() {
    NotificationService.instance.stop();
    _bootWarmupTimer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthProvider>();
    _syncNativeCredentials(auth);

    return ValueListenableBuilder<bool>(
      valueListenable: ApiService.accessTerminated,
      builder: (context, terminated, _) {
        if (terminated) return const _AccessTerminatedGate();

        if (auth.isRestoring) {
          return _bootWarmupVisible
              ? const _BootWarmupCard()
              : const Scaffold(
                  backgroundColor: AppColors.background,
                  body: Center(
                    child:
                        CircularProgressIndicator(color: AppColors.royalBlue),
                  ),
                );
        }

        if (!auth.isLoggedIn) return const AuthScreen();
        return const MainNavigationShell();
      },
    );
  }
}

/// Full-screen takeover for blocked accounts. Not dismissible (covers every
/// tab, no back navigation); the only way out is signing out or exiting.
/// Full-screen takeover for blocked accounts. Not dismissible (covers every
/// tab, no back navigation); the only way out is signing out or exiting.
class _AccessTerminatedGate extends StatelessWidget {
  const _AccessTerminatedGate();

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      child: Scaffold(
        backgroundColor: AppColors.background,
        body: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: 32),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Container(
                    width: 72,
                    height: 72,
                    decoration: BoxDecoration(
                      color: AppColors.danger.withOpacity(0.12),
                      shape: BoxShape.circle,
                    ),
                    child: const Icon(
                      Icons.gpp_bad_outlined,
                      size: 40,
                      color: AppColors.danger,
                    ),
                  ),
                  const SizedBox(height: 24),
                  const Text(
                    'Access Terminated',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontFamily: 'Georgia',
                      color: AppColors.inkBlack,
                      fontSize: 24,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 12),
                  const Text(
                    'Your access has been terminated by Administration. '
                    'For assistance or appeals, contact martaicampus@gmail.com.',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      color: AppColors.textMuted,
                      fontSize: 14.5,
                      height: 1.5,
                    ),
                  ),
                  const SizedBox(height: 20),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                    decoration: BoxDecoration(
                      color: AppColors.surface,
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: AppColors.hairline),
                    ),
                    child: const Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(Icons.mail_outline, size: 18, color: AppColors.royalBlue),
                        SizedBox(width: 8),
                        SelectableText(
                          'martaicampus@gmail.com',
                          style: TextStyle(
                            color: AppColors.royalBlue,
                            fontSize: 13.5,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 28),
                  FilledButton(
                    onPressed: () => context.read<AuthProvider>().logout(),
                    child: const Text('Exit & Sign Out'),
                  ),
                  const SizedBox(height: 10),
                  TextButton(
                    onPressed: () => SystemNavigator.pop(),
                    child: const Text(
                      'Close Application',
                      style: TextStyle(
                        color: AppColors.textMuted,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// Cold-boot card (>3s restore) - animated brand mark + honest phase steps.
class _BootWarmupCard extends StatelessWidget {
  const _BootWarmupCard();

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      backgroundColor: AppColors.background,
      body: Center(
        child: Padding(
          padding: EdgeInsets.symmetric(horizontal: 36),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              AnimatedBrandLogo(size: 108),
              SizedBox(height: 26),
              Text(
                'Connecting to Campus Mart Ai Marketplace',
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontFamily: 'Georgia',
                  color: AppColors.inkBlack,
                  fontSize: 17,
                  fontWeight: FontWeight.w700,
                ),
              ),
              SizedBox(height: 8),
              Text(
                'Hang tight! Waking up our cloud AI server (takes ~30-60 '
                'seconds on first launch)...',
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: AppColors.textMuted,
                  fontSize: 13,
                  height: 1.5,
                ),
              ),
              SizedBox(height: 18),
              WarmupStepIndicator(),
            ],
          ),
        ),
      ),
    );
  }
}

/// Five-tab navigation shell (Task 5):
///  0. Discovery Feed
///  1. Sell / Create Listing
///  2. Ask CampusMart AI
///  3. Messages (buyer-seller chat)
///  4. Profile & Campus Trust
class MainNavigationShell extends StatefulWidget {
  const MainNavigationShell({super.key});

  @override
  State<MainNavigationShell> createState() => _MainNavigationShellState();
}

class _MainNavigationShellState extends State<MainNavigationShell> {
  int _index = 0;

  /// Immersive browsing: while the student scrolls DOWN through the feed the
  /// bottom nav slides off-screen (driven by FeedScreen), and it comes right
  /// back on scroll-up or on any tab change.
  bool _chromeVisible = true;

  /// Screens are built once so every tab keeps its own state while hidden
  /// (IndexedStack keeps offstage children alive).
  late final List<Widget> _screens;

  @override
  void initState() {
    super.initState();
    _screens = <Widget>[
      FeedScreen(onChromeVisibilityChanged: _setChromeVisible),
      // After a successful listing the shell jumps back to the feed tab.
      CreateListingScreen(onListingCreated: _showFeedTab),
      const AiAssistantScreen(),
      const MessagesScreen(),
      const ProfileScreen(),
    ];
  }

  void _showFeedTab() => setState(() {
        _index = 0;
        _chromeVisible = true;
      });

  void _setChromeVisible(bool visible) {
    if (!mounted || _chromeVisible == visible) return;
    setState(() => _chromeVisible = visible);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(
        index: _index,
        children: _screens,
      ),
      bottomNavigationBar: AnimatedSlide(
        offset: _chromeVisible ? Offset.zero : const Offset(0, 1),
        duration: const Duration(milliseconds: 220),
        curve: Curves.easeOutCubic,
        child: BottomNavigationBar(
          currentIndex: _index,
          onTap: (index) => setState(() {
            _index = index;
            _chromeVisible = true;
          }),
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
              icon: Icon(Icons.auto_awesome_outlined),
              activeIcon: Icon(Icons.auto_awesome),
              label: 'Ask AI',
            ),
            BottomNavigationBarItem(
              icon: Icon(Icons.chat_bubble_outline),
              activeIcon: Icon(Icons.chat_bubble),
              label: 'Messages',
            ),
            BottomNavigationBarItem(
              icon: Icon(Icons.person_outline),
              activeIcon: Icon(Icons.person),
              label: 'Profile',
            ),
          ],
        ),
      ),
    );
  }
}
