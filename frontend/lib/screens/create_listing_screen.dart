import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:provider/provider.dart';

import '../providers/auth_provider.dart';
import '../providers/product_provider.dart';
import '../services/api_service.dart';
import '../widgets/app_theme.dart';

/// Tab 2 - Sell / Create Listing.
///
/// Collects the listing details, then hands them to POST /products/ where the
/// LangGraph AI pipeline derives the category, suggests a fair price, and runs
/// the fraud check. Success shows an animated snackbar with the AI verdict
/// before returning to the feed.
class CreateListingScreen extends StatefulWidget {
  const CreateListingScreen({super.key, required this.onListingCreated});

  /// Called after a successful creation so the shell can switch to Tab 1.
  final VoidCallback onListingCreated;

  @override
  State<CreateListingScreen> createState() => _CreateListingScreenState();
}

class _CreateListingScreenState extends State<CreateListingScreen> {
  final GlobalKey<FormState> _formKey = GlobalKey<FormState>();
  final TextEditingController _titleController = TextEditingController();
  final TextEditingController _descriptionController = TextEditingController();
  final TextEditingController _ageController = TextEditingController();
  final TextEditingController _priceController = TextEditingController();
  final TextEditingController _imageController = TextEditingController();

  static const List<String> _conditions = <String>[
    'Like New',
    'Good',
    'Fair',
    'Poor',
  ];
  String _condition = _conditions.first;

  /// True while the picked photo is in flight to POST /products/upload-image/.
  bool _isUploading = false;

  @override
  void dispose() {
    _titleController.dispose();
    _descriptionController.dispose();
    _ageController.dispose();
    _priceController.dispose();
    _imageController.dispose();
    super.dispose();
  }

  /// Phase 6 cloud pipeline: gallery pick -> POST /products/upload-image/ ->
  /// returned CDN URL lands in the image field (used as `image_url` on submit).
  Future<void> _pickAndUploadImage() async {
    if (_isUploading) return;

    // Capture everything needed AFTER awaits before leaving this context.
    final messenger = ScaffoldMessenger.of(context);
    final auth = context.read<AuthProvider>();

    final picked = await ImagePicker().pickImage(
      source: ImageSource.gallery,
      maxWidth: 1600,
      maxHeight: 1600,
      imageQuality: 85,
    );
    if (picked == null) return; // user cancelled the picker

    setState(() => _isUploading = true);
    try {
      final bytes = await picked.readAsBytes();
      final imageUrl = await ApiService.instance.uploadListingImage(
        bytes: bytes,
        filename: picked.name,
        token: auth.token,
      );
      if (!mounted) return;
      setState(() => _imageController.text = imageUrl);
      messenger.showSnackBar(
        SnackBar(
          backgroundColor: AppColors.success.withOpacity(0.92),
          content: const Text(
            'Photo uploaded to the cloud',
            style: TextStyle(color: Colors.black, fontWeight: FontWeight.w700),
          ),
        ),
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      messenger.showSnackBar(
        SnackBar(
          backgroundColor: AppColors.danger.withOpacity(0.92),
          content: Text(
            error.message,
            style: const TextStyle(color: Colors.black),
          ),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      messenger.showSnackBar(
        SnackBar(
          backgroundColor: AppColors.danger.withOpacity(0.92),
          content: Text(
            'Photo upload failed: $error',
            style: const TextStyle(color: Colors.black),
          ),
        ),
      );
    } finally {
      if (mounted) setState(() => _isUploading = false);
    }
  }

  Future<void> _submit() async {
    final form = _formKey.currentState;
    if (form == null || !form.validate()) return;

    // Capture everything needed AFTER the await before leaving this context.
    final provider = context.read<ProductProvider>();
    final messenger = ScaffoldMessenger.of(context);

    final payload = <String, dynamic>{
      'title': _titleController.text.trim(),
      'description': _descriptionController.text.trim(),
      // AI input only - never persisted to the products table.
      'age': _ageController.text.trim(),
      'condition': _condition,
      'image_url': _imageController.text.trim(),
      'listed_price': double.parse(_priceController.text.trim()),
      // `category` omitted on purpose: the AI pipeline owns it (Phase 3).
    };

    final created = await provider.addProduct(payload);
    if (!mounted) return;

    if (created != null) {
      final suggested = created.suggestedPrice;
      messenger.showSnackBar(
        SnackBar(
          backgroundColor: AppColors.success.withOpacity(0.92),
          content: Text(
            'AI analysis complete - ${created.category}'
            '${suggested == null ? '' : ' - suggested \$${suggested.toStringAsFixed(2)}'}',
            style: const TextStyle(
              color: Colors.black,
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
      );
      _resetForm();
      widget.onListingCreated();
    } else {
      messenger.showSnackBar(
        SnackBar(
          backgroundColor: AppColors.danger.withOpacity(0.92),
          content: Text(
            provider.errorMessage ?? 'Listing creation failed. Try again.',
            style: const TextStyle(color: Colors.black),
          ),
        ),
      );
    }
  }

  void _resetForm() {
    _formKey.currentState?.reset();
    _titleController.clear();
    _descriptionController.clear();
    _ageController.clear();
    _priceController.clear();
    _imageController.clear();
    setState(() => _condition = _conditions.first);
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<ProductProvider>();
    final isSubmitting = provider.isLoading;

    return Scaffold(
      appBar: AppBar(
        titleSpacing: 16,
        title: const Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Sell on CampusMart',
              style: TextStyle(
                fontSize: 17,
                fontWeight: FontWeight.w800,
                color: AppColors.textPrimary,
              ),
            ),
            Text(
              'AI-assisted pricing & safety check',
              style: TextStyle(
                fontSize: 11.5,
                fontWeight: FontWeight.w500,
                color: AppColors.cyanAccent,
              ),
            ),
          ],
        ),
      ),
      body: SafeArea(
        child: Form(
          key: _formKey,
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
            children: [
              _buildImageSection(),
              const SizedBox(height: 20),
              TextFormField(
                controller: _titleController,
                enabled: !isSubmitting,
                textCapitalization: TextCapitalization.sentences,
                decoration: const InputDecoration(
                  labelText: 'Product Title',
                  hintText: 'e.g. Calculus Textbook, 8th Edition',
                ),
                validator: (value) {
                  final text = (value ?? '').trim();
                  if (text.isEmpty) return 'Title is required';
                  if (text.length > 200) return 'Max 200 characters';
                  return null;
                },
              ),
              const SizedBox(height: 16),
              TextFormField(
                controller: _descriptionController,
                enabled: !isSubmitting,
                minLines: 3,
                maxLines: 6,
                textCapitalization: TextCapitalization.sentences,
                decoration: const InputDecoration(
                  labelText: 'Description',
                  hintText: 'Describe wear, included accessories, edition...',
                  alignLabelWithHint: true,
                ),
                validator: (value) =>
                    (value ?? '').trim().isEmpty ? 'Description is required' : null,
              ),
              const SizedBox(height: 16),
              Row(
                children: [
                  Expanded(
                    child: TextFormField(
                      controller: _ageController,
                      enabled: !isSubmitting,
                      decoration: const InputDecoration(
                        labelText: 'Original Age',
                        hintText: 'e.g. 2 years',
                      ),
                      validator: (value) =>
                          (value ?? '').trim().isEmpty ? 'Age is required' : null,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: TextFormField(
                      controller: _priceController,
                      enabled: !isSubmitting,
                      keyboardType:
                          const TextInputType.numberWithOptions(decimal: true),
                      decoration: const InputDecoration(
                        labelText: 'Listed Price',
                        hintText: 'e.g. 45.00',
                        prefixText: '\$ ',
                      ),
                      validator: (value) {
                        final price = double.tryParse((value ?? '').trim());
                        if (price == null) return 'Enter a valid price';
                        if (price <= 0) return 'Must be > 0';
                        return null;
                      },
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              DropdownButtonFormField<String>(
                value: _condition,
                dropdownColor: AppColors.surfaceHigh,
                decoration: const InputDecoration(labelText: 'Condition'),
                items: _conditions
                    .map(
                      (condition) => DropdownMenuItem<String>(
                        value: condition,
                        child: Text(condition),
                      ),
                    )
                    .toList(),
                onChanged: isSubmitting
                    ? null
                    : (value) =>
                        setState(() => _condition = value ?? _condition),
              ),
              const SizedBox(height: 24),
              FilledButton(
                onPressed: isSubmitting ? null : _submit,
                child: isSubmitting
                    ? const SizedBox(
                        width: 22,
                        height: 22,
                        child: CircularProgressIndicator(
                          strokeWidth: 2.6,
                          color: Colors.black,
                        ),
                      )
                    : const Text('Submit for AI Analysis'),
              ),
              if (isSubmitting) ...[
                const SizedBox(height: 18),
                const _AiAnalysisLoading(),
              ],
            ],
          ),
        ),
      ),
    );
  }

  /// Cloud photo picker + live URL preview (Phase 6).
  /// Tapping the tile opens the gallery; the picked photo uploads to
  /// POST /products/upload-image/ and its CDN URL fills the field below
  /// (which stays editable as a manual-URL fallback).
  Widget _buildImageSection() {
    final previewUrl = _imageController.text.trim();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'PHOTO',
          style: TextStyle(
            color: AppColors.textMuted,
            fontSize: 11,
            fontWeight: FontWeight.w700,
            letterSpacing: 1.1,
          ),
        ),
        const SizedBox(height: 8),
        InkWell(
          onTap: _isUploading ? null : _pickAndUploadImage,
          borderRadius: BorderRadius.circular(14),
          child: Container(
            height: 150,
            width: double.infinity,
            clipBehavior: Clip.antiAlias,
            decoration: BoxDecoration(
              color: AppColors.surface,
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: AppColors.hairline),
            ),
            child: Stack(
              fit: StackFit.expand,
              children: [
                previewUrl.isEmpty
                    ? const _ImagePlaceholder()
                    : Image.network(
                        previewUrl,
                        fit: BoxFit.cover,
                        errorBuilder: (context, error, stackTrace) =>
                            const _ImagePlaceholder(),
                      ),
                if (_isUploading)
                  Container(
                    color: AppColors.voidBlack.withOpacity(0.65),
                    alignment: Alignment.center,
                    child: const Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        SizedBox(
                          width: 26,
                          height: 26,
                          child: CircularProgressIndicator(
                            strokeWidth: 2.6,
                            color: AppColors.cyanAccent,
                          ),
                        ),
                        SizedBox(height: 10),
                        Text(
                          'Uploading to cloud...',
                          style: TextStyle(
                            color: AppColors.textPrimary,
                            fontSize: 12.5,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 6),
        Text(
          previewUrl.isEmpty
              ? 'Tap the photo area to pick & upload from your gallery'
              : 'Tap the photo to replace it',
          style: const TextStyle(
            color: AppColors.textMuted,
            fontSize: 11.5,
          ),
        ),
        const SizedBox(height: 10),
        TextFormField(
          controller: _imageController,
          enabled: !context.watch<ProductProvider>().isLoading && !_isUploading,
          keyboardType: TextInputType.url,
          onChanged: (_) => setState(() {}),
          decoration: const InputDecoration(
            labelText: 'Image URL',
            hintText: 'https://... (or upload above)',
            prefixIcon: Icon(Icons.link_outlined, size: 20),
          ),
          validator: (value) {
            final url = (value ?? '').trim();
            if (url.isEmpty) return 'Upload a photo or enter an image URL';
            final uri = Uri.tryParse(url);
            if (uri == null || !uri.hasScheme || !uri.hasAuthority) {
              return 'Enter a full URL (https://...)';
            }
            return null;
          },
        ),
      ],
    );
  }
}

/// Empty-state shown before a photo is picked (tapping triggers the picker).
class _ImagePlaceholder extends StatelessWidget {
  const _ImagePlaceholder();

  @override
  Widget build(BuildContext context) {
    return const Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Icon(Icons.add_a_photo_outlined, size: 30, color: AppColors.textMuted),
        SizedBox(height: 8),
        Text(
          'Tap to choose & upload a photo',
          style: TextStyle(color: AppColors.textMuted, fontSize: 12),
        ),
      ],
    );
  }
}

/// Spinning, softly pulsing loader with the AI status copy required by spec.
class _AiAnalysisLoading extends StatefulWidget {
  const _AiAnalysisLoading();

  @override
  State<_AiAnalysisLoading> createState() => _AiAnalysisLoadingState();
}

class _AiAnalysisLoadingState extends State<_AiAnalysisLoading>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 850),
  )..repeat(reverse: true);

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return FadeTransition(
      opacity: Tween<double>(begin: 0.5, end: 1.0).animate(_controller),
      child: const Column(
        children: [
          SizedBox(
            width: 26,
            height: 26,
            child: CircularProgressIndicator(
              strokeWidth: 2.8,
              color: AppColors.cyanAccent,
            ),
          ),
          SizedBox(height: 14),
          Text(
            'AI Orchestrator is analyzing listing & verifying price...',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: AppColors.cyanAccent,
              fontSize: 13,
              fontWeight: FontWeight.w600,
              height: 1.4,
            ),
          ),
        ],
      ),
    );
  }
}
