import 'package:flutter/material.dart';

/// CampusMart "Warm Paper" design tokens (image_28.png):
///   Main Background: Warm Paper-Cream (#FAF9F6)
///   Card/Surface Backgrounds: Crisp White (#FFFFFF)
///   Primary Buttons, Headers & Dark text: Deep Ink-Black (#141413)
///   Soft Elements (Input boxes, disabled state): Stone-Sand Gray (#F3F2EE or #EFEFE9)
///   Primary Highlight: Subtle Royal Blue (#2563EB)
///   Verified & Badge Accents: Matte Forest Green (#15803D) and soft amber (#D97706)
abstract final class AppColors {
  /// Main Background: Warm Paper-Cream (#FAF9F6).
  static const Color background = Color(0xFFFAF9F6);
  static const Color warmCream = Color(0xFFFAF9F6);

  /// Backward-compatibility alias so all existing views inherit Warm Paper-Cream:
  static const Color voidBlack = Color(0xFFFAF9F6);

  /// Card/Surface Backgrounds: Crisp White (#FFFFFF).
  static const Color surface = Color(0xFFFFFFFF);

  /// Soft Elements (Input boxes, disabled state, meter tracks): Stone-Sand Gray (#F3F2EE).
  static const Color surfaceHigh = Color(0xFFF3F2EE);
  static const Color stoneSand = Color(0xFFF3F2EE);
  static const Color softGray = Color(0xFFEFEFE9);

  /// Primary Buttons, Headers & Dark text: Deep Ink-Black (#141413).
  static const Color inkBlack = Color(0xFF141413);
  static const Color textPrimary = Color(0xFF141413);

  /// Muted body text / subtitles: refined charcoal (#6B7280).
  static const Color textMuted = Color(0xFF6B7280);

  /// Primary Highlight: Subtle Royal Blue (#2563EB).
  static const Color royalBlue = Color(0xFF2563EB);

  /// Backward-compatibility alias so highlight references use Subtle Royal Blue:
  static const Color cyanAccent = Color(0xFF2563EB);

  /// Hairline borders / dividers: warm stone hairline (#E5E5DF).
  static const Color hairline = Color(0xFFE5E5DF);

  /// Verified & Badge Accents: Matte Forest Green (#15803D).
  static const Color success = Color(0xFF15803D);
  static const Color forestGreen = Color(0xFF15803D);

  /// Soft amber accent (#D97706).
  static const Color warning = Color(0xFFD97706);
  static const Color softAmber = Color(0xFFD97706);

  /// Error/danger accent (#DC2626).
  static const Color danger = Color(0xFFDC2626);
}

/// Central Warm Paper theme for the app.
abstract final class AppTheme {
  static ThemeData get paper {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.light,
      colorScheme: const ColorScheme.light(
        primary: AppColors.royalBlue,
        secondary: AppColors.forestGreen,
        surface: AppColors.surface,
        onSurface: AppColors.textPrimary,
        error: AppColors.danger,
      ),
      scaffoldBackgroundColor: AppColors.background,
      appBarTheme: const AppBarTheme(
        backgroundColor: AppColors.background,
        foregroundColor: AppColors.inkBlack,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        titleTextStyle: TextStyle(
          fontFamily: 'Georgia',
          fontSize: 20,
          fontWeight: FontWeight.w700,
          color: AppColors.inkBlack,
          letterSpacing: -0.3,
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: AppColors.surfaceHigh,
        hintStyle: const TextStyle(color: AppColors.textMuted),
        labelStyle: const TextStyle(color: AppColors.textMuted),
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        border: _inputBorder(),
        enabledBorder: _inputBorder(),
        focusedBorder: _inputBorder(color: AppColors.royalBlue, width: 1.5),
        errorBorder: _inputBorder(color: AppColors.danger),
        focusedErrorBorder:
            _inputBorder(color: AppColors.danger, width: 1.5),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: AppColors.inkBlack,
          foregroundColor: Colors.white,
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
        selectedItemColor: AppColors.royalBlue,
        unselectedItemColor: AppColors.textMuted,
        type: BottomNavigationBarType.fixed,
        elevation: 4,
      ),
      snackBarTheme: SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        backgroundColor: AppColors.inkBlack,
        contentTextStyle: const TextStyle(color: Colors.white),
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

  /// Alias so callers accessing dark inherit the Warm Paper design:
  static ThemeData get dark => paper;

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
