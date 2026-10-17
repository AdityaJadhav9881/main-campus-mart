/// Strict-JSON result of POST /products/analyze-images (the 4-angle Vision
/// AI inspection) - mirrors `AnalyzeImagesResponse` on the backend.
class AiPhotoAnalysis {
  const AiPhotoAnalysis({
    required this.source,
    required this.title,
    required this.description,
    required this.category,
    required this.condition,
    required this.conditionNotes,
    required this.priceMinInr,
    required this.priceMaxInr,
    required this.suggestedPriceInr,
    required this.listedPriceInr,
    required this.aiTags,
    required this.imageUrls,
    this.brand,
    this.modelName,
    this.branch,
    this.academicYear,
    this.whatsappPitch,
    this.isValidProduct = true,
    this.rejectionReason,
    this.retailMrpInr,
  });

  factory AiPhotoAnalysis.fromJson(Map<String, dynamic> json) {
    List<String> tags = (json['ai_tags'] as List<dynamic>? ?? const <dynamic>[])
        .map((dynamic tag) => tag.toString())
        .where((tag) => tag.trim().isNotEmpty)
        .toList(growable: false);
    // The endpoint contract requires >=5 tags; be defensive anyway.
    if (tags.isEmpty) tags = <String>['campus sale', 'second hand'];

    return AiPhotoAnalysis(
      source: json['source']?.toString() ?? 'heuristic',
      brand: json['brand']?.toString(),
      modelName: json['model_name']?.toString(),
      branch: json['branch']?.toString(),
      academicYear: json['academic_year']?.toString(),
      whatsappPitch: json['whatsapp_pitch']?.toString(),
      title: json['title']?.toString() ?? '',
      description: json['description']?.toString() ?? '',
      category: json['category']?.toString() ?? 'Electronics',
      condition: json['condition']?.toString() ?? 'Good',
      conditionNotes: json['condition_notes']?.toString() ?? '',
      priceMinInr: (json['price_min_inr'] as num?)?.toDouble() ?? 0,
      priceMaxInr: (json['price_max_inr'] as num?)?.toDouble() ?? 0,
      suggestedPriceInr:
          (json['suggested_price_inr'] as num?)?.toDouble() ?? 0,
      listedPriceInr: (json['listed_price_inr'] as num?)?.toDouble() ?? 0,
      aiTags: tags,
      imageUrls: (json['image_urls'] as List<dynamic>? ?? const <dynamic>[])
          .map((dynamic url) => url.toString())
          .toList(growable: false),
      isValidProduct: json['is_valid_product'] as bool? ?? true,
      rejectionReason: json['rejection_reason']?.toString(),
      retailMrpInr: (json['retail_mrp_inr'] as num?)?.toDouble(),
    );
  }

  /// 'gemini' | 'openai' | 'groq' | 'openrouter' when a live vision model
  /// answered; 'heuristic' for the offline INR fallback.
  final String source;
  final String? brand;
  final String? modelName;
  final String? branch;
  final String? academicYear;
  final String? whatsappPitch;
  final String title;
  final String description;
  final String category;
  final String condition;
  final String conditionNotes;
  final double priceMinInr;
  final double priceMaxInr;
  final double suggestedPriceInr;
  final double listedPriceInr;
  final List<String> aiTags;
  final List<String> imageUrls;
  final bool isValidProduct;
  final String? rejectionReason;
  final double? retailMrpInr;

  bool get isLiveVision => source != 'heuristic';

  String get tagsCsv => aiTags.join(', ');
}
