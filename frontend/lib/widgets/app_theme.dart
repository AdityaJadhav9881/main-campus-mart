import 'package:flutter/material.dart';

/// CampusMart "deep void" design tokens: dark surfaces, subtle cyan accents,
/// and hairline borders. Single source of truth for the whole UI.
abstract final class AppColors {
  /// App background (deep void black with a blue undertone).
  static const Color voidBlack = Color(0xFF0A0E14);

  /// Cards, fields, and the bottom nav bar.
  static const Color surface = Color(0xFF111826);

  /// Elevated/pressed variants and meter tracks.
  static const Color surfaceHigh = Color(0xFF1A2437);

  /// Primary accent (subtle cyan).
  static const Color cyanAccent = Color(0xFF22D3EE);

  static const Color textPrimary = Color(0xFFE8EDF5);
  static const Color textMuted = Color(0xFF8A94A6);

  /// 12%-white hairline used for all borders/dividers.
  static const Color hairline = Color(0x1FFFFFFF);

  static const Color success = Color(0xFF34D399);
  static const Color warning = Color(0xFFFBBF24);
  static const Color danger = Color(0xFFF87171);
}

/// Central dark theme for the app.
abstract final class AppTheme {
  static ThemeData get dark {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      colorScheme: ColorScheme.fromSeed(
        seedColor: AppColors.cyanAccent,
        brightness: Brightness.dark,
      ),
      scaffoldBackgroundColor: AppColors.voidBlack,
      appBarTheme: const AppBarTheme(
        backgroundColor: AppColors.voidBlack,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: AppColors.surface,
        hintStyle: const TextStyle(color: AppColors.textMuted),
        labelStyle: const TextStyle(color: AppColors.textMuted),
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        border: _inputBorder(),
        enabledBorder: _inputBorder(),
        focusedBorder: _inputBorder(color: AppColors.cyanAccent, width: 1.4),
        errorBorder: _inputBorder(color: AppColors.danger),
        focusedErrorBorder:
            _inputBorder(color: AppColors.danger, width: 1.4),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: AppColors.cyanAccent,
          foregroundColor: Colors.black,
          minimumSize: const Size.fromHeight(52),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(14),
          ),
          textStyle: const TextStyle(
            fontWeight: FontWeight.w700,
            fontSize: 15,
          ),
        ),
      ),
      bottomNavigationBarTheme: const BottomNavigationBarThemeData(
        backgroundColor: AppColors.surface,
        selectedItemColor: AppColors.cyanAccent,
        unselectedItemColor: AppColors.textMuted,
        type: BottomNavigationBarType.fixed,
      ),
      snackBarTheme: SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        backgroundColor: AppColors.surfaceHigh,
        contentTextStyle: const TextStyle(color: AppColors.textPrimary),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(12),
        ),
      ),
      dividerTheme: const DividerThemeData(
        color: AppColors.hairline,
        space: 1,
      ),
    );
  }

  /// Shared hairline outline for text fields.
  static OutlineInputBorder _inputBorder({
    Color color = AppColors.hairline,
    double width = 1,
  }) {
    return OutlineInputBorder(
      borderRadius: BorderRadius.circular(12),
      borderSide: BorderSide(color: color, width: width),
    );
  }
}
