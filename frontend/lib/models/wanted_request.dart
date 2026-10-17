/// Data model for a Want to Buy (WTB) request on the campus request board.
class WantedRequest {
  const WantedRequest({
    required this.id,
    required this.userId,
    required this.requesterName,
    required this.requesterEmail,
    required this.title,
    required this.createdAt,
    this.collegeName,
    this.collegeCode,
    this.description = '',
    this.maxBudget,
    this.category,
    this.branch,
    this.academicYear,
    this.urgency = 'medium',
    this.status = 'open',
    this.aiKeywords,
  });

  factory WantedRequest.fromJson(Map<String, dynamic> json) {
    return WantedRequest(
      id: json['id']?.toString() ?? '',
      userId: json['user_id']?.toString() ?? '',
      requesterName: json['requester_name']?.toString() ?? 'Student',
      requesterEmail: json['requester_email']?.toString() ?? '',
      collegeName: json['college_name']?.toString(),
      collegeCode: json['college_code']?.toString(),
      title: json['title']?.toString() ?? 'Wanted Item',
      description: json['description']?.toString() ?? '',
      maxBudget: _toDouble(json['max_budget']),
      category: json['category']?.toString(),
      branch: json['branch']?.toString(),
      academicYear: json['academic_year']?.toString(),
      urgency: json['urgency']?.toString() ?? 'medium',
      status: json['status']?.toString() ?? 'open',
      aiKeywords: json['ai_keywords']?.toString(),
      createdAt: DateTime.tryParse(json['created_at']?.toString() ?? '') ??
          DateTime.now(),
    );
  }

  final String id;
  final String userId;
  final String requesterName;
  final String requesterEmail;
  final String? collegeName;
  final String? collegeCode;
  final String title;
  final String description;
  final double? maxBudget;
  final String? category;
  final String? branch;
  final String? academicYear;
  final String urgency;
  final String status;
  final String? aiKeywords;
  final DateTime createdAt;

  Map<String, dynamic> toJson() => {
        'id': id,
        'user_id': userId,
        'requester_name': requesterName,
        'requester_email': requesterEmail,
        'college_name': collegeName,
        'college_code': collegeCode,
        'title': title,
        'description': description,
        'max_budget': maxBudget,
        'category': category,
        'branch': branch,
        'academic_year': academicYear,
        'urgency': urgency,
        'status': status,
        'ai_keywords': aiKeywords,
        'created_at': createdAt.toIso8601String(),
      };

  static double? _toDouble(dynamic value) {
    if (value == null) return null;
    if (value is num) return value.toDouble();
    return double.tryParse(value.toString());
  }
}

