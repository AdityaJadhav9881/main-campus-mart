import 'package:flutter/material.dart';

import 'app_theme.dart';

/// Small tinted pill rendering the seller-declared item condition
/// (e.g. "LIKE NEW") with a color that communicates quality at a glance.
class ConditionBadge extends StatelessWidget {
  const ConditionBadge({
    super.key,
    required this.condition,
    this.compact = false,
  });

  final String condition;
  final bool compact;

  Color get _color {
    switch (condition.toLowerCase()) {
      case 'new':
      case 'like new':
        return AppColors.success;
      case 'good':
        return AppColors.cyanAccent;
      case 'fair':
        return AppColors.warning;
      case 'poor':
        return AppColors.danger;
      default:
        return AppColors.textMuted;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: compact ? 8 : 10,
        vertical: compact ? 3 : 4,
      ),
      decoration: BoxDecoration(
        color: _color.withOpacity(0.12),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: _color.withOpacity(0.55), width: 0.8),
      ),
      child: Text(
        condition.toUpperCase(),
        style: TextStyle(
          color: _color,
          fontSize: compact ? 9 : 10,
          fontWeight: FontWeight.w700,
          letterSpacing: 0.6,
        ),
      ),
    );
  }
}
