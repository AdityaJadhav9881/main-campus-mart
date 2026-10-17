import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/product.dart';
import '../providers/auth_provider.dart';
import '../services/api_service.dart';
import '../services/currency.dart';
import '../widgets/action_otp_sheet.dart';
import '../widgets/app_theme.dart';
import 'chat_thread_screen.dart';

/// Opens the 4-step checkout: meetup details -> payment -> OTP -> success
/// (Part B Task 7). Resolves to the [PurchaseResult] once the order is in,
/// or null if the student backs out before placing it.
Future<PurchaseResult?> showCheckoutSheet(
  BuildContext context, {
  required Product product,
}) {
  return showModalBottomSheet<PurchaseResult>(
    context: context,
    isScrollControlled: true,
    backgroundColor: AppColors.surface,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(22)),
    ),
    builder: (_) => _CheckoutSheet(product: product),
  );
}

class _CheckoutSheet extends StatefulWidget {
  const _CheckoutSheet({required this.product});

  final Product product;

  @override
  State<_CheckoutSheet> createState() => _CheckoutSheetState();
}

class _CheckoutSheetState extends State<_CheckoutSheet> {
  final ApiService _api = ApiService.instance;
  final TextEditingController _address = TextEditingController();
  final TextEditingController _landmark = TextEditingController();
  final TextEditingController _phone = TextEditingController();
  final TextEditingController _notes = TextEditingController();
  final TextEditingController _upiRef = TextEditingController();

  /// 0 = meetup details, 1 = payment, 2 = review + place, 3 = success.
  int _step = 0;

  String _paymentMethod = 'Cash on Meetup';
  String? _detailsError;
  String? _placeError;
  bool _placing = false;
  PurchaseResult? _result;

  @override
  void dispose() {
    _address.dispose();
    _landmark.dispose();
    _phone.dispose();
    _notes.dispose();
    _upiRef.dispose();
    super.dispose();
  }

  // ---------------------------------------------------------------------------
  // Payment
  // ---------------------------------------------------------------------------
  Future<void> _openUpiApp() async {
    final amount = widget.product.listedPrice.toStringAsFixed(2);
    final title = Uri.encodeComponent(widget.product.title);
    // tez:// targets GPay directly; upi:// is the generic fallback every
    // UPI app registers. The payee VPA must be confirmed with the seller in
    // chat - the sheet shows that note above the button.
    final gpay = Uri.parse(
      'tez://upi/pay?pa=campusmart.ai@upi&pn=CampusMart%20Seller'
      '&am=$amount&cu=INR&tn=$title',
    );
    final generic = Uri.parse(
      'upi://pay?pa=campusmart.ai@upi&pn=CampusMart%20Seller'
      '&am=$amount&cu=INR&tn=$title',
    );
    var launched = false;
    try {
      launched = await launchUrl(gpay, mode: LaunchMode.externalApplication);
    } catch (_) {
      launched = false;
    }
    if (!launched) {
      try {
        launched = await launchUrl(
          generic,
          mode: LaunchMode.externalApplication,
        );
      } catch (_) {
        launched = false;
      }
    }
    if (!mounted) return;
    if (!launched) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'No UPI app found. Confirm the seller\'s UPI ID in chat and pay '
            'from your bank app, then enter the reference below.',
          ),
        ),
      );
    }
  }

  // ---------------------------------------------------------------------------
  // Place order
  // ---------------------------------------------------------------------------
  Future<void> _placeOrder() async {
    if (_placing) return;
    final auth = context.read<AuthProvider>();
    final messenger = ScaffoldMessenger.of(context);

    // Step 3 of the flow: the emailed 6-digit action code.
    final otp = await showActionOtpSheet(
      context,
      token: auth.token,
      actionType: 'purchase',
      itemTitle: widget.product.title,
      email: auth.profile?.email,
    );
    if (otp == null || !otp.verified || !mounted) return;

    setState(() {
      _placing = true;
      _placeError = null;
    });
    try {
      final result = await _api.purchaseProduct(
        productId: widget.product.id,
        token: auth.token,
        deliveryAddress: _address.text,
        hostelOrLandmark: _landmark.text,
        contactPhone: _phone.text,
        paymentMethod: _paymentMethod,
        upiReference: _upiRef.text,
        notes: _notes.text,
      );
      if (!mounted) return;
      setState(() {
        _placing = false;
        _result = result;
        _step = 3;
      });
      messenger.showSnackBar(
        SnackBar(
          backgroundColor: AppColors.success.withOpacity(0.92),
          content: const Text(
            'Order placed - the seller has been notified!',
            style: TextStyle(
              color: Colors.black,
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _placing = false;
        _placeError = error.message;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _placing = false;
        _placeError = 'Could not place the order right now. Please retry.';
      });
    }
  }

  void _openSellerChat() {
    final result = _result;
    if (result == null || result.sellerId == null) return;
    final sellerName = (result.sellerName ?? '').trim();
    // Capture the navigator before popping: the sheet's own context is
    // deactivated the moment the route pops.
    final navigator = Navigator.of(context);
    navigator.pop(result);
    navigator.push(
      MaterialPageRoute<void>(
        builder: (_) => ChatThreadScreen(
          productId: widget.product.id,
          productTitle: widget.product.title,
          productImageUrl: widget.product.imageUrl,
          productPrice: result.finalPrice,
          otherUserId: result.sellerId!,
          otherUserName: sellerName.isEmpty ? 'Campus Seller' : sellerName,
        ),
      ),
    );
  }

  // ---------------------------------------------------------------------------
  // Build
  // ---------------------------------------------------------------------------
  @override
  Widget build(BuildContext context) {
    final height = MediaQuery.of(context).size.height * 0.86;
    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
      child: SizedBox(
        height: height,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const SizedBox(height: 10),
            Center(
              child: Container(
                width: 42,
                height: 4,
                decoration: BoxDecoration(
                  color: AppColors.hairline,
                  borderRadius: BorderRadius.circular(999),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 14, 20, 8),
              child: Row(
                children: [
                  const Text(
                    'Checkout',
                    style: TextStyle(
                      fontFamily: 'Georgia',
                      color: AppColors.inkBlack,
                      fontSize: 19,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const Spacer(),
                  if (_step < 3) _StepDots(current: _step),
                ],
              ),
            ),
            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(20, 4, 20, 20),
                child: _step == 3 ? _buildSuccess() : _buildFormStep(),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildFormStep() {
    switch (_step) {
      case 0:
        return _buildDetailsStep();
      case 1:
        return _buildPaymentStep();
      default:
        return _buildReviewStep();
    }
  }

  // --- Step 0: meetup details -------------------------------------------------
  Widget _buildDetailsStep() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _ItemSummary(product: widget.product),
        const SizedBox(height: 16),
        const Text(
          'MEETUP & DELIVERY DETAILS',
          style: TextStyle(
            color: AppColors.textMuted,
            fontSize: 11,
            fontWeight: FontWeight.w800,
            letterSpacing: 1.1,
          ),
        ),
        const SizedBox(height: 10),
        _CheckoutField(
          controller: _address,
          label: 'Delivery address / hostel room',
          icon: Icons.home_outlined,
          hint: 'e.g. Hostel A, Room 214',
        ),
        const SizedBox(height: 10),
        _CheckoutField(
          controller: _landmark,
          label: 'Hostel or landmark',
          icon: Icons.place_outlined,
          hint: 'e.g. Near main canteen gate',
        ),
        const SizedBox(height: 10),
        _CheckoutField(
          controller: _phone,
          label: 'Contact phone (10 digits)',
          icon: Icons.phone_outlined,
          keyboardType: TextInputType.phone,
          formatters: [FilteringTextInputFormatter.digitsOnly],
          maxLength: 10,
        ),
        const SizedBox(height: 10),
        _CheckoutField(
          controller: _notes,
          label: 'Order notes (optional)',
          icon: Icons.sticky_note_2_outlined,
          maxLines: 2,
        ),
        if (_detailsError != null) ...[
          const SizedBox(height: 8),
          Text(
            _detailsError!,
            style: const TextStyle(color: AppColors.danger, fontSize: 12),
          ),
        ],
        const SizedBox(height: 18),
        FilledButton(
          onPressed: () {
            final phone = _phone.text.trim();
            if (_address.text.trim().isEmpty) {
              setState(() => _detailsError =
                  'Add a delivery address or hostel room.');
              return;
            }
            if (!RegExp(r'^\d{10}$').hasMatch(phone)) {
              setState(() =>
                  _detailsError = 'Enter a valid 10-digit contact phone.');
              return;
            }
            setState(() {
              _detailsError = null;
              _step = 1;
            });
          },
          child: const Text('Continue to Payment'),
        ),
      ],
    );
  }

  // --- Step 1: payment ---------------------------------------------------------
  Widget _buildPaymentStep() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Text(
          'PAYMENT METHOD',
          style: TextStyle(
            color: AppColors.textMuted,
            fontSize: 11,
            fontWeight: FontWeight.w800,
            letterSpacing: 1.1,
          ),
        ),
        const SizedBox(height: 10),
        _PaymentTile(
          emoji: '💵',
          title: 'Cash on Meetup',
          subtitle: 'Hand over cash when you collect the item',
          selected: _paymentMethod == 'Cash on Meetup',
          onTap: () => setState(() => _paymentMethod = 'Cash on Meetup'),
        ),
        const SizedBox(height: 10),
        _PaymentTile(
          emoji: '💳',
          title: 'GPay / UPI',
          subtitle: 'Pay ${formatInr(widget.product.listedPrice)} via UPI app',
          selected: _paymentMethod == 'GPay UPI',
          onTap: () => setState(() => _paymentMethod = 'GPay UPI'),
        ),
        if (_paymentMethod == 'GPay UPI') ...[
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: AppColors.royalBlue.withOpacity(0.06),
              borderRadius: BorderRadius.circular(12),
              border: Border.all(
                color: AppColors.royalBlue.withOpacity(0.3),
              ),
            ),
            child: const Text(
              'Confirm the seller\'s UPI ID in chat before paying. After the '
              'payment, paste the UPI reference (UTR) below so the order '
              'carries proof of payment.',
              style: TextStyle(
                color: AppColors.textMuted,
                fontSize: 11.5,
                height: 1.45,
              ),
            ),
          ),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            onPressed: _openUpiApp,
            icon: const Icon(Icons.open_in_new, size: 16),
            label: Text('Open UPI app · ${formatInr(widget.product.listedPrice)}'),
          ),
          const SizedBox(height: 10),
          _CheckoutField(
            controller: _upiRef,
            label: 'UPI reference / UTR (optional)',
            icon: Icons.receipt_long_outlined,
          ),
        ],
        const SizedBox(height: 18),
        FilledButton(
          onPressed: () => setState(() => _step = 2),
          child: const Text('Review Order'),
        ),
        const SizedBox(height: 8),
        TextButton(
          onPressed: () => setState(() => _step = 0),
          child: const Text('Back to details'),
        ),
      ],
    );
  }

  // --- Step 2: review ----------------------------------------------------------
  Widget _buildReviewStep() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _ItemSummary(product: widget.product),
        const SizedBox(height: 14),
        _SummaryRow(
          icon: Icons.place_outlined,
          label: 'Meetup',
          value: [
            _address.text.trim(),
            _landmark.text.trim(),
          ].where((part) => part.isNotEmpty).join(' · '),
        ),
        _SummaryRow(
          icon: Icons.phone_outlined,
          label: 'Phone',
          value: _phone.text.trim(),
        ),
        _SummaryRow(
          icon: Icons.payments_outlined,
          label: 'Payment',
          value: _paymentMethod == 'GPay UPI'
              ? 'GPay / UPI${_upiRef.text.trim().isEmpty ? '' : ' · ref ${_upiRef.text.trim()}'}'
              : 'Cash on Meetup',
        ),
        if (_notes.text.trim().isNotEmpty)
          _SummaryRow(
            icon: Icons.sticky_note_2_outlined,
            label: 'Notes',
            value: _notes.text.trim(),
          ),
        const SizedBox(height: 10),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(
            color: AppColors.surfaceHigh,
            borderRadius: BorderRadius.circular(12),
          ),
          child: const Row(
            children: [
              Icon(Icons.verified_user_outlined,
                  size: 17, color: AppColors.royalBlue),
              SizedBox(width: 8),
              Expanded(
                child: Text(
                  'A 6-digit email code verifies every order - the seller sees '
                  'your verified campus profile.',
                  style: TextStyle(
                    color: AppColors.textMuted,
                    fontSize: 11.5,
                    height: 1.4,
                  ),
                ),
              ),
            ],
          ),
        ),
        if (_placeError != null) ...[
          const SizedBox(height: 10),
          Text(
            _placeError!,
            style: const TextStyle(color: AppColors.danger, fontSize: 12),
          ),
        ],
        const SizedBox(height: 18),
        FilledButton.icon(
          onPressed: _placing ? null : _placeOrder,
          icon: _placing
              ? const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: Colors.black,
                  ),
                )
              : const Icon(Icons.verified_outlined, size: 18),
          label: Text(
            _placing
                ? 'Placing order...'
                : 'Verify OTP & Place Order · ${formatInr(widget.product.listedPrice)}',
          ),
        ),
        const SizedBox(height: 8),
        TextButton(
          onPressed: () => setState(() => _step = 1),
          child: const Text('Back to payment'),
        ),
      ],
    );
  }

  // --- Step 3: success ---------------------------------------------------------
  Widget _buildSuccess() {
    final result = _result;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SizedBox(height: 12),
        Center(
          child: Container(
            width: 74,
            height: 74,
            decoration: BoxDecoration(
              color: AppColors.success.withOpacity(0.15),
              shape: BoxShape.circle,
              border: Border.all(
                color: AppColors.success.withOpacity(0.5),
                width: 1.6,
              ),
            ),
            child: const Icon(
              Icons.check_rounded,
              size: 38,
              color: AppColors.success,
            ),
          ),
        ),
        const SizedBox(height: 16),
        const Text(
          'Order placed!',
          textAlign: TextAlign.center,
          style: TextStyle(
            fontFamily: 'Georgia',
            color: AppColors.inkBlack,
            fontSize: 21,
            fontWeight: FontWeight.w700,
          ),
        ),
        const SizedBox(height: 8),
        Text(
          result?.orderStatus ?? 'Requested / Processing',
          textAlign: TextAlign.center,
          style: const TextStyle(
            color: AppColors.royalBlue,
            fontSize: 13,
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 10),
        Text(
          '${widget.product.title} · ${formatInr(result?.finalPrice ?? widget.product.listedPrice)}\n'
          'The seller has been alerted and an Order Card was posted in your '
          'chat thread. Coordinate the handover there.',
          textAlign: TextAlign.center,
          style: const TextStyle(
            color: AppColors.textMuted,
            fontSize: 12.5,
            height: 1.5,
          ),
        ),
        const SizedBox(height: 22),
        FilledButton.icon(
          onPressed: result?.sellerId == null ? null : _openSellerChat,
          icon: const Icon(Icons.chat_bubble_outline, size: 17),
          label: const Text('Open Chat with Seller'),
        ),
        const SizedBox(height: 8),
        OutlinedButton(
          onPressed: () => Navigator.of(context).pop(_result),
          child: const Text('Done'),
        ),
      ],
    );
  }
}

/// Three-dot progress indicator for steps 1-3.
class _StepDots extends StatelessWidget {
  const _StepDots({required this.current});

  final int current;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        for (var i = 0; i < 3; i++)
          Container(
            width: i == current ? 18 : 7,
            height: 7,
            margin: const EdgeInsets.only(left: 5),
            decoration: BoxDecoration(
              color:
                  i <= current ? AppColors.royalBlue : AppColors.hairline,
              borderRadius: BorderRadius.circular(999),
            ),
          ),
      ],
    );
  }
}

/// Product thumb + title + price header reused across steps.
class _ItemSummary extends StatelessWidget {
  const _ItemSummary({required this.product});

  final Product product;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.surfaceHigh,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.hairline),
      ),
      child: Row(
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(10),
            child: SizedBox(
              width: 54,
              height: 54,
              child: product.imageUrl.isEmpty
                  ? const ColoredBox(color: AppColors.surface)
                  : Image.network(
                      product.imageUrl,
                      fit: BoxFit.cover,
                      errorBuilder: (context, error, stack) =>
                          const ColoredBox(color: AppColors.surface),
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
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                    height: 1.25,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  formatInr(product.listedPrice),
                  style: const TextStyle(
                    color: AppColors.inkBlack,
                    fontSize: 15,
                    fontWeight: FontWeight.w900,
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

/// Styled text field used by the checkout steps.
class _CheckoutField extends StatelessWidget {
  const _CheckoutField({
    required this.controller,
    required this.label,
    required this.icon,
    this.hint,
    this.keyboardType,
    this.formatters,
    this.maxLength,
    this.maxLines = 1,
  });

  final TextEditingController controller;
  final String label;
  final IconData icon;
  final String? hint;
  final TextInputType? keyboardType;
  final List<TextInputFormatter>? formatters;
  final int? maxLength;
  final int maxLines;

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      keyboardType: keyboardType,
      inputFormatters: formatters,
      maxLength: maxLength,
      maxLines: maxLines,
      style: const TextStyle(color: AppColors.textPrimary, fontSize: 13.5),
      decoration: InputDecoration(
        counterText: '',
        labelText: label,
        hintText: hint,
        prefixIcon: Icon(icon, size: 19, color: AppColors.textMuted),
      ),
    );
  }
}

/// Selectable payment method card.
class _PaymentTile extends StatelessWidget {
  const _PaymentTile({
    required this.emoji,
    required this.title,
    required this.subtitle,
    required this.selected,
    required this.onTap,
  });

  final String emoji;
  final String title;
  final String subtitle;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: selected
          ? AppColors.royalBlue.withOpacity(0.07)
          : AppColors.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: BorderSide(
          color: selected
              ? AppColors.royalBlue.withOpacity(0.5)
              : AppColors.hairline,
          width: selected ? 1.4 : 1,
        ),
      ),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
          child: Row(
            children: [
              Text(emoji, style: const TextStyle(fontSize: 22)),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: const TextStyle(
                        color: AppColors.textPrimary,
                        fontSize: 13.5,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      subtitle,
                      style: const TextStyle(
                        color: AppColors.textMuted,
                        fontSize: 11.5,
                      ),
                    ),
                  ],
                ),
              ),
              Icon(
                selected
                    ? Icons.radio_button_checked
                    : Icons.radio_button_unchecked,
                size: 20,
                color:
                    selected ? AppColors.royalBlue : AppColors.textMuted,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// One label/value row on the review step.
class _SummaryRow extends StatelessWidget {
  const _SummaryRow({
    required this.icon,
    required this.label,
    required this.value,
  });

  final IconData icon;
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 17, color: AppColors.textMuted),
          const SizedBox(width: 10),
          SizedBox(
            width: 74,
            child: Text(
              label,
              style: const TextStyle(
                color: AppColors.textMuted,
                fontSize: 12,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
          Expanded(
            child: Text(
              value.isEmpty ? '-' : value,
              style: const TextStyle(
                color: AppColors.textPrimary,
                fontSize: 12.5,
                height: 1.35,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
