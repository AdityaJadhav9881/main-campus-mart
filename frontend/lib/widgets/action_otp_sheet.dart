import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../services/api_service.dart';
import 'app_theme.dart';

/// Bottom sheet that emails a 6-digit code and verifies it before a
/// publish (sell) or purchase action - the "no OTP, no listing/order" trust
/// gate (Part B Task 7).
///
/// Resolves to an [ActionOtpResult] with the minted action token, or null
/// when dismissed. In dev/unkeyed environments the API echoes
/// `fallback_otp_code` and the sheet offers a one-tap fill.
Future<ActionOtpResult?> showActionOtpSheet(
  BuildContext context, {
  required String token,
  required String actionType, // 'sell' | 'purchase'
  String? itemTitle,
  String? email,
}) {
  return showModalBottomSheet<ActionOtpResult>(
    context: context,
    isScrollControlled: true,
    backgroundColor: AppColors.surface,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(22)),
    ),
    builder: (_) => Padding(
      padding: EdgeInsets.only(
        bottom: MediaQuery.of(context).viewInsets.bottom,
      ),
      child: _ActionOtpSheet(
        token: token,
        actionType: actionType,
        itemTitle: itemTitle,
        email: email,
      ),
    ),
  );
}

class _ActionOtpSheet extends StatefulWidget {
  const _ActionOtpSheet({
    required this.token,
    required this.actionType,
    this.itemTitle,
    this.email,
  });

  final String token;
  final String actionType;
  final String? itemTitle;
  final String? email;

  @override
  State<_ActionOtpSheet> createState() => _ActionOtpSheetState();
}

class _ActionOtpSheetState extends State<_ActionOtpSheet> {
  final ApiService _api = ApiService.instance;
  final TextEditingController _code = TextEditingController();

  bool _sending = true;
  bool _verifying = false;
  String? _sendError;
  String? _verifyError;
  String? _fallbackCode;
  int _resendSeconds = 0;
  Timer? _timer;

  bool get _isSell => widget.actionType == 'sell';

  @override
  void initState() {
    super.initState();
    _sendCode();
  }

  @override
  void dispose() {
    _timer?.cancel();
    _code.dispose();
    super.dispose();
  }

  Future<void> _sendCode() async {
    setState(() {
      _sending = true;
      _sendError = null;
      _fallbackCode = null;
    });
    try {
      final res = await _api.sendActionOtp(
        actionType: widget.actionType,
        token: widget.token,
        itemTitle: widget.itemTitle,
      );
      if (!mounted) return;
      setState(() {
        _sending = false;
        _fallbackCode = res['fallback_otp_code'] as String?;
      });
      _startCooldown();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _sending = false;
        _sendError = error.message;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _sending = false;
        _sendError = 'Could not send the verification code right now.';
      });
    }
  }

  void _startCooldown() {
    _timer?.cancel();
    setState(() => _resendSeconds = 30);
    _timer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (!mounted) {
        timer.cancel();
        return;
      }
      if (_resendSeconds <= 1) {
        timer.cancel();
        setState(() => _resendSeconds = 0);
      } else {
        setState(() => _resendSeconds -= 1);
      }
    });
  }

  Future<void> _verify() async {
    final code = _code.text.trim();
    if (!RegExp(r'^\d{6}$').hasMatch(code)) {
      setState(() => _verifyError = 'Enter the 6-digit code');
      return;
    }
    setState(() {
      _verifying = true;
      _verifyError = null;
    });
    try {
      final result = await _api.verifyActionOtp(
        otpCode: code,
        token: widget.token,
        actionType: widget.actionType,
      );
      if (!mounted) return;
      if (result.verified) {
        Navigator.of(context).pop(result);
      } else {
        setState(() {
          _verifying = false;
          _verifyError = 'That code did not match. Try again.';
        });
      }
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _verifying = false;
        _verifyError = error.message;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _verifying = false;
        _verifyError = 'Could not verify the code right now.';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final actionLabel = _isSell ? 'Publish Listing' : 'Place Order';
    final emailLine = (widget.email ?? '').trim().isEmpty
        ? 'your account email'
        : widget.email!.trim();

    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 14, 20, 20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
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
            const SizedBox(height: 16),
            Row(
              children: [
                Container(
                  width: 40,
                  height: 40,
                  decoration: BoxDecoration(
                    color: AppColors.royalBlue.withOpacity(0.1),
                    shape: BoxShape.circle,
                  ),
                  child: const Icon(
                    Icons.pin_outlined,
                    size: 20,
                    color: AppColors.royalBlue,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Verify to $actionLabel',
                        style: const TextStyle(
                          fontFamily: 'Georgia',
                          color: AppColors.inkBlack,
                          fontSize: 17,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const SizedBox(height: 3),
                      Text(
                        _sending
                            ? 'Sending a 6-digit code to $emailLine...'
                            : 'Code sent to $emailLine · expires in 10 min',
                        style: const TextStyle(
                          color: AppColors.textMuted,
                          fontSize: 12,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            if (widget.itemTitle != null &&
                widget.itemTitle!.trim().isNotEmpty) ...[
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.symmetric(
                    horizontal: 12, vertical: 9),
                decoration: BoxDecoration(
                  color: AppColors.surfaceHigh,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Text(
                  widget.itemTitle!.trim(),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 12.5,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ],
            const SizedBox(height: 18),
            if (_sending)
              const Center(
                child: SizedBox(
                  width: 26,
                  height: 26,
                  child: CircularProgressIndicator(
                    strokeWidth: 2.6,
                    color: AppColors.royalBlue,
                  ),
                ),
              )
            else if (_sendError != null)
              Column(
                children: [
                  Text(
                    _sendError!,
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      color: AppColors.danger,
                      fontSize: 12.5,
                      height: 1.4,
                    ),
                  ),
                  const SizedBox(height: 10),
                  FilledButton.tonal(
                    onPressed: _sendCode,
                    child: const Text('Retry sending code'),
                  ),
                ],
              )
            else ...[
              if (_fallbackCode != null) ...[
                InkWell(
                  borderRadius: BorderRadius.circular(12),
                  onTap: () {
                    _code.text = _fallbackCode!;
                    setState(() {});
                    _verify();
                  },
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 14, vertical: 11),
                    decoration: BoxDecoration(
                      color: const Color(0xFFFEF3C7),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: const Color(0xFFF59E0B)),
                    ),
                    child: Row(
                      children: [
                        const Icon(Icons.flash_on,
                            color: Color(0xFFB45309), size: 20),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Text.rich(
                            TextSpan(
                              style: const TextStyle(
                                color: Color(0xFF92400E),
                                fontSize: 12,
                                height: 1.35,
                              ),
                              children: [
                                const TextSpan(
                                    text: 'Email delayed - instant code: '),
                                TextSpan(
                                  text: _fallbackCode,
                                  style: const TextStyle(
                                    fontWeight: FontWeight.w800,
                                    fontSize: 13.5,
                                    letterSpacing: 2,
                                  ),
                                ),
                                const TextSpan(text: ' (tap to fill)'),
                              ],
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 12),
              ],
              TextField(
                controller: _code,
                keyboardType: TextInputType.number,
                maxLength: 6,
                textAlign: TextAlign.center,
                inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                onSubmitted: (_) => _verify(),
                style: const TextStyle(
                  color: AppColors.textPrimary,
                  fontSize: 22,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 8,
                ),
                decoration: const InputDecoration(
                  counterText: '',
                  hintText: '••••••',
                  hintStyle: TextStyle(
                    color: AppColors.hairline,
                    letterSpacing: 8,
                  ),
                ),
              ),
              if (_verifyError != null) ...[
                const SizedBox(height: 6),
                Text(
                  _verifyError!,
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    color: AppColors.danger,
                    fontSize: 12,
                  ),
                ),
              ],
              const SizedBox(height: 14),
              FilledButton(
                onPressed: _verifying ? null : _verify,
                child: _verifying
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Colors.black,
                        ),
                      )
                    : const Text('Verify & Continue'),
              ),
              const SizedBox(height: 8),
              Center(
                child: TextButton(
                  onPressed: _resendSeconds > 0 ? null : _sendCode,
                  child: Text(
                    _resendSeconds > 0
                        ? 'Resend code in ${_resendSeconds}s'
                        : 'Resend code',
                    style: const TextStyle(fontSize: 12.5),
                  ),
                ),
              ),
              const Text(
                'For your safety this code is required before every approved '
                'sell or purchase action.',
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: AppColors.textMuted,
                  fontSize: 11,
                  height: 1.4,
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
