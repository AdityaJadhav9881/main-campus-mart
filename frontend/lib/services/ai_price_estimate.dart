/// Client-side mirror of the backend's Price Prediction agent
/// (`backend/app/ai/price_agent.py`) used by the Sell screen's
/// "✨ AI Smart Estimate" banner.
///
/// The real verdict always comes from the server when the listing is
/// submitted; this preview simply shows students a fair-price range *before*
/// they commit, using the same condition table the AI applies:
///
///     base 100 x {new 1.0, like new 0.8, good 0.6, fair 0.4, poor 0.2}
///
/// Age and the title's category signal nudge the estimate the way the full
/// model will once the trained regressor lands (SWAP POINT on the backend).
abstract final class AiPriceEstimate {
  /// Identical to `price_agent.BASE_MOCK_PRICE`.
  static const double basePrice = 100.0;

  /// Identical to `price_agent.CONDITION_FACTORS`.
  static const Map<String, double> conditionFactors = <String, double>{
    'new': 1.00,
    'like new': 0.80,
    'good': 0.60,
    'fair': 0.40,
    'poor': 0.20,
  };

  static const double _defaultFactor = 0.50;

  /// Keywords that push a listing into the Academic bucket (book resale holds
  /// value better than consumer electronics).
  static const List<String> _academicKeywords = <String>[
    'book',
    'textbook',
    'notes',
    'math',
    'guide',
    'manual',
    'dictionary',
  ];

  /// Estimate half-window: the banner shows `center * 0.9 .. center * 1.1`.
  static const double _spread = 0.10;

  /// Cheap age parser: accepts "2 years", "8 months", "1 yr", "few months".
  static double _ageInYears(String age) {
    final value = age.trim().toLowerCase();
    if (value.isEmpty) return 0;
    final number = double.tryParse(
      value.replaceAll(RegExp(r'[^0-9.]'), ''),
    );
    if (number == null || number <= 0) return 0;
    if (value.contains('month') || value.contains('mo ')) return number / 12.0;
    if (value.contains('week') || value.contains('day')) return number / 52.0;
    return number; // bare number or "years"
  }

  /// Fair-value centre for the current form state (same math as the server
  /// for condition; age/category apply the modest depreciation the production
  /// model will learn).
  static double center({
    required String title,
    required String condition,
    required String age,
  }) {
    final normalized = condition.trim().toLowerCase();
    final factor = conditionFactors[normalized] ?? _defaultFactor;
    var value = basePrice * factor;

    final years = _ageInYears(age);
    if (years > 0) {
      final academic = _academicKeywords.any(
        (keyword) => title.trim().toLowerCase().contains(keyword),
      );
      // Textbooks depreciate slowly (~3%/yr); gadgets faster (~7%/yr).
      final annual = academic ? 0.03 : 0.07;
      value *= (1 - annual * years).clamp(0.40, 1.0).toDouble();
    }

    return double.parse(value.toStringAsFixed(2));
  }

  /// `(low, high)` inclusive fair-price range for the live form values.
  static ({double low, double high}) range({
    required String title,
    required String condition,
    required String age,
  }) {
    final mid = center(title: title, condition: condition, age: age);
    final low = double.parse((mid * (1 - _spread)).toStringAsFixed(2));
    final high = double.parse((mid * (1 + _spread)).toStringAsFixed(2));
    return (low: low, high: high);
  }

  /// Suggested condition label the AI is most likely to confirm, purely so
  /// the banner can explain itself ("condition: Good → factor 0.60").
  static double factorFor(String condition) {
    return conditionFactors[condition.trim().toLowerCase()] ?? _defaultFactor;
  }
}
