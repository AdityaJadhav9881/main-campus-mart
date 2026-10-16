import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../providers/auth_provider.dart';
import '../widgets/app_theme.dart';

/// Full-screen Login / Sign-Up for campus email-password auth (Phase 7).
///
/// Validation policy (flexible by design — global campuses):
///   * Any syntactically valid email (`x@y.z`) is accepted, so evaluators can
///     use standard Gmail/Yahoo addresses and Indian domains alike.
///   * A positive "Campus email detected" badge appears for known campus
///     TLDs: .edu, .ac.in, .edu.in, .org — purely informational, never a
///     hard block.
///
/// Sign-up is now a **2-step email OTP flow** (Task 4):
///   Step 1 - name / email / password -> POST /auth/send-otp mails a 6-digit
///            code (Brevo) and parks the signup for 10 minutes.
///   Step 2 - enter the code -> POST /auth/verify-otp creates the account
///            and signs the student straight in. Resend unlocks after 30s.
class AuthScreen extends StatefulWidget {
  const AuthScreen({super.key});

  @override
  State<AuthScreen> createState() => _AuthScreenState();
}

enum _SignupStep { details, otp }

class _AuthScreenState extends State<AuthScreen> {
  final _formKey = GlobalKey<FormState>();
  final _otpFormKey = GlobalKey<FormState>();
  final _nameController = TextEditingController();
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  final _otpController = TextEditingController();

  bool _isLoginMode = true;
  bool _obscurePassword = true;

  /// Step 2 (code entry) only exists while signing up.
  _SignupStep _signupStep = _SignupStep.details;

  /// Resend cooldown (30s) after every issued code.
  int _resendSeconds = 0;
  Timer? _resendTimer;

  /// Warm-up card shown if a login attempt is still pending after 3s
  /// (Render cold start) - reassured progress, no server internals.
  Timer? _warmupTimer;
  bool _warmupVisible = false;

  /// Campus TLDs that earn the positive visual indicator (never a gate).
  static const List<String> _campusTlds = [
    '.edu',
    '.ac.in',
    '.edu.in',
    '.org',
  ];

  @override
  void dispose() {
    _resendTimer?.cancel();
    _warmupTimer?.cancel();
    _nameController.dispose();
    _emailController.dispose();
    _passwordController.dispose();
    _otpController.dispose();
    super.dispose();
  }

  /// Loose "has an @ and a dot after it" check — intentionally permissive.
  bool _isValidEmail(String email) {
    final value = email.trim();
    final at = value.indexOf('@');
    if (at <= 0 || at != value.lastIndexOf('@')) return false;
    final domain = value.substring(at + 1);
    final dot = domain.indexOf('.');
    return dot > 0 && dot < domain.length - 1 && !domain.contains('..');
  }

  bool _isCampusEmail(String email) {
    final value = email.trim().toLowerCase();
    return _campusTlds.any(
      (tld) => value.endsWith(tld) || value.contains('$tld.'),
    );
  }

  Future<void> _submit() async {
    final auth = context.read<AuthProvider>();
    final messenger = ScaffoldMessenger.of(context);

    // Step 2: verify the 6-digit code, then the session is live.
    if (!_isLoginMode && _signupStep == _SignupStep.otp) {
      final otpForm = _otpFormKey.currentState;
      if (otpForm == null || !otpForm.validate()) return;
      final ok = await auth.verifyOtp(
        email: _emailController.text.trim(),
        otpCode: _otpController.text.trim(),
      );
      if (!mounted) return;
      if (ok) {
        messenger.showSnackBar(
          SnackBar(
            backgroundColor: AppColors.success.withOpacity(0.92),
            content: const Text(
              'Account created — happy trading!',
              style: TextStyle(
                color: Colors.black,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        );
      }
      return;
    }

    final form = _formKey.currentState;
    if (form == null || !form.validate()) return;

    final bool ok;
    if (_isLoginMode) {
      _startWarmup();
      ok = await auth.login(
        email: _emailController.text.trim(),
        password: _passwordController.text,
      );
      _stopWarmup();
    } else {
      // Step 1: park the signup and email the code (Brevo).
      ok = await auth.sendOtp(
        name: _nameController.text.trim(),
        email: _emailController.text.trim(),
        password: _passwordController.text,
      );
      if (!mounted) return;
      if (ok) {
        setState(() {
          _signupStep = _SignupStep.otp;
          _otpController.clear();
        });
        _startResendCooldown();
        messenger.showSnackBar(
          SnackBar(
            backgroundColor: AppColors.royalBlue,
            content: Text(
              'Verification code sent to ${_emailController.text.trim()}',
              style: const TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        );
      }
      return;
    }

    if (!mounted) return;
    if (ok) {
      messenger.showSnackBar(
        SnackBar(
          backgroundColor: AppColors.success.withOpacity(0.92),
          content: const Text(
            'Welcome back!',
            style: TextStyle(
              color: Colors.black,
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
      );
    }
  }

  /// 30-second resend lockout restarted after every issued OTP.
  void _startResendCooldown() {
    _resendTimer?.cancel();
    setState(() => _resendSeconds = 30);
    _resendTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
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

  Future<void> _resendCode() async {
    if (_resendSeconds > 0) return;
    final auth = context.read<AuthProvider>();
    final messenger = ScaffoldMessenger.of(context);
    final ok = await auth.resendOtp(email: _emailController.text.trim());
    if (!mounted) return;
    if (ok) {
      _startResendCooldown();
      messenger.showSnackBar(
        const SnackBar(
          backgroundColor: AppColors.royalBlue,
          content: Text(
            'New verification code sent — check your inbox.',
            style: TextStyle(
              color: Colors.white,
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
      );
    }
  }

  void _startWarmup() {
    _warmupTimer?.cancel();
    _warmupVisible = false;
    _warmupTimer = Timer(const Duration(seconds: 3), () {
      if (!mounted) return;
      if (context.read<AuthProvider>().isLoading) {
        setState(() => _warmupVisible = true);
      }
    });
  }

  void _stopWarmup() {
    _warmupTimer?.cancel();
    if (_warmupVisible && mounted) setState(() => _warmupVisible = false);
  }

  void _backToDetails() {
    _resendTimer?.cancel();
    setState(() {
      _signupStep = _SignupStep.details;
      _otpController.clear();
      _resendSeconds = 0;
    });
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthProvider>();
    final campusDetected = _isCampusEmail(_emailController.text);
    final otpStep = !_isLoginMode && _signupStep == _SignupStep.otp;

    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(24, 24, 24, 32),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const _Header(),
                  const SizedBox(height: 28),
                  if (!otpStep)
                    _ModeToggle(
                      isLogin: _isLoginMode,
                      onChanged: (login) => setState(() {
                        _isLoginMode = login;
                        if (login) _backToDetails();
                      }),
                    ),
                  const SizedBox(height: 22),
                  if (otpStep)
                    _buildOtpStep()
                  else
                    _buildDetailsForm(campusDetected),
                  if (auth.errorMessage != null) ...[
                    const SizedBox(height: 14),
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: AppColors.danger.withOpacity(0.12),
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(
                          color: AppColors.danger.withOpacity(0.45),
                        ),
                      ),
                      child: Text(
                        auth.errorMessage!,
                        style: const TextStyle(
                          color: AppColors.danger,
                          fontSize: 13,
                          height: 1.4,
                        ),
                      ),
                    ),
                  ],
                  const SizedBox(height: 22),
                  FilledButton(
                    onPressed: auth.isLoading ? null : _submit,
                    child: auth.isLoading
                        ? const SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : Text(
                            otpStep
                                ? 'Verify Code'
                                : (_isLoginMode ? 'Log In' : 'Create Account'),
                          ),
                  ),
                  // Cold-start reassurance while a login is still pending.
                  if (_warmupVisible && auth.isLoading) ...[
                    const SizedBox(height: 16),
                    Container(
                      padding: const EdgeInsets.all(14),
                      decoration: BoxDecoration(
                        color: AppColors.surface,
                        borderRadius: BorderRadius.circular(14),
                        border: Border.all(
                          color: AppColors.royalBlue.withOpacity(0.35),
                        ),
                      ),
                      child: const Column(
                        children: [
                          Text(
                            'Connecting to Campus Mart Ai Marketplace',
                            textAlign: TextAlign.center,
                            style: TextStyle(
                              color: AppColors.textPrimary,
                              fontSize: 13.5,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                          SizedBox(height: 6),
                          Text(
                            'Hang tight! Waking up our cloud AI server '
                            '(takes ~30-60 seconds on first launch)...',
                            textAlign: TextAlign.center,
                            style: TextStyle(
                              color: AppColors.textMuted,
                              fontSize: 12,
                              height: 1.4,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                  const SizedBox(height: 16),
                  const Text(
                    'Trade second-hand campus gear with verified students. '
                    'Reuse. Reduce. Recycle.',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      color: AppColors.textMuted,
                      fontSize: 12.5,
                      height: 1.45,
                    ),
                  ),
                  const SizedBox(height: 14),
                  Center(
                    child: InkWell(
                      borderRadius: BorderRadius.circular(8),
                      onTap: () {
                        Clipboard.setData(
                          const ClipboardData(text: 'martaicampus@gmail.com'),
                        );
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(
                            content: Text(
                              'Support email copied: martaicampus@gmail.com',
                            ),
                          ),
                        );
                      },
                      child: const Padding(
                        padding: EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                        child: Text(
                          'Need help signing in? Contact martaicampus@gmail.com',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            color: AppColors.royalBlue,
                            fontSize: 12.5,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
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

  /// Step 1 fields (name / college email / password) for login + signup.
  Widget _buildDetailsForm(bool campusDetected) {
    return Form(
      key: _formKey,
      child: Column(
        children: [
          if (!_isLoginMode) ...[
            _TextFormField(
              controller: _nameController,
              label: 'Full name',
              icon: Icons.person_outline,
              validator: (value) =>
                  (value == null || value.trim().isEmpty)
                      ? 'Enter your name'
                      : null,
            ),
            const SizedBox(height: 14),
          ],
          _TextFormField(
            controller: _emailController,
            label: 'College email',
            icon: Icons.email_outlined,
            keyboardType: TextInputType.emailAddress,
            onChanged: (_) => setState(() {}),
            validator: (value) {
              final email = value?.trim() ?? '';
              if (email.isEmpty) return 'Enter your email';
              if (!_isValidEmail(email)) {
                return 'Enter a valid email (e.g. you@college.edu)';
              }
              return null;
            },
          ),
          // Positive campus-domain indicator (informational).
          if (campusDetected) ...[
            const SizedBox(height: 8),
            const _CampusBadge(),
          ],
          const SizedBox(height: 14),
          _TextFormField(
            controller: _passwordController,
            label: 'Password',
            icon: Icons.lock_outline,
            obscure: _obscurePassword,
            suffixIcon: IconButton(
              icon: Icon(
                _obscurePassword
                    ? Icons.visibility_off_outlined
                    : Icons.visibility_outlined,
                size: 20,
                color: AppColors.textMuted,
              ),
              onPressed: () => setState(
                () => _obscurePassword = !_obscurePassword,
              ),
            ),
            validator: (value) {
              final password = value ?? '';
              if (password.isEmpty) return 'Enter your password';
              if (!_isLoginMode && password.length < 8) {
                return 'Password must be at least 8 characters';
              }
              return null;
            },
          ),
        ],
      ),
    );
  }

  /// Step 2: the 6-digit code box + resend cooldown + back link.
  Widget _buildOtpStep() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TextButton.icon(
          onPressed: _backToDetails,
          icon: const Icon(Icons.arrow_back, size: 16, color: AppColors.textMuted),
          label: const Text(
            'Back to sign up details',
            style: TextStyle(
              color: AppColors.textMuted,
              fontSize: 13,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
        const SizedBox(height: 4),
        Text(
          'We emailed a 6-digit code to\n${_emailController.text.trim()}',
          textAlign: TextAlign.center,
          style: const TextStyle(
            color: AppColors.textPrimary,
            fontSize: 14.5,
            height: 1.5,
            fontWeight: FontWeight.w700,
          ),
        ),
        const SizedBox(height: 6),
        const Text(
          'It expires in 10 minutes. Check spam if you do not see it.',
          textAlign: TextAlign.center,
          style: TextStyle(
            color: AppColors.textMuted,
            fontSize: 12,
            height: 1.4,
          ),
        ),
        Builder(
          builder: (context) {
            final fallback = context.watch<AuthProvider>().fallbackOtp;
            if (fallback == null || fallback.isEmpty) return const SizedBox.shrink();
            return Padding(
              padding: const EdgeInsets.only(top: 14),
              child: InkWell(
                borderRadius: BorderRadius.circular(12),
                onTap: () {
                  _otpController.text = fallback;
                  setState(() {});
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text('Instant verification code applied!'),
                      duration: Duration(seconds: 2),
                    ),
                  );
                },
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                  decoration: BoxDecoration(
                    color: const Color(0xFFFEF3C7),
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: const Color(0xFFF59E0B)),
                  ),
                  child: Row(
                    children: [
                      const Icon(Icons.flash_on, color: Color(0xFFB45309), size: 22),
                      const SizedBox(width: 10),
                      Expanded(
                        child: RichText(
                          text: TextSpan(
                            style: const TextStyle(
                              color: Color(0xFF92400E),
                              fontSize: 12.5,
                              height: 1.35,
                            ),
                            children: [
                              const TextSpan(
                                text: 'Email delivery delayed — use instant verification code: ',
                              ),
                              TextSpan(
                                text: fallback,
                                style: const TextStyle(
                                  fontWeight: FontWeight.w800,
                                  fontSize: 14,
                                  letterSpacing: 2,
                                ),
                              ),
                              const TextSpan(
                                text: '\n(Tap here to fill code)',
                                style: TextStyle(
                                  fontWeight: FontWeight.w700,
                                  color: Color(0xFFB45309),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            );
          },
        ),
        const SizedBox(height: 18),
        Form(
          key: _otpFormKey,
          child: _TextFormField(
            controller: _otpController,
            label: 'Verification code',
            icon: Icons.pin_outlined,
            keyboardType: TextInputType.number,
            maxLength: 6,
            validator: (value) {
              final code = (value ?? '').trim();
              if (code.isEmpty) return 'Enter the 6-digit code';
              if (!RegExp(r'^\d{6}$').hasMatch(code)) {
                return 'Enter the 6 digits from your email';
              }
              return null;
            },
          ),
        ),
        const SizedBox(height: 10),
        Center(
          child: _resendSeconds > 0
              ? Text(
                  'Resend code in ${_resendSeconds}s',
                  style: const TextStyle(
                    color: AppColors.textMuted,
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                  ),
                )
              : TextButton(
                  onPressed: _resendCode,
                  child: const Text(
                    'Resend code',
                    style: TextStyle(
                      color: AppColors.royalBlue,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
        ),
      ],
    );
  }
}

class _Header extends StatelessWidget {
  const _Header();

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Container(
          width: 96,
          height: 96,
          clipBehavior: Clip.antiAlias,
          decoration: BoxDecoration(
            color: AppColors.surface,
            borderRadius: BorderRadius.circular(24),
            border: Border.all(
              color: AppColors.hairline,
              width: 1.2,
            ),
            boxShadow: const [
              BoxShadow(
                color: Color(0x0C000000),
                blurRadius: 10,
                offset: Offset(0, 4),
              ),
            ],
          ),
          child: const Image(
            image: AssetImage('assets/logo.png'),
            fit: BoxFit.cover,
          ),
        ),
        const SizedBox(height: 18),
        const Text(
          'Campus Mart Ai',
          style: TextStyle(
            fontFamily: 'Georgia',
            color: AppColors.inkBlack,
            fontSize: 28,
            fontWeight: FontWeight.w700,
            letterSpacing: -0.5,
          ),
        ),
        const SizedBox(height: 6),
        const Text(
          'Sign in to buy and sell on campus',
          style: TextStyle(
            color: AppColors.textMuted,
            fontSize: 14,
          ),
        ),
      ],
    );
  }
}

class _ModeToggle extends StatelessWidget {
  const _ModeToggle({required this.isLogin, required this.onChanged});

  final bool isLogin;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.hairline),
      ),
      child: Row(
        children: [
          _ToggleChip(
            label: 'Log In',
            selected: isLogin,
            onTap: () => onChanged(true),
          ),
          _ToggleChip(
            label: 'Sign Up',
            selected: !isLogin,
            onTap: () => onChanged(false),
          ),
        ],
      ),
    );
  }
}

class _ToggleChip extends StatelessWidget {
  const _ToggleChip({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: GestureDetector(
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 11),
          decoration: BoxDecoration(
            color: selected ? AppColors.inkBlack : Colors.transparent,
            borderRadius: BorderRadius.circular(10),
          ),
          child: Text(
            label,
            textAlign: TextAlign.center,
            style: TextStyle(
              color: selected ? Colors.white : AppColors.textMuted,
              fontWeight: FontWeight.w700,
              fontSize: 13.5,
            ),
          ),
        ),
      ),
    );
  }
}

class _CampusBadge extends StatelessWidget {
  const _CampusBadge();

  @override
  Widget build(BuildContext context) {
    return const Row(
      children: [
        Icon(
          Icons.verified_outlined,
          size: 14,
          color: AppColors.success,
        ),
        SizedBox(width: 6),
        Text(
          'Campus email detected — verified-student benefits unlocked',
          style: TextStyle(
            color: AppColors.success,
            fontSize: 12,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    );
  }
}

class _TextFormField extends StatelessWidget {
  const _TextFormField({
    required this.controller,
    required this.label,
    required this.icon,
    this.keyboardType,
    this.obscure = false,
    this.suffixIcon,
    this.onChanged,
    this.validator,
    this.maxLength,
  });

  final TextEditingController controller;
  final String label;
  final IconData icon;
  final TextInputType? keyboardType;
  final bool obscure;
  final Widget? suffixIcon;
  final ValueChanged<String>? onChanged;
  final String? Function(String?)? validator;
  final int? maxLength;

  @override
  Widget build(BuildContext context) {
    return TextFormField(
      controller: controller,
      keyboardType: keyboardType,
      obscureText: obscure,
      onChanged: onChanged,
      validator: validator,
      maxLength: maxLength,
      style: const TextStyle(
        color: AppColors.textPrimary,
        fontSize: 14.5,
      ),
      decoration: InputDecoration(
        labelText: label,
        counterText: maxLength != null ? '' : null,
        labelStyle: const TextStyle(color: AppColors.textMuted),
        prefixIcon: Icon(icon, size: 20, color: AppColors.royalBlue),
        suffixIcon: suffixIcon,
        filled: true,
        fillColor: AppColors.surface,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 16,
          vertical: 14,
        ),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(color: AppColors.hairline),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(color: AppColors.hairline),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(
            color: AppColors.royalBlue,
            width: 1.4,
          ),
        ),
        errorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(color: AppColors.danger),
        ),
        focusedErrorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(color: AppColors.danger, width: 1.4),
        ),
      ),
    );
  }
}
