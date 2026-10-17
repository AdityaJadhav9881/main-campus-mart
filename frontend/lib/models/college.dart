// Maharashtra CET Cell college directory models (mirror the FastAPI
// `CollegeRead` / `CollegeSearchResponse` schemas served by GET /colleges).

/// One college row returned by GET /colleges (CET directory or custom entry).
class College {
  const College({
    required this.code,
    required this.name,
    required this.shortName,
    required this.city,
    this.aliases = const <String>[],
    this.custom = false,
  });

  factory College.fromJson(Map<String, dynamic> json) {
    return College(
      code: json['code']?.toString() ?? '',
      name: json['name']?.toString() ?? '',
      shortName: json['short_name']?.toString() ?? '',
      city: json['city']?.toString() ?? '',
      aliases: (json['aliases'] as List<dynamic>? ?? const <dynamic>[])
          .map((dynamic alias) => alias.toString())
          .where((alias) => alias.isNotEmpty)
          .toList(growable: false),
      custom: json['custom'] == true,
    );
  }

  /// DTE/CET Cell institute code ("6006"); empty for custom entries.
  final String code;

  /// Official college name ("COEP Technological University, Pune").
  final String name;

  /// Student shorthand ("COEP", "VJTI").
  final String shortName;

  final String city;

  /// Extra search aliases students type.
  final List<String> aliases;

  /// True when this is a typed-in unlisted college (not from the directory).
  final bool custom;

  /// Badge label: "CET 6006" for directory entries, else "Verified Campus"
  /// only when the backend marked it verified (custom = unverified text).
  String? get cetBadge => code.trim().isEmpty ? null : 'CET ${code.trim()}';
}

/// GET /colleges response: ranked matches + the picker's city filter list.
class CollegeSearchResult {
  const CollegeSearchResult({
    required this.colleges,
    this.cities = const <String>[],
  });

  factory CollegeSearchResult.fromJson(Map<String, dynamic> json) {
    return CollegeSearchResult(
      colleges: (json['colleges'] as List<dynamic>? ?? const <dynamic>[])
          .whereType<Map<String, dynamic>>()
          .map(College.fromJson)
          .toList(growable: false),
      cities: (json['cities'] as List<dynamic>? ?? const <dynamic>[])
          .map((dynamic city) => city.toString())
          .where((city) => city.isNotEmpty)
          .toList(growable: false),
    );
  }

  final List<College> colleges;

  /// Canonical city pill list (first entry is "All").
  final List<String> cities;
}
