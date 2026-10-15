import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/product.dart';
import '../providers/auth_provider.dart';
import '../providers/product_provider.dart';
import '../services/api_service.dart';
import '../widgets/app_theme.dart';
import '../widgets/category_icon.dart';
import '../widgets/trust_score_meter.dart';
import 'product_detail_screen.dart';

/// Tab 3 - Profile & Campus Trust (Phase 7).
///
/// Shows the real logged-in student's identity, live trust score fetched from
/// the backend, their active listings, session info, and a Log Out button.
class ProfileScreen extends StatelessWidget {
  const ProfileScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthProvider>();
    final feed = context.watch<ProductProvider>();
    final profile = auth.profile;

    // My active listings: filter the live feed by my seller id (works without
    // a dedicated backend endpoint; sold/flagged never appear in the feed).
    final myUid = profile?.id ?? '';
    final myListings = feed.products
        .where((product) => product.sellerId == myUid)
        .toList();

    return Scaffold(
      appBar: AppBar(
        titleSpacing: 16,
        title: const Text(
          'Profile & Campus Trust',
          style: TextStyle(
            fontSize: 17,
            fontWeight: FontWeight.w800,
            color: AppColors.textPrimary,
          ),
        ),
      ),
      body: RefreshIndicator(
        color: AppColors.cyanAccent,
        backgroundColor: AppColors.surface,
        onRefresh: () async {
          await auth.refreshProfile();
          await feed.loadProducts();
        },
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
          children: [
            if (auth.isLoading && profile == null) ...[
              const SizedBox(height: 120),
              const Center(
                child: CircularProgressIndicator(
                  color: AppColors.cyanAccent,
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
              const SizedBox(height: 16),
              _TrustCard(score: profile.trustScore),
              const SizedBox(height: 16),
              _MyListingsSection(listings: myListings),
              const SizedBox(height: 16),
              _SessionCard(
                errorMessage: auth.errorMessage,
                onRetry: auth.refreshProfile,
                onLogout: () => _confirmLogout(context, auth),
              ),
            ],
          ],
        ),
      ),
    );
  }

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
            child: Icon(
              Icons.person_outline,
              color: isBlocked ? AppColors.danger : AppColors.cyanAccent,
              size: 30,
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
                    color: (isBlocked ? AppColors.danger : AppColors.cyanAccent)
                        .withOpacity(0.12),
                    borderRadius: BorderRadius.circular(999),
                    border: Border.all(
                      color: (isBlocked
                              ? AppColors.danger
                              : AppColors.cyanAccent)
                          .withOpacity(0.5),
                    ),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        isBlocked ? Icons.block : Icons.verified,
                        size: 12,
                        color:
                            isBlocked ? AppColors.danger : AppColors.cyanAccent,
                      ),
                      const SizedBox(width: 4),
                      Text(
                        isBlocked ? 'Account Blocked' : 'Verified Student',
                        style: TextStyle(
                          color: isBlocked
                              ? AppColors.danger
                              : AppColors.cyanAccent,
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

class _TrustCard extends StatelessWidget {
  const _TrustCard({required this.score});

  final double score;

  @override
  Widget build(BuildContext context) {
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
          const Text(
            'CAMPUS TRUST SCORE',
            style: TextStyle(
              color: AppColors.textMuted,
              fontSize: 10.5,
              fontWeight: FontWeight.w700,
              letterSpacing: 1.1,
            ),
          ),
          const SizedBox(height: 12),
          TrustScoreMeter(score: score, label: 'Current score'),
          const SizedBox(height: 12),
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

/// Grid of the student's own active listings, pulled from the live feed.
class _MyListingsSection extends StatelessWidget {
  const _MyListingsSection({required this.listings});

  final List<Product> listings;

  @override
  Widget build(BuildContext context) {
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
              const Icon(
                Icons.storefront_outlined,
                size: 16,
                color: AppColors.cyanAccent,
              ),
              const SizedBox(width: 8),
              Text(
                'MY ACTIVE LISTINGS (${listings.length})',
                style: const TextStyle(
                  color: AppColors.textMuted,
                  fontSize: 10.5,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 1.1,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          if (listings.isEmpty)
            const Text(
              'No active listings yet. Head to the Sell tab to post your '
              'first item!',
              style: TextStyle(
                color: AppColors.textMuted,
                fontSize: 13,
                height: 1.4,
              ),
            )
          else
            ...listings.map(
              (product) => Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: _ListingTile(product: product),
              ),
            ),
        ],
      ),
    );
  }
}

class _ListingTile extends StatelessWidget {
  const _ListingTile({required this.product});

  final Product product;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      borderRadius: BorderRadius.circular(12),
      onTap: () => Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => ProductDetailScreen(product: product),
        ),
      ),
      child: Container(
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: AppColors.surfaceHigh,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: AppColors.hairline),
        ),
        child: Row(
          children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(10),
              child: SizedBox(
                width: 52,
                height: 52,
                child: product.imageUrl.isEmpty
                    ? ImageFallbackIcon(category: product.category, size: 24)
                    : Image.network(
                        product.imageUrl,
                        fit: BoxFit.cover,
                        errorBuilder: (_, __, ___) => ImageFallbackIcon(
                          category: product.category,
                          size: 24,
                        ),
                      ),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    product.title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: AppColors.textPrimary,
                      fontSize: 13.5,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '\$${product.listedPrice.toStringAsFixed(2)} · '
                    '${product.condition}',
                    style: const TextStyle(
                      color: AppColors.textMuted,
                      fontSize: 12,
                    ),
                  ),
                ],
              ),
            ),
            const Icon(
              Icons.chevron_right,
              size: 20,
              color: AppColors.textMuted,
            ),
          ],
        ),
      ),
    );
  }
}

/// Session card: API endpoint + auth mode + Log Out.
class _SessionCard extends StatelessWidget {
  const _SessionCard({this.errorMessage, this.onRetry, this.onLogout});

  final String? errorMessage;
  final Future<void> Function()? onRetry;
  final VoidCallback? onLogout;

  @override
  Widget build(BuildContext context) {
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
          const Text(
            'SESSION & API',
            style: TextStyle(
              color: AppColors.textMuted,
              fontSize: 10.5,
              fontWeight: FontWeight.w700,
              letterSpacing: 1.1,
            ),
          ),
          const SizedBox(height: 12),
          const _InfoRow(
            icon: Icons.dns_outlined,
            label: 'API endpoint',
            value: '', // filled below via ApiService.baseUrl
          ),
          const SizedBox(height: 8),
          const _InfoRow(
            icon: Icons.verified_user_outlined,
            label: 'Auth mode',
            value: 'Campus email / JWT (live)',
          ),
          if (errorMessage != null) ...[
            const SizedBox(height: 12),
            Text(
              errorMessage!,
              style: const TextStyle(
                color: AppColors.warning,
                fontSize: 12.5,
                height: 1.4,
              ),
            ),
            const SizedBox(height: 10),
            FilledButton.tonalIcon(
              icon: const Icon(Icons.refresh, size: 18),
              label: const Text('Retry connection'),
              onPressed: onRetry,
            ),
          ],
          const SizedBox(height: 16),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              icon: const Icon(Icons.logout, size: 18),
              label: const Text('Log Out'),
              onPressed: onLogout,
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
      ),
    );
  }
}

class _InfoRow extends StatelessWidget {
  const _InfoRow({
    required this.icon,
    required this.label,
    required this.value,
  });

  final IconData icon;
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    // Resolve the live base URL at build time (static getter).
    final resolved =
        value.isEmpty && label == 'API endpoint' ? ApiService.baseUrl : value;
    return Row(
      children: [
        Icon(icon, size: 16, color: AppColors.cyanAccent),
        const SizedBox(width: 8),
        Text(
          '$label: ',
          style: const TextStyle(
            color: AppColors.textMuted,
            fontSize: 12.5,
            fontWeight: FontWeight.w600,
          ),
        ),
        Expanded(
          child: Text(
            resolved,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              color: AppColors.textPrimary,
              fontSize: 12.5,
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
      ],
    );
  }
}
