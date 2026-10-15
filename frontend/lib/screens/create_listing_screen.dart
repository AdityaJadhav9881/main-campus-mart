import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:provider/provider.dart';

import '../providers/auth_provider.dart';
import '../providers/product_provider.dart';
import '../services/ai_price_estimate.dart';
import '../services/api_service.dart';
import '../widgets/app_theme.dart';

/// Tab 2 - "Sell on Campus Mart Ai".
///
/// Collects the listing details, then hands them to POST /products/ where the
/// LangGraph AI pipeline derives the category, suggests a fair price, and runs
/// the fraud check. Highlights:
///   * Camera **or** Gallery photo pick with a full-bleed preview.
///   * The raw "Image URL" field is hidden behind a "Paste URL instead" link.
///   * A live "✨ AI Smart Estimate" banner mirrors the backend price agent so
///     students see a fair-price range before submitting.
///   * The submit button sits well above the bottom navigation bar so
///     floating snackbars never cover it.
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

  /// Advanced escape hatch: the developer-facing "Image URL" field stays
  /// hidden unless the student taps "Paste URL instead".
  bool _showUrlField = false;

  /// Explicit camera/gallery choice surfaced as a bottom sheet.
  ImageSource? _lastSource;

  /// Clearance so the submit button never hides behind the tab shell's
  /// bottom navigation bar (or a floating snackbar riding on top of it).
  static const double _bottomNavClearance = 96;

  @override
  void initState() {
    super.initState();
    // Rebuild on every keystroke so the AI Smart Estimate stays live.
    _titleController.addListener(_onFormChanged);
    _ageController.addListener(_onFormChanged);
    _priceController.addListener(_onFormChanged);
  }

  @override
  void dispose() {
    _titleController.removeListener(_onFormChanged);
    _ageController.removeListener(_onFormChanged);
    _priceController.removeListener(_onFormChanged);
    _titleController.dispose();
    _descriptionController.dispose();
    _ageController.dispose();
    _priceController.dispose();
    _imageController.dispose();
    super.dispose();
  }

  void _onFormChanged() {
    if (!mounted) return;
    setState(() {}); // cheap: only re-runs the estimate banner build
  }

  /// Bottom-sheet choice between taking a photo and picking one.
  Future<void> _choosePhotoSource() async {
    if (_isUploading) return;
    final source = await showModalBottomSheet<ImageSource>(
      context: context,
      backgroundColor: AppColors.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (sheetContext) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Padding(
              padding: EdgeInsets.fromLTRB(20, 18, 20, 12),
              child: Text(
                'ADD A PHOTO',
                style: TextStyle(
                  color: AppColors.textMuted,
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 1.2,
                ),
              ),
            ),
            ListTile(
              leading: const Icon(Icons.photo_camera_outlined,
                  color: AppColors.cyanAccent),
              title: const Text('Take a photo',
                  style: TextStyle(color: AppColors.textPrimary)),
              subtitle: const Text('Use the camera right now',
                  style: TextStyle(color: AppColors.textMuted, fontSize: 12)),
              onTap: () => Navigator.of(sheetContext).pop(ImageSource.camera),
            ),
            ListTile(
              leading: const Icon(Icons.photo_library_outlined,
                  color: AppColors.cyanAccent),
              title: const Text('Choose from gallery',
                  style: TextStyle(color: AppColors.textPrimary)),
              subtitle: const Text('Pick an existing picture',
                  style: TextStyle(color: AppColors.textMuted, fontSize: 12)),
              onTap: () => Navigator.of(sheetContext).pop(ImageSource.gallery),
            ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
    if (source != null) await _pickAndUploadImage(source);
  }

  /// Phase 6 cloud pipeline: pick -> POST /products/upload-image/ ->
  /// returned CDN URL lands in the image field (used as `image_url` on submit).
  Future<void> _pickAndUploadImage(ImageSource source) async {
    if (_isUploading) return;

    // Capture everything needed AFTER awaits before leaving this context.
    final messenger = ScaffoldMessenger.of(context);
    final auth = context.read<AuthProvider>();

    final picked = await ImagePicker().pickImage(
      source: source,
      maxWidth: 1600,
      maxHeight: 1600,
      imageQuality: 85,
    );
    if (picked == null) return; // user cancelled the picker

    _lastSource = source;
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

    final imageUrl = _imageController.text.trim();
    if (imageUrl.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          backgroundColor: AppColors.warning.withOpacity(0.94),
          content: const Text(
            'Add a photo (camera or gallery) before submitting.',
            style: TextStyle(color: Colors.black, fontWeight: FontWeight.w700),
          ),
        ),
      );
      return;
    }

    // Capture everything needed AFTER the await before leaving this context.
    final provider = context.read<ProductProvider>();
    final messenger = ScaffoldMessenger.of(context);

    final payload = <String, dynamic>{
      'title': _titleController.text.trim(),
      'description': _descriptionController.text.trim(),
      // AI input only - never persisted to the products table.
      'age': _ageController.text.trim(),
      'condition': _condition,
      'image_url': imageUrl,
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
    setState(() {
      _condition = _conditions.first;
      _showUrlField = false;
      _lastSource = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<ProductProvider>();
    final isSubmitting = provider.isLoading;
    final bottomInset = MediaQuery.paddingOf(context).bottom;

    return Scaffold(
      appBar: AppBar(
        titleSpacing: 16,
        title: const Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Sell on Campus Mart Ai',
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
        top: false,
        child: Form(
          key: _formKey,
          child: ListView(
            // Bottom clearance keeps the submit button far above the tab
            // shell's navigation bar (and any floating snackbar above it).
            padding: EdgeInsets.fromLTRB(
              16,
              8,
              16,
              32 + _bottomNavClearance + bottomInset,
            ),
            children: [
              _buildImageSection(),
              const SizedBox(height: 16),
              _AiEstimateBanner(
                title: _titleController.text,
                condition: _condition,
                age: _ageController.text,
              ),
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
              const SizedBox(height: 14),
              _buildAdvancedUrlToggle(isSubmitting),
              const SizedBox(height: 28),
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

  /// "Paste URL instead" link that reveals the raw Image URL field.
  Widget _buildAdvancedUrlToggle(bool isSubmitting) {
    if (_showUrlField) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          TextFormField(
            controller: _imageController,
            enabled: !isSubmitting && !_isUploading,
            keyboardType: TextInputType.url,
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(
              labelText: 'Image URL',
              hintText: 'https://... (or upload a photo above)',
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
          const SizedBox(height: 6),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              onPressed: () => setState(() => _showUrlField = false),
              icon: const Icon(Icons.visibility_off_outlined, size: 15),
              label: const Text('Hide URL field'),
              style: TextButton.styleFrom(
                foregroundColor: AppColors.textMuted,
                padding: const EdgeInsets.symmetric(horizontal: 4),
              ),
            ),
          ),
        ],
      );
    }

    return Align(
      alignment: Alignment.centerLeft,
      child: TextButton.icon(
        onPressed: () => setState(() => _showUrlField = true),
        icon: const Icon(Icons.link_outlined, size: 15),
        label: const Text('Paste URL instead'),
        style: TextButton.styleFrom(
          foregroundColor: AppColors.textMuted,
          padding: const EdgeInsets.symmetric(horizontal: 4),
        ),
      ),
    );
  }

  /// Photo picker with full-bleed preview once a photo is on board.
  Widget _buildImageSection() {
    final previewUrl = _imageController.text.trim();
    final hasPhoto = previewUrl.isNotEmpty;

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
        Container(
          height: hasPhoto ? 230 : 160,
          width: double.infinity,
          clipBehavior: Clip.antiAlias,
          decoration: BoxDecoration(
            color: AppColors.surface,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(
              color: hasPhoto
                  ? AppColors.cyanAccent.withOpacity(0.4)
                  : AppColors.hairline,
            ),
          ),
          child: Stack(
            fit: StackFit.expand,
            children: [
              hasPhoto
                  ? Image.network(
                      previewUrl,
                      fit: BoxFit.cover,
                      width: double.infinity,
                      height: double.infinity,
                      errorBuilder: (context, error, stackTrace) =>
                          const _ImagePlaceholder(),
                    )
                  : const _ImagePlaceholder(),

              // Full-bleed camera / gallery chooser when empty.
              if (!hasPhoto)
                Positioned.fill(
                  child: Material(
                    color: Colors.transparent,
                    child: InkWell(
                      onTap: _isUploading ? null : _choosePhotoSource,
                      child: const SizedBox.expand(),
                    ),
                  ),
                ),

              // "Change Photo" bar over the preview.
              if (hasPhoto)
                Positioned(
                  left: 12,
                  right: 12,
                  bottom: 12,
                  child: Row(
                    children: [
                      Expanded(
                        child: _PhotoActionButton(
                          label: 'Change Photo',
                          icon: Icons.cameraswitch_outlined,
                          filled: true,
                          onTap: _isUploading ? null : _choosePhotoSource,
                        ),
                      ),
                      const SizedBox(width: 10),
                      _PhotoActionButton(
                        label: 'Remove',
                        icon: Icons.close,
                        filled: false,
                        onTap: _isUploading
                            ? null
                            : () => setState(() {
                                  _imageController.clear();
                                  _lastSource = null;
                                }),
                      ),
                    ],
                  ),
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
        const SizedBox(height: 8),
        Text(
          hasPhoto
              ? 'Photo ready$_sourceHint — tap Change Photo to replace it.'
              : 'Take a photo with the camera or pick one from your gallery.',
          style: const TextStyle(
            color: AppColors.textMuted,
            fontSize: 11.5,
          ),
        ),
      ],
    );
  }

  String get _sourceHint {
    switch (_lastSource) {
      case ImageSource.camera:
        return ' (from camera)';
      case ImageSource.gallery:
        return ' (from gallery)';
      case null:
        return '';
    }
  }
}

/// Small overlay button used on the photo preview.
class _PhotoActionButton extends StatelessWidget {
  const _PhotoActionButton({
    required this.label,
    required this.icon,
    required this.filled,
    required this.onTap,
  });

  final String label;
  final IconData icon;
  final bool filled;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Container(
          height: 40,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: filled
                ? AppColors.cyanAccent
                : Colors.black.withOpacity(0.72),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(
              color: filled
                  ? AppColors.cyanAccent
                  : Colors.white.withOpacity(0.35),
            ),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 16, color: filled ? Colors.black : Colors.white),
              const SizedBox(width: 6),
              Text(
                label,
                style: TextStyle(
                  color: filled ? Colors.black : Colors.white,
                  fontSize: 12.5,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Empty-state shown before a photo is picked.
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
          'Tap to add a photo',
          style: TextStyle(color: AppColors.textMuted, fontSize: 12),
        ),
        SizedBox(height: 4),
        Text(
          'Camera or gallery',
          style: TextStyle(color: AppColors.textMuted, fontSize: 11),
        ),
      ],
    );
  }
}

/// Live "✨ AI Smart Estimate" preview banner.
///
/// Re-uses [AiPriceEstimate], the client mirror of the backend price agent,
/// so the range students see updates as they type the title, age and pick a
/// condition - before anything is submitted.
class _AiEstimateBanner extends StatelessWidget {
  const _AiEstimateBanner({
    required this.title,
    required this.condition,
    required this.age,
  });

  final String title;
  final String condition;
  final String age;

  @override
  Widget build(BuildContext context) {
    final range = AiPriceEstimate.range(
      title: title,
      condition: condition,
      age: age,
    );
    final factor = AiPriceEstimate.factorFor(condition);
    final hasInput = title.trim().isNotEmpty || age.trim().isNotEmpty;

    return AnimatedContainer(
      duration: const Duration(milliseconds: 250),
      curve: Curves.easeOut,
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.cyanAccent.withOpacity(hasInput ? 0.10 : 0.05),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.cyanAccent.withOpacity(0.35)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.auto_awesome, size: 14, color: AppColors.cyanAccent),
              SizedBox(width: 6),
              Text(
                'AI Smart Estimate',
                style: TextStyle(
                  color: AppColors.cyanAccent,
                  fontSize: 12,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 0.4,
                ),
              ),
              Spacer(),
              Text(
                'LIVE',
                style: TextStyle(
                  color: AppColors.textMuted,
                  fontSize: 9.5,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 1.0,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text.rich(
            TextSpan(
              children: [
                const TextSpan(
                  text: 'Estimated fair price  ',
                  style: TextStyle(
                    color: AppColors.textMuted,
                    fontSize: 12.5,
                    fontWeight: FontWeight.w500,
                  ),
                ),
                TextSpan(
                  text:
                      '\$${range.low.toStringAsFixed(2)} – \$${range.high.toStringAsFixed(2)}',
                  style: const TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 16,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 6),
          Text(
            hasInput
                ? 'Condition "${_pretty(condition)}" x${factor.toStringAsFixed(2)} '
                    '· age & category applied · AI confirms the exact value on submit.'
                : 'Enter title, age and condition to see the range the AI will start from.',
            style: const TextStyle(
              color: AppColors.textMuted,
              fontSize: 11.5,
              height: 1.4,
            ),
          ),
        ],
      ),
    );
  }

  static String _pretty(String condition) =>
      condition.isEmpty ? condition : condition[0].toUpperCase() + condition.substring(1);
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
