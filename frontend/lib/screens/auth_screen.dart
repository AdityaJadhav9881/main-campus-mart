import 'package:flutter/material.dart';
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
class AuthScreen extends StatefulWidget {
  const AuthScreen({super.key});

  @override
  State<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends State<AuthScreen> {
  final _formKey = GlobalKey<FormState>();
  final _nameController = TextEditingController();
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();

  bool _isLoginMode = true;
  bool _obscurePassword = true;

  /// Campus TLDs that earn the positive visual indicator (never a gate).
  static const List<String> _campusTlds = [
    '.edu',
    '.ac.in',
    '.edu.in',
    '.org',
  ];

  @override
  void dispose() {
    _nameController.dispose();
    _emailController.dispose();
    _passwordController.dispose();
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
    final form = _formKey.currentState;
    if (form == null || !form.validate()) return;

    final auth = context.read<AuthProvider>();
    final messenger = ScaffoldMessenger.of(context);

    final bool ok;
    if (_isLoginMode) {
      ok = await auth.login(
        email: _emailController.text.trim(),
        password: _passwordController.text,
      );
    } else {
      ok = await auth.register(
        name: _nameController.text.trim(),
        email: _emailController.text.trim(),
        password: _passwordController.text,
      );
    }

    if (!mounted) return;
    if (ok) {
      messenger.showSnackBar(
        SnackBar(
          backgroundColor: AppColors.success.withOpacity(0.92),
          content: Text(
            _isLoginMode ? 'Welcome back!' : 'Account created — happy trading!',
            style: const TextStyle(
              color: Colors.black,
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthProvider>();
    final campusDetected = _isCampusEmail(_emailController.text);

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
                  _ModeToggle(
                    isLogin: _isLoginMode,
                    onChanged: (login) => setState(() => _isLoginMode = login),
                  ),
                  const SizedBox(height: 22),
                  Form(
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
                  ),
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
                              color: Colors.black,
                            ),
                          )
                        : Text(_isLoginMode ? 'Log In' : 'Create Account'),
                  ),
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
                ],
              ),
            ),
          ),
        ),
      ),
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
          width: 64,
          height: 64,
          decoration: BoxDecoration(
            color: AppColors.cyanAccent.withOpacity(0.12),
            borderRadius: BorderRadius.circular(20),
            border: Border.all(
              color: AppColors.cyanAccent.withOpacity(0.45),
            ),
          ),
          child: const Icon(
            Icons.school_outlined,
            size: 30,
            color: AppColors.cyanAccent,
          ),
        ),
        const SizedBox(height: 16),
        const Text(
          'CampusMart AI',
          style: TextStyle(
            color: AppColors.textPrimary,
            fontSize: 26,
            fontWeight: FontWeight.w800,
            letterSpacing: -0.4,
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
            color: selected ? AppColors.cyanAccent : Colors.transparent,
            borderRadius: BorderRadius.circular(10),
          ),
          child: Text(
            label,
            textAlign: TextAlign.center,
            style: TextStyle(
              color: selected ? Colors.black : AppColors.textMuted,
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
  });

  final TextEditingController controller;
  final String label;
  final IconData icon;
  final TextInputType? keyboardType;
  final bool obscure;
  final Widget? suffixIcon;
  final ValueChanged<String>? onChanged;
  final String? Function(String?)? validator;

  @override
  Widget build(BuildContext context) {
    return TextFormField(
      controller: controller,
      keyboardType: keyboardType,
      obscureText: obscure,
      onChanged: onChanged,
      validator: validator,
      style: const TextStyle(
        color: AppColors.textPrimary,
        fontSize: 14.5,
      ),
      decoration: InputDecoration(
        labelText: label,
        labelStyle: const TextStyle(color: AppColors.textMuted),
        prefixIcon: Icon(icon, size: 20, color: AppColors.cyanAccent),
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
            color: AppColors.cyanAccent,
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
