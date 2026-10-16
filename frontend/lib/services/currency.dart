/// Indian Rupee formatting shared by every Campus Mart Ai screen.
///
/// The marketplace prices exclusively in ₹ (the backend never returns USD),
/// so all money strings go through [formatInr] - which also applies Indian
/// digit grouping (1,25,000 style) the way students expect to see prices.
library;

/// Groups an integer digit string using the Indian system:
/// 4500 -> "4,500" · 125000 -> "1,25,000" · 12345678 -> "1,23,45,678".
String _groupIndian(String digits) {
  if (digits.length <= 3) return digits;
  final last3 = digits.substring(digits.length - 3);
  var rest = digits.substring(0, digits.length - 3);
  final parts = <String>[];
  while (rest.length > 2) {
    parts.insert(0, rest.substring(rest.length - 2));
    rest = rest.substring(0, rest.length - 2);
  }
  if (rest.isNotEmpty) parts.insert(0, rest);
  return '${parts.join(',')},$last3';
}

/// Formats [value] as Indian Rupees: `formatInr(125000)` -> `"₹1,25,000"`.
///
/// Whole rupees show no decimals (`₹850`); paise are kept when present
/// (`₹850.50`). Negative amounts render as `-₹100`.
String formatInr(num value) {
  final negative = value.isNegative;
  final amount = value.abs();
  final whole = amount.floor();
  final fraction = amount - whole;

  var out = _groupIndian(whole.toString());
  if (fraction > 0) {
    final paise = (fraction * 100).round().toString().padLeft(2, '0');
    out = '$out.$paise';
  }
  return '${negative ? '-' : ''}₹$out';
}
