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

  /// Serializes back to the API's snake_case contract.
  Map<String, dynamic> toJson() => <String, dynamic>{
        'id': id,
        'firebase_uid': firebaseUid,
        'name': name,
        'email': email,
        'trust_score': trustScore,
        'status': status,
        'created_at': createdAt.toIso8601String(),
      };

  /// Accepts num, numeric String, or null when reading score-like fields.
  static double? _toDouble(dynamic value) {
    if (value == null) return null;
    if (value is num) return value.toDouble();
    return double.tryParse(value.toString());
  }
}
