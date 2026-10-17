import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/college.dart';
import '../providers/auth_provider.dart';
import '../providers/cart_provider.dart';
import '../providers/wishlist_provider.dart';
import '../widgets/app_theme.dart';
import '../widgets/college_picker_sheet.dart';
import '../widgets/trust_score_meter.dart';
import 'cart_screen.dart';
import 'my_listings_screen.dart';
import 'orders_screen.dart';
import 'saved_listings_screen.dart';

/// Tab 3 - Profile & Campus Trust.
///
/// Shows the real logged-in student's identity, the live trust score on the
/// API's 0-5.0 scale with a dynamic tier badge, a Log Out action, and a
/// 4-tile action grid (Part B Task 7):
///   * **My Listings** - active + sold posts with Delete (own screen).
///   * **My Orders** - buys + sales with order status and Message actions.
///   * **My Cart** - parked listings with a live count badge.
///   * **Saved** - wishlist hearts persisted by WishlistProvider.
class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {

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

  /// Profile-tab college editor: swap the campus network via the CET sheet.
  Future<void> _editCollege() async {
    final auth = context.read<AuthProvider>();
    final profile = auth.profile;
    final hasCollege =
        profile != null && (profile.collegeName ?? '').trim().isNotEmpty;
    final picked = await showCollegePickerSheet(
      context,
      initial: hasCollege
          ? College(
              code: profile.collegeCode ?? '',
              name: profile.collegeName!,
              shortName: '',
              city: '',
            )
          : null,
      title: 'Your campus network',
    );
    if (picked == null || !mounted) return;
    final ok = await auth.updateCollege(
      collegeName: picked.name,
      collegeCode: picked.code,
    );
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        backgroundColor:
            (ok ? AppColors.success : AppColors.danger).withOpacity(0.92),
        content: Text(
          ok
              ? 'Campus network updated - new listings will carry ${picked.name}.'
              : (auth.errorMessage ?? 'Could not update your college.'),
          style: const TextStyle(
            color: Colors.black,
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthProvider>();
    final profile = auth.profile;

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
      ),
      body: RefreshIndicator(
        color: AppColors.royalBlue,
        backgroundColor: AppColors.surface,
        onRefresh: () async {
          final cart = context.read<CartProvider>();
          await auth.refreshProfile();
          await cart.load();
        },
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.fromLTRB(16, 20, 16, 36),
          children: [
            if (auth.isLoading && profile == null) ...[
              const SizedBox(height: 120),
              const Center(
                child: CircularProgressIndicator(
                  color: AppColors.royalBlue,
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
              const SizedBox(height: 12),
              _CollegeNetworkCard(
                collegeName: profile.collegeName,
                collegeCode: profile.collegeCode,
                onEdit: _editCollege,
              ),
              const SizedBox(height: 16),
              _TrustCard(score: profile.trustScore),
              const SizedBox(height: 16),
              const _ProfileActionTiles(),
              const SizedBox(height: 20),
              const _HelpAndSupportCard(),
              const SizedBox(height: 20),
              const _AboutCard(),
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
                color: isBlocked ? AppColors.danger : AppColors.royalBlue,
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
                    color: (isBlocked ? AppColors.danger : AppColors.royalBlue)
                        .withOpacity(0.12),
                    borderRadius: BorderRadius.circular(999),
                    border: Border.all(
                      color: (isBlocked
                              ? AppColors.danger
                              : AppColors.royalBlue)
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
                            isBlocked ? AppColors.danger : AppColors.royalBlue,
                      ),
                      const SizedBox(width: 4),
                      Text(
                        isBlocked ? 'Account Blocked' : 'Campus Student',
                        style: TextStyle(
                          color: isBlocked
                              ? AppColors.danger
                              : AppColors.royalBlue,
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

/// College-network card (Task 3): shows the student's CET college + code and
/// opens the picker sheet to swap campuses (their next listings inherit it).
class _CollegeNetworkCard extends StatelessWidget {
  const _CollegeNetworkCard({
    required this.collegeName,
    required this.collegeCode,
    required this.onEdit,
  });

  final String? collegeName;
  final String? collegeCode;
  final VoidCallback onEdit;

  @override
  Widget build(BuildContext context) {
    final name = (collegeName ?? '').trim();
    final code = (collegeCode ?? '').trim();
    final linked = name.isNotEmpty;

    return Container(
      padding: const EdgeInsets.fromLTRB(16, 14, 12, 14),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(
          color: linked
              ? AppColors.royalBlue.withOpacity(0.35)
              : AppColors.hairline,
        ),
      ),
      child: Row(
        children: [
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              color: AppColors.royalBlue.withOpacity(0.1),
              shape: BoxShape.circle,
            ),
            child: const Icon(
              Icons.school_outlined,
              size: 20,
              color: AppColors.royalBlue,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'CAMPUS NETWORK',
                  style: TextStyle(
                    color: AppColors.textMuted,
                    fontSize: 10,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 1.1,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  linked ? name : 'Not linked to a college yet',
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    color: linked
                        ? AppColors.textPrimary
                        : AppColors.textMuted,
                    fontSize: 13.5,
                    fontWeight: FontWeight.w700,
                    height: 1.25,
                  ),
                ),
                if (linked) ...[
                  const SizedBox(height: 3),
                  Text(
                    [
                      if (code.isNotEmpty) 'CET $code',
                      'You get alerts when students at your college post.',
                    ].join(' Â· '),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: AppColors.textMuted,
                      fontSize: 11,
                      height: 1.3,
                    ),
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(width: 8),
          TextButton(
            onPressed: onEdit,
            style: TextButton.styleFrom(
              foregroundColor: AppColors.royalBlue,
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            ),
            child: Text(
              linked ? 'Change' : 'Set',
              style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800),
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

/// 4-tile action grid (Part B Task 7): My Listings / My Orders / My Cart /
/// Saved - each opens its own screen, so the profile stays a trust summary
/// while activity lives where it has room to breathe.
class _ProfileActionTiles extends StatelessWidget {
  const _ProfileActionTiles();

  @override
  Widget build(BuildContext context) {
    final cartCount = context.watch<CartProvider>().count;
    final savedCount = context.watch<WishlistProvider>().count;

    return GridView.count(
      crossAxisCount: 2,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      mainAxisSpacing: 12,
      crossAxisSpacing: 12,
      childAspectRatio: 1.62,
      children: [
        _ProfileActionTile(
          icon: Icons.storefront_outlined,
          label: 'My Listings',
          caption: 'Manage your posts',
          tint: AppColors.royalBlue,
          onTap: () => Navigator.of(context).push(
            MaterialPageRoute<void>(builder: (_) => const MyListingsScreen()),
          ),
        ),
        _ProfileActionTile(
          icon: Icons.receipt_long_outlined,
          label: 'My Orders',
          caption: 'Purchases & sales',
          tint: AppColors.success,
          onTap: () => Navigator.of(context).push(
            MaterialPageRoute<void>(builder: (_) => const OrdersScreen()),
          ),
        ),
        _ProfileActionTile(
          icon: Icons.shopping_cart_outlined,
          label: 'My Cart',
          caption:
              cartCount == 0 ? 'Nothing parked yet' : '$cartCount waiting',
          tint: AppColors.warning,
          badge: cartCount,
          onTap: () => Navigator.of(context).push(
            MaterialPageRoute<void>(builder: (_) => const CartScreen()),
          ),
        ),
        _ProfileActionTile(
          icon: Icons.favorite_border,
          label: 'Saved',
          caption: savedCount == 0 ? 'Heart items to save' : '$savedCount saved',
          tint: AppColors.danger,
          badge: savedCount,
          onTap: () => Navigator.of(context).push(
            MaterialPageRoute<void>(
              builder: (_) => const SavedListingsScreen(),
            ),
          ),
        ),
      ],
    );
  }
}

/// One tile in the 4-tile action grid.
class _ProfileActionTile extends StatelessWidget {
  const _ProfileActionTile({
    required this.icon,
    required this.label,
    required this.caption,
    required this.tint,
    required this.onTap,
    this.badge = 0,
  });

  final IconData icon;
  final String label;
  final String caption;
  final Color tint;
  final VoidCallback onTap;
  final int badge;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: AppColors.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: const BorderSide(color: AppColors.hairline),
      ),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(14, 12, 12, 12),
          child: Row(
            children: [
              Stack(
                clipBehavior: Clip.none,
                children: [
                  Container(
                    width: 38,
                    height: 38,
                    decoration: BoxDecoration(
                      color: tint.withOpacity(0.12),
                      borderRadius: BorderRadius.circular(11),
                    ),
                    child: Icon(icon, size: 20, color: tint),
                  ),
                  if (badge > 0)
                    Positioned(
                      right: -5,
                      top: -5,
                      child: Container(
                        constraints: const BoxConstraints(minWidth: 17),
                        height: 17,
                        padding: const EdgeInsets.symmetric(horizontal: 4),
                        decoration: BoxDecoration(
                          color: AppColors.danger,
                          borderRadius: BorderRadius.circular(999),
                          border: Border.all(
                            color: AppColors.surface,
                            width: 1.5,
                          ),
                        ),
                        child: Center(
                          child: Text(
                            badge > 9 ? '9+' : '$badge',
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
                ],
              ),
              const SizedBox(width: 11),
              Expanded(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      label,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: AppColors.textPrimary,
                        fontSize: 13,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      caption,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: AppColors.textMuted,
                        fontSize: 10.5,
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
          const _SupportEmailRow(
            icon: Icons.email_outlined,
            label: 'Support Email:',
            email: 'martaicampus@gmail.com',
            emphasized: true,
          ),
          const SizedBox(height: 4),
          const _SupportEmailRow(
            icon: Icons.alternate_email,
            label: 'General Desk:',
            email: 'support@campusmart.in',
            emphasized: false,
          ),
        ],
      ),
    );
  }
}

/// One support email row: tapping launches the mail client directly
/// (external mailto intent); the copy icon is the secondary fallback that
/// copies the address when no mail app handles the intent (Part B Task 8).
class _SupportEmailRow extends StatelessWidget {
  const _SupportEmailRow({
    required this.icon,
    required this.label,
    required this.email,
    required this.emphasized,
  });

  final IconData icon;
  final String label;
  final String email;
  final bool emphasized;

  Future<void> _launchMail(BuildContext context) async {
    final uri = Uri(
      scheme: 'mailto',
      path: email,
      queryParameters: const {'subject': 'CampusMart Support Inquiry'},
    );
    try {
      final launched =
          await launchUrl(uri, mode: LaunchMode.externalApplication);
      if (launched) return;
    } catch (_) {
      // Fall through to the clipboard fallback below.
    }
    if (!context.mounted) return;
    await _copy(context);
  }

  Future<void> _copy(BuildContext context) async {
    await Clipboard.setData(ClipboardData(text: email));
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        duration: const Duration(seconds: 2),
        content: Text('Support email copied: $email'),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final color = emphasized ? AppColors.royalBlue : AppColors.textMuted;
    return InkWell(
      borderRadius: BorderRadius.circular(10),
      onTap: () => _launchMail(context),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 4),
        child: Row(
          children: [
            Icon(icon, size: 16, color: color),
            const SizedBox(width: 10),
            Text(
              label,
              style: const TextStyle(
                color: AppColors.textPrimary,
                fontSize: 13,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(width: 6),
            Expanded(
              child: Text(
                email,
                style: TextStyle(
                  color: color,
                  fontSize: 13,
                  fontWeight:
                      emphasized ? FontWeight.w700 : FontWeight.w600,
                ),
              ),
            ),
            Tooltip(
              message: 'Copy email',
              child: InkWell(
                customBorder: const CircleBorder(),
                onTap: () => _copy(context),
                child: Padding(
                  padding: const EdgeInsets.all(4),
                  child: Icon(Icons.copy, size: 15, color: color),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// About card (Part B Task 8): official website link + platform identity.
class _AboutCard extends StatelessWidget {
  const _AboutCard();

  static const String _websiteUrl = 'https://campus-mart-ivory.vercel.app';

  Future<void> _openWebsite(BuildContext context) async {
    final uri = Uri.parse(_websiteUrl);
    try {
      final launched =
          await launchUrl(uri, mode: LaunchMode.externalApplication);
      if (launched) return;
    } catch (_) {
      // Fall through to the clipboard fallback below.
    }
    await Clipboard.setData(const ClipboardData(text: _websiteUrl));
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        duration: Duration(seconds: 2),
        content: Text('Website link copied: $_websiteUrl'),
      ),
    );
  }

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
                  color: AppColors.inkBlack.withOpacity(0.82),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: const Icon(
                  Icons.info_outline,
                  size: 20,
                  color: Colors.white,
                ),
              ),
              const SizedBox(width: 12),
              const Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'About CampusMart Ai',
                      style: TextStyle(
                        fontFamily: 'Georgia',
                        color: AppColors.inkBlack,
                        fontSize: 15,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    SizedBox(height: 2),
                    Text(
                      'Campus commerce, reimagined with AI',
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
            onTap: () => _openWebsite(context),
            child: const Padding(
              padding: EdgeInsets.symmetric(vertical: 6, horizontal: 4),
              child: Row(
                children: [
                  Icon(
                    Icons.public,
                    size: 16,
                    color: AppColors.royalBlue,
                  ),
                  SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      'Visit Official Website',
                      style: TextStyle(
                        color: AppColors.royalBlue,
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                  Icon(
                    Icons.open_in_new,
                    size: 15,
                    color: AppColors.royalBlue,
                  ),
                ],
              ),
            ),
          ),
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 6, horizontal: 4),
            child: Row(
              children: [
                Icon(
                  Icons.account_balance_outlined,
                  size: 16,
                  color: AppColors.textMuted,
                ),
                SizedBox(width: 10),
                Text(
                  'CET Cell Campus Network',
                  style: TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
          ),
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 6, horizontal: 4),
            child: Row(
              children: [
                Icon(
                  Icons.verified_outlined,
                  size: 16,
                  color: AppColors.success,
                ),
                SizedBox(width: 10),
                Expanded(
                  child: Text(
                    'v2.5.0 Production · Verified OTP & Vision AI',
                    style: TextStyle(
                      color: AppColors.textMuted,
                      fontSize: 12.5,
                      fontWeight: FontWeight.w600,
                    ),
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

