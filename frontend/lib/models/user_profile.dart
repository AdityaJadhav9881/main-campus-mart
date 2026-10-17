/// Student profile mirroring the backend `UserRead` schema.
///
/// Used for the Profile tab and the seller trust indicators on listings.
class UserProfile {
  const UserProfile({
    required this.id,
    required this.firebaseUid,
    required this.name,
    required this.email,
    required this.trustScore,
    required this.createdAt,
    this.status = 'active',
    this.collegeName,
    this.collegeCode,
    this.branch,
    this.academicYear,
  });

  /// Builds a [UserProfile] from the snake_case JSON produced by FastAPI.
  factory UserProfile.fromJson(Map<String, dynamic> json) {
    return UserProfile(
      id: json['id']?.toString() ?? '',
      firebaseUid: json['firebase_uid']?.toString() ?? '',
      name: json['name']?.toString() ?? 'Student',
      email: json['email']?.toString() ?? '',
      trustScore: _toDouble(json['trust_score']) ?? 5.0,
      status: json['status']?.toString() ?? 'active',
      collegeName: json['college_name']?.toString(),
      collegeCode: json['college_code']?.toString(),
      branch: json['branch']?.toString(),
      academicYear: json['academic_year']?.toString(),
      createdAt: DateTime.tryParse(json['created_at']?.toString() ?? '') ??
          DateTime.now(),
    );
  }

  final String id;
  final String firebaseUid;
  final String name;
  final String email;

  /// Moderation state: 'active' | 'blocked'.
  final String status;

  /// Reputation score on a 0-10 scale (neutral default 5.0).
  final double trustScore;

  final DateTime createdAt;

  /// CET college the student belongs to (null for pre-college-network accounts).
  final String? collegeName;

  /// DTE/CET institute code of [collegeName] (e.g. '6006').
  final String? collegeCode;

  /// Engineering department/branch (e.g. 'Computer / IT').
  final String? branch;

  /// Current academic year (e.g. 'SE (2nd Year)' or 'FE').
  final String? academicYear;

  /// Short display label for the college chip ("COEP" style).
  String? get collegeBadge {
    final name = collegeName?.trim() ?? '';
    if (name.isEmpty) return null;
    final head = name.split(',').first.trim();
    if (head.isEmpty) return null;
    return head.length <= 26 ? head : '${head.substring(0, 24)}…';
  }

  /// Serializes back to the API's snake_case contract.
  Map<String, dynamic> toJson() => <String, dynamic>{
        'id': id,
        'firebase_uid': firebaseUid,
        'name': name,
        'email': email,
        'trust_score': trustScore,
        'status': status,
        'college_name': collegeName,
        'college_code': collegeCode,
        'branch': branch,
        'academic_year': academicYear,
        'created_at': createdAt.toIso8601String(),
      };

  /// Accepts num, numeric String, or null when reading score-like fields.
  static double? _toDouble(dynamic value) {
    if (value == null) return null;
    if (value is num) return value.toDouble();
    return double.tryParse(value.toString());
  }
}
