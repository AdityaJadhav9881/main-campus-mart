/// Client-side mirror of the backend's Price Prediction agent
/// (`backend/app/ai/price_agent.py`) used by the Sell screen's
/// "✨ AI Smart Estimate" banner.
///
/// The real verdict always comes from the server when the listing is
/// submitted; this preview simply shows students a fair-price range *before*
/// they commit, using the same category + condition table the AI applies
/// (all amounts in INDIAN RUPEES):
///
///     base by category: Electronics ₹1500 · Academic Material ₹500
///                       Lab Gear ₹600 · Stationery ₹100 · Hostel ₹400
///     x {new 1.0, like new 0.8, good 0.6, fair 0.4, poor 0.2}
///
/// Age and the title's category signal nudge the estimate the way the full
/// model will once the trained regressor lands (SWAP POINT on the backend).
abstract final class AiPriceEstimate {
  /// Identical to `price_agent.CATEGORY_BASE_PRICE_INR`.
  static const Map<String, double> categoryBasePriceInr = <String, double>{
    'Electronics': 1500.0,
    'Academic Material': 500.0,
    'Lab Gear & Instruments': 600.0,
    'Stationery': 100.0,
    'Hostel & Lifestyle': 400.0,
  };

  /// Identical to `price_agent.BASE_MOCK_PRICE` (unknown category default).
  static const double basePrice = 500.0;

  /// Identical to `price_agent.CONDITION_FACTORS`.
  static const Map<String, double> conditionFactors = <String, double>{
    'new': 1.00,
    'like new': 0.80,
    'good': 0.60,
    'fair': 0.40,
    'poor': 0.20,
  };

  static const double _defaultFactor = 0.50;

  /// Keyword -> category rules, ordered like the backend listing agent so
  /// the preview lands in the same bucket the AI will confirm.
  static const List<(List<String>, String)> _categoryRules =
      <(List<String>, String)>[
    (
      ['book', 'textbook', 'math', 'notes', 'manual', 'guide', 'dictionary',
       'edition', 'semester', 'syllabus', 'reference'],
      'Academic Material',
    ),
    (
      ['multimeter', 'drafter', 'oscilloscope', 'solder', 'lab', 'protractor',
       'vernier', 'calliper', 'caliper', 'microscope', 'instrument', 'sensor',
       'breadboard'],
      'Lab Gear & Instruments',
    ),
    (
      ['pen', 'pencil', 'marker', 'highlighter', 'refill', 'sticky',
       'geometry', 'eraser', 'stapler', 'ruler'],
      'Stationery',
    ),
    (
      ['bedsheet', 'pillow', 'mug', 'lamp', 'hostel', 'curtain', 'mattress',
       'bucket', 'fan', 'mat', 'hanger'],
      'Hostel & Lifestyle',
    ),
    (
      ['laptop', 'phone', 'calculator', 'speaker', 'headphone', 'earbud',
       'camera', 'watch', 'drone', 'esp32', 'arduino', 'raspberry', 'battery',
       'charger', 'monitor', 'keyboard', 'mouse', 'tablet', 'bluetooth',
       'electronics', 'usb', 'projector'],
      'Electronics',
    ),
  ];

  /// Estimate half-window: the banner shows `center * 0.9 .. center * 1.1`.
  static const double _spread = 0.10;

  /// Resolves the marketplace category for a title/description, mirroring
  /// `listing_agent.listing_agent` (first keyword match wins, else default).
  static String categoryFor(String text) {
    final haystack = text.trim().toLowerCase();
    for (final (keywords, category) in _categoryRules) {
      if (keywords.any(haystack.contains)) return category;
    }
    return 'Electronics';
  }

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
  /// for category + condition; age applies the modest depreciation the
  /// production model will learn).
  static double center({
    required String title,
    required String condition,
    required String age,
  }) {
    final normalized = condition.trim().toLowerCase();
    final factor = conditionFactors[normalized] ?? _defaultFactor;
    var value = (categoryBasePriceInr[categoryFor(title)] ?? basePrice) * factor;

    final years = _ageInYears(age);
    if (years > 0) {
      final category = categoryFor(title);
      final academic = category == 'Academic Material' ||
          category == 'Stationery';
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
