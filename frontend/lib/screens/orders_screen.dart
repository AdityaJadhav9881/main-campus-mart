import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/auth_provider.dart';
import '../services/api_service.dart';
import '../services/currency.dart';
import '../widgets/app_theme.dart';
import 'chat_thread_screen.dart';

/// My Orders (Part B Task 7): buys + sales from GET /transactions/my with the
/// structured checkout context (order status, payment method, meetup info)
/// and a Message Seller / Message Buyer action per order.
class OrdersScreen extends StatefulWidget {
  const OrdersScreen({super.key});

  @override
  State<OrdersScreen> createState() => _OrdersScreenState();
}

class _OrdersScreenState extends State<OrdersScreen> {
  final ApiService _api = ApiService.instance;

  TransactionHistory? _history;
  bool _loading = true;
  String? _error;
  String? _openingChatFor;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _reload();
    });
  }

  Future<void> _reload() async {
    final auth = context.read<AuthProvider>();
    if (auth.token.isEmpty) return;
    setState(() {
      _loading = _history == null;
      _error = null;
    });
    try {
      final history = await _api.fetchMyTransactions(token: auth.token);
      if (!mounted) return;
      setState(() {
        _history = history;
        _loading = false;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _error = error.message;
        _loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _error = 'Could not load your orders right now.';
        _loading = false;
      });
    }
  }

  /// Bought orders: resolve the listing to learn the seller's user id
  /// (transactions only carry names), then open the chat thread.
  Future<void> _messageSeller(TransactionRecord record) async {
    if (_openingChatFor != null) return;
    setState(() => _openingChatFor = record.id);
    final messenger = ScaffoldMessenger.of(context);
    try {
      final product = await _api.fetchProductById(record.productId);
      if (!mounted) return;
      if (product == null || product.sellerId.isEmpty) {
        messenger.showSnackBar(
          const SnackBar(
            content: Text('That listing is no longer available to chat on.'),
          ),
        );
        return;
      }
      Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => ChatThreadScreen(
            productId: record.productId,
            productTitle: record.productTitle ?? product.title,
            productImageUrl:
                record.productImageUrl ?? product.imageUrl,
            productPrice: record.finalPrice,
            otherUserId: product.sellerId,
            otherUserName: product.sellerName ??
                record.sellerName ??
                'Campus Seller',
          ),
        ),
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      messenger.showSnackBar(SnackBar(content: Text(error.message)));
    } catch (_) {
      if (!mounted) return;
      messenger.showSnackBar(
        const SnackBar(content: Text('Could not open the chat thread.')),
      );
    } finally {
      if (mounted) setState(() => _openingChatFor = null);
    }
  }

  void _messageBuyer(TransactionRecord record) {
    if (record.buyerId.isEmpty) return;
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => ChatThreadScreen(
          productId: record.productId,
          productTitle: record.productTitle ?? 'Listing',
          productImageUrl: record.productImageUrl,
          productPrice: record.finalPrice,
          otherUserId: record.buyerId,
          otherUserName: record.buyerName ?? 'Campus Buyer',
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final bought = _history?.bought ?? const <TransactionRecord>[];
    final sold = _history?.sold ?? const <TransactionRecord>[];

    return DefaultTabController(
      length: 2,
      child: Scaffold(
        backgroundColor: AppColors.background,
        appBar: AppBar(
          titleSpacing: 16,
          title: const Text(
            'My Orders',
            style: TextStyle(
              fontFamily: 'Georgia',
              fontSize: 20,
              fontWeight: FontWeight.w700,
              color: AppColors.inkBlack,
            ),
          ),
          bottom: TabBar(
            labelColor: AppColors.royalBlue,
            unselectedLabelColor: AppColors.textMuted,
            indicatorColor: AppColors.royalBlue,
            indicatorWeight: 2.5,
            labelStyle:
                const TextStyle(fontSize: 13, fontWeight: FontWeight.w800),
            unselectedLabelStyle:
                const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
            tabs: [
              Tab(text: 'Purchases (${bought.length})'),
              Tab(text: 'Sales (${sold.length})'),
            ],
          ),
        ),
        body: _buildBody(bought, sold),
      ),
    );
  }

  Widget _buildBody(
    List<TransactionRecord> bought,
    List<TransactionRecord> sold,
  ) {
    if (_loading) {
      return const Center(
        child: CircularProgressIndicator(color: AppColors.royalBlue),
      );
    }
    if (_error != null && _history == null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(28),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.receipt_long_outlined,
                  size: 42, color: AppColors.textMuted),
              const SizedBox(height: 12),
              Text(
                _error!,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  color: AppColors.textMuted,
                  fontSize: 13,
                  height: 1.45,
                ),
              ),
              const SizedBox(height: 12),
              FilledButton.tonal(
                onPressed: _reload,
                child: const Text('Retry'),
              ),
            ],
          ),
        ),
      );
    }
    return TabBarView(
      children: [
        _buildList(
          records: bought,
          caption: 'Purchases appear here with the seller\'s meetup details.',
          emptyIcon: Icons.shopping_bag_outlined,
          emptyMessage:
              'Nothing purchased yet.\nYour buys and their OTP receipts show up here.',
          builtForSale: false,
        ),
        _buildList(
          records: sold,
          caption: 'Your sold items with the buyer\'s delivery details.',
          emptyIcon: Icons.storefront_outlined,
          emptyMessage:
              'No sales yet.\nWhen someone buys your listing, the order lands here.',
          builtForSale: true,
        ),
      ],
    );
  }

  Widget _buildList({
    required List<TransactionRecord> records,
    required String caption,
    required IconData emptyIcon,
    required String emptyMessage,
    required bool builtForSale,
  }) {
    if (records.isEmpty) {
      return ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        children: [
          const SizedBox(height: 110),
          Icon(emptyIcon, size: 42, color: AppColors.textMuted),
          const SizedBox(height: 12),
          Text(
            emptyMessage,
            textAlign: TextAlign.center,
            style: const TextStyle(
              color: AppColors.textMuted,
              fontSize: 13,
              height: 1.5,
            ),
          ),
        ],
      );
    }
    return RefreshIndicator(
      color: AppColors.royalBlue,
      backgroundColor: AppColors.surface,
      onRefresh: _reload,
      child: ListView.separated(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 28),
        itemCount: records.length + 1,
        separatorBuilder: (_, __) => const SizedBox(height: 10),
        itemBuilder: (context, index) {
          if (index == 0) {
            return Padding(
              padding: const EdgeInsets.only(bottom: 2),
              child: Text(
                caption,
                style: const TextStyle(
                  color: AppColors.textMuted,
                  fontSize: 11.5,
                ),
              ),
            );
          }
          final record = records[index - 1];
          return _OrderCard(
            record: record,
            builtForSale: builtForSale,
            busy: _openingChatFor == record.id,
            onMessage: builtForSale
                ? () => _messageBuyer(record)
                : () => _messageSeller(record),
          );
        },
      ),
    );
  }
}

/// One order with status / payment / meetup context and a message action.
class _OrderCard extends StatelessWidget {
  const _OrderCard({
    required this.record,
    required this.builtForSale,
    required this.busy,
    required this.onMessage,
  });

  final TransactionRecord record;
  final bool builtForSale;
  final bool busy;
  final VoidCallback onMessage;

  Color _statusColor() {
    final status = (record.orderStatus ?? record.status).toLowerCase();
    if (status.contains('cancel')) return AppColors.danger;
    if (status.contains('complete') || status == 'paid') {
      return AppColors.success;
    }
    return AppColors.warning;
  }

  @override
  Widget build(BuildContext context) {
    final counterpartName =
        builtForSale ? record.buyerName : record.sellerName;
    final payment = record.paymentMethod ?? '';
    final landmark = record.hostelOrLandmark ?? record.deliveryAddress ?? '';
    final date = record.timestamp.toLocal().toString().split(' ').first;

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.hairline),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(10),
                child: SizedBox(
                  width: 54,
                  height: 54,
                  child: (record.productImageUrl ?? '').isEmpty
                      ? const ColoredBox(color: AppColors.surfaceHigh)
                      : Image.network(
                          record.productImageUrl!,
                          fit: BoxFit.cover,
                          errorBuilder: (context, error, stack) =>
                              const ColoredBox(color: AppColors.surfaceHigh),
                        ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      record.productTitle ?? 'Listing',
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: AppColors.textPrimary,
                        fontSize: 13.5,
                        fontWeight: FontWeight.w700,
                        height: 1.25,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '${formatInr(record.finalPrice)} · $date',
                      style: const TextStyle(
                        color: AppColors.textMuted,
                        fontSize: 11.5,
                      ),
                    ),
                  ],
                ),
              ),
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: _statusColor().withOpacity(0.14),
                  borderRadius: BorderRadius.circular(999),
                ),
                child: Text(
                  record.orderStatus ?? record.status,
                  style: TextStyle(
                    color: _statusColor(),
                    fontSize: 10,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 6,
            children: [
              if (payment.isNotEmpty)
                _InfoChip(
                  icon: payment.toLowerCase().contains('cash')
                      ? Icons.payments_outlined
                      : Icons.qr_code_2_outlined,
                  label: payment,
                ),
              if (landmark.isNotEmpty)
                _InfoChip(
                  icon: Icons.place_outlined,
                  label: landmark,
                ),
              if (counterpartName != null && counterpartName.isNotEmpty)
                _InfoChip(
                  icon: builtForSale
                      ? Icons.person_outline
                      : Icons.storefront_outlined,
                  label: '${builtForSale ? 'Buyer' : 'Seller'}: '
                      '$counterpartName',
                ),
            ],
          ),
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              onPressed: busy ? null : onMessage,
              icon: busy
                  ? const SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: AppColors.royalBlue,
                      ),
                    )
                  : const Icon(Icons.chat_bubble_outline, size: 16),
              label: Text(
                builtForSale ? 'Message Buyer' : 'Message Seller',
              ),
              style: OutlinedButton.styleFrom(
                foregroundColor: AppColors.royalBlue,
                side: BorderSide(
                  color: AppColors.royalBlue.withOpacity(0.5),
                  width: 1.2,
                ),
                minimumSize: const Size.fromHeight(40),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(11),
                ),
                textStyle: const TextStyle(
                  fontSize: 12.5,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Small tinted pill for payment / meetup / counterpart info.
class _InfoChip extends StatelessWidget {
  const _InfoChip({required this.icon, required this.label});

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
      decoration: BoxDecoration(
        color: AppColors.surfaceHigh,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: AppColors.hairline),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 13, color: AppColors.textMuted),
          const SizedBox(width: 5),
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 210),
            child: Text(
              label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                color: AppColors.textMuted,
                fontSize: 11,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
