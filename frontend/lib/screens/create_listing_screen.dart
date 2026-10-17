import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/ai_analysis.dart';
import '../models/product.dart';
import '../providers/auth_provider.dart';
import '../providers/product_provider.dart';
import '../services/api_service.dart';
import '../services/currency.dart';
import '../widgets/app_theme.dart';

/// Tab 1 - "Sell on Campus Mart Ai" (Task 3: mandatory 4-photo vision flow).
///
/// Collects the listing details, then hands them to POST /products/ where the
/// LangGraph AI pipeline derives the category, suggests a fair price, and runs
/// the fraud check. Highlights:
///   * **4 mandatory photo slots** (Front, Back, Side, Label/Close-up) - the
///     exact angles the Vision AI needs; submit stays locked until all four
///     are captured from camera or gallery.
///   * **Automatic AI scan** the moment the 4th upload lands: POST
///     /products/analyze-images auto-fills title, description, condition and
///     price (fields the student has not typed yet), plus AI tags + 4-angle
///     condition notes for the listing.
///   * The submit button sits well above the bottom navigation bar so
///     floating snackbars never cover it.
class CreateListingScreen extends StatefulWidget {
  const CreateListingScreen({super.key, required this.onListingCreated});

  /// Called after a successful creation so the shell can switch to Discover.
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

  static const List<String> _conditions = <String>[
    'Like New',
    'Good',
    'Fair',
    'Poor',
  ];

  /// Slot labels shown on the empty tiles (the 4 vision angles).
  static const List<String> _slotLabels = <String>[
    'Front',
    'Back',
    'Side',
    'Label / Close-up',
  ];

  /// CDN URLs of the captured photos, max 4 (index = slot).
  final List<String> _photos = <String>[];

  /// 1-based slot currently uploading (0 while idle) for the tile spinner.
  int _uploadingSlot = 0;

  static const List<String> _branches = <String>[
    'First Year (Common)',
    'Computer / IT',
    'Mechanical',
    'Electrical / ENTC',
    'Civil',
    'Pharmacy',
    'Architecture / Design',
    'All Branches',
  ];

  static const List<String> _academicYears = <String>[
    'FE (1st Year)',
    'SE (2nd Year)',
    'TE (3rd Year)',
    'BE (Final Year)',
    'All Years',
  ];

  String? _branch;
  String? _academicYear;

  String _condition = _conditions.first;

  /// Strict-JSON result of the 4-photo scan (null until it succeeds).
  AiPhotoAnalysis? _analysis;
  bool _isScanning = false;

  /// True while programmatic auto-fill writes are in flight so the
  /// "user typed this" listeners below do not mark the fields as edited.
  bool _autoFilling = false;

  /// Tracks fields the student has actually typed into - auto-fill never
  /// overwrites a value the seller chose themselves.
  bool _titleEdited = false;
  bool _descriptionEdited = false;
  bool _priceEdited = false;

  /// Clearance so the submit button never hides behind the tab shell's
  /// bottom navigation bar (or a floating snackbar riding on top of it).
  static const double _bottomNavClearance = 96;

  bool get _photosComplete => _photos.length >= _slotLabels.length;
  bool get _isBusy => _isScanning || _uploadingSlot != 0;

  @override
  void initState() {
    super.initState();
    // Rebuild on every keystroke so the AI Smart Estimate stays live, and
    // remember which fields the seller filled in themselves.
    _titleController.addListener(() {
      if (!_autoFilling) _titleEdited = true;
      _onFormChanged();
    });
    _descriptionController.addListener(() {
      if (!_autoFilling) _descriptionEdited = true;
      _onFormChanged();
    });
    _ageController.addListener(_onFormChanged);
    _priceController.addListener(() {
      if (!_autoFilling) _priceEdited = true;
      _onFormChanged();
    });
  }

  @override
  void dispose() {
    _titleController.dispose();
    _descriptionController.dispose();
    _ageController.dispose();
    _priceController.dispose();
    super.dispose();
  }

  void _onFormChanged() {
    if (!mounted) return;
    setState(() {}); // cheap: only re-runs the estimate banner build
  }

  // ---------------------------------------------------------------------------
  // Photos: bottom-sheet source choice -> cloud upload -> slot management
  // ---------------------------------------------------------------------------

  /// Bottom-sheet choice between taking a photo and picking one for [slot].
  Future<void> _choosePhotoSource(int slot) async {
    if (_isBusy) return;
    final label = slot < _slotLabels.length ? _slotLabels[slot] : 'Photo';
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
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 18, 20, 12),
              child: Text(
                'ADD PHOTO ${slot + 1}: ${label.toUpperCase()}',
                style: const TextStyle(
                  color: AppColors.textMuted,
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 1.2,
                ),
              ),
            ),
            ListTile(
              leading: const Icon(Icons.photo_camera_outlined,
                  color: AppColors.royalBlue),
              title: const Text('Take a photo',
                  style: TextStyle(color: AppColors.textPrimary)),
              subtitle: const Text('Use the camera right now',
                  style: TextStyle(color: AppColors.textMuted, fontSize: 12)),
              onTap: () => Navigator.of(sheetContext).pop(ImageSource.camera),
            ),
            ListTile(
              leading: const Icon(Icons.photo_library_outlined,
                  color: AppColors.royalBlue),
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
    if (source != null) await _pickAndUploadImage(source, slot);
  }

  /// Phase 6 cloud pipeline: pick -> POST /products/upload-image/ -> the CDN
  /// URL lands in [slot]. Filling the 4th slot kicks off the AI scan.
  Future<void> _pickAndUploadImage(ImageSource source, int slot) async {
    if (_isBusy) return;

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

    setState(() => _uploadingSlot = slot + 1);
    try {
      final bytes = await picked.readAsBytes();
      final imageUrl = await ApiService.instance.uploadListingImage(
        bytes: bytes,
        filename: picked.name,
        token: auth.token,
      );
      if (!mounted) return;
      setState(() {
        while (_photos.length < slot) {
          _photos.add(''); // keep earlier empty slots stable
        }
        if (slot < _photos.length) {
          _photos[slot] = imageUrl; // replacing an existing photo
        } else {
          _photos.add(imageUrl);
        }
        // The photo set changed -> any previous scan is stale.
        _analysis = null;
        _photos.removeWhere((url) => url.isEmpty);
      });
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
      if (mounted) setState(() => _uploadingSlot = 0);
    }
  }

  void _removePhoto(int slot) {
    if (_isBusy) return;
    setState(() {
      _photos.removeAt(slot);
      _analysis = null;
    });
  }

  /// "Paste URL instead" escape hatch - adds a hosted image to the first
  /// empty slot (validators keep it a real http(s) URL).
  Future<void> _pasteUrl() async {
    if (_isBusy || _photosComplete) return;
    final controller = TextEditingController();
    final url = await showDialog<String>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: AppColors.surface,
        title: const Text(
          'Paste image URL',
          style: TextStyle(
              color: AppColors.textPrimary,
              fontSize: 16,
              fontWeight: FontWeight.w700),
        ),
        content: TextField(
          controller: controller,
          autofocus: true,
          keyboardType: TextInputType.url,
          style:
              const TextStyle(color: AppColors.textPrimary, fontSize: 14),
          decoration: const InputDecoration(hintText: 'https://...'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: const Text('Cancel',
                style: TextStyle(color: AppColors.textMuted)),
          ),
          TextButton(
            onPressed: () =>
                Navigator.of(dialogContext).pop(controller.text.trim()),
            child: const Text('Add'),
          ),
        ],
      ),
    );
    controller.dispose();
    if (url == null || url.isEmpty) return;
    final uri = Uri.tryParse(url);
    if (uri == null || !uri.hasScheme || !uri.hasAuthority) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Enter a full URL (https://...)')),
      );
      return;
    }
    setState(() {
      _photos.add(url);
      _analysis = null;
    });
  }

  // ---------------------------------------------------------------------------
  // Task 3: 4-photo Vision AI scan (triggered by "Scan 4 Photos with AI")
  // ---------------------------------------------------------------------------

  /// POST /products/analyze-images with the 4 CDN URLs, then auto-fill the
  /// untouched fields from the strict-JSON reply.
  Future<void> _runAiScan() async {
    if (!_photosComplete || _isScanning) return;

    final messenger = ScaffoldMessenger.of(context);
    final auth = context.read<AuthProvider>();
    final typedTitle = _titleController.text.trim();
    final typedDescription = _descriptionController.text.trim();

    setState(() => _isScanning = true);
    try {
      final result = await ApiService.instance.analyzeImages(
        imageUrls: _photos,
        // Seller-typed values are only hints (they steer the offline
        // heuristic fallback; a live vision model ignores them).
        title: _titleEdited ? typedTitle : null,
        description: _descriptionEdited ? typedDescription : null,
        token: auth.token,
      );
      if (!mounted) return;

      if (!result.isValidProduct) {
        setState(() {
          _analysis = null;
        });
        messenger.showSnackBar(
          SnackBar(
            backgroundColor: AppColors.danger.withOpacity(0.95),
            duration: const Duration(seconds: 5),
            content: Text(
              result.rejectionReason ??
                  'Screenshot or invalid image detected. Please upload real photos of the item you want to sell.',
              style: const TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        );
        return;
      }

      setState(() {
        _analysis = result;
        _autoFilling = true;
        try {
          if (!_titleEdited && _titleController.text.trim().isEmpty) {
            _titleController.text = result.title;
          }
          if (!_descriptionEdited &&
              _descriptionController.text.trim().isEmpty) {
            _descriptionController.text = result.description;
          }
          if (_conditions.contains(result.condition)) {
            _condition = result.condition;
          }
          if (result.branch != null && result.branch!.isNotEmpty) {
            _branch = result.branch;
          }
          if (result.academicYear != null && result.academicYear!.isNotEmpty) {
            _academicYear = result.academicYear;
          }
          if (!_priceEdited && _priceController.text.trim().isEmpty) {
            _priceController.text =
                result.listedPriceInr.toStringAsFixed(0);
          }
        } finally {
          _autoFilling = false;
        }
      });

      messenger.showSnackBar(
        SnackBar(
          backgroundColor: AppColors.royalBlue.withOpacity(0.94),
          content: Text(
            result.isLiveVision
                ? 'AI vision scan complete (${result.source}) - listing '
                    'auto-filled'
                : 'AI scan complete - smart defaults applied (offline '
                    'heuristic)',
            style: const TextStyle(
              color: Colors.black,
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      messenger.showSnackBar(
        SnackBar(
          backgroundColor: AppColors.warning.withOpacity(0.94),
          content: Text(
            'AI scan unavailable: ${error.message} - you can still submit '
            'and the price agent will run on the server.',
            style: const TextStyle(color: Colors.black),
          ),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      messenger.showSnackBar(
        SnackBar(
          backgroundColor: AppColors.warning.withOpacity(0.94),
          content: Text(
            'AI scan failed: $error - you can still submit.',
            style: const TextStyle(color: Colors.black),
          ),
        ),
      );
    } finally {
      if (mounted) setState(() => _isScanning = false);
    }
  }

  // ---------------------------------------------------------------------------
  // Submit
  // ---------------------------------------------------------------------------

  Future<void> _submit() async {
    final form = _formKey.currentState;
    if (form == null || !form.validate()) return;

    if (!_photosComplete) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          backgroundColor: AppColors.warning.withOpacity(0.94),
          content: Text(
            'Add all 4 photos (${_slotLabels.join(' / ')}) before '
            'submitting - the AI vision scan needs every angle.',
            style: const TextStyle(color: Colors.black, fontWeight: FontWeight.w700),
          ),
        ),
      );
      return;
    }

    // Capture everything needed AFTER the await before leaving this context.
    final provider = context.read<ProductProvider>();
    final messenger = ScaffoldMessenger.of(context);
    final analysis = _analysis;

    final payload = <String, dynamic>{
      'title': _titleController.text.trim(),
      'description': _descriptionController.text.trim(),
      // AI input only - never persisted to the products table.
      'age': _ageController.text.trim(),
      'condition': _condition,
      'image_url': _photos.first,
      'image_urls': _photos,
      if (_branch != null && _branch!.isNotEmpty) 'branch': _branch,
      if (_academicYear != null && _academicYear!.isNotEmpty)
        'academic_year': _academicYear,
      if (analysis != null) ...{
        'ai_tags': analysis.tagsCsv,
        'ai_condition_notes': analysis.conditionNotes,
        'ai_suggested_price': analysis.suggestedPriceInr,
        if (analysis.whatsappPitch != null && analysis.whatsappPitch!.isNotEmpty)
          'whatsapp_share_text': analysis.whatsappPitch,
      },
      'listed_price': double.parse(_priceController.text.trim()),
      // `category` omitted on purpose: the AI pipeline owns it (Phase 3).
    };

    final created = await provider.addProduct(payload);
    if (!mounted) return;

    if (created != null) {
      _resetForm();
      widget.onListingCreated();
      _showCelebrationModal(created);
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

  void _showCelebrationModal(Product product) {
    showDialog(
      context: context,
      barrierDismissible: true,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppColors.surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        title: const Row(
          children: [
            Text('🎉 ', style: TextStyle(fontSize: 22)),
            Expanded(
              child: Text(
                'Listing Published Live!',
                style: TextStyle(
                  color: AppColors.inkBlack,
                  fontWeight: FontWeight.bold,
                  fontSize: 18,
                ),
              ),
            ),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Your "${product.title}" is now active in your college marketplace at ${formatInr(product.listedPrice)}.',
              style: const TextStyle(color: AppColors.textPrimary, fontSize: 13.5),
            ),
            const SizedBox(height: 14),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: const Color(0xFF25D366).withOpacity(0.1),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: const Color(0xFF25D366).withOpacity(0.3)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Row(
                    children: [
                      Icon(Icons.bolt, size: 14, color: Color(0xFF15803D)),
                      SizedBox(width: 4),
                      Text(
                        'AI Viral WhatsApp Pitch:',
                        style: TextStyle(
                          color: Color(0xFF15803D),
                          fontWeight: FontWeight.w700,
                          fontSize: 11,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Text(
                    product.whatsappShareText ??
                        '🔥 ${product.title} listed on CampusMart for ${formatInr(product.listedPrice)}!',
                    style: const TextStyle(
                      color: AppColors.inkBlack,
                      fontSize: 12.5,
                      fontStyle: FontStyle.italic,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const Text('View Feed', style: TextStyle(color: AppColors.textMuted)),
          ),
          FilledButton.icon(
            onPressed: () async {
              Navigator.of(ctx).pop();
              final text = product.whatsappShareText ??
                  '🔥 *${product.title}* listed on CampusMart for *${formatInr(product.listedPrice)}*!\n'
                  'Check it out on CampusMart AI: https://campusmart-api-zia4.onrender.com/products/${product.id}';
              final url = Uri.parse('https://api.whatsapp.com/send?text=${Uri.encodeComponent(text)}');
              try {
                if (await canLaunchUrl(url)) {
                  await launchUrl(url, mode: LaunchMode.externalApplication);
                }
              } catch (_) {}
            },
            icon: const Icon(Icons.share, size: 16),
            label: const Text('Share to WhatsApp Groups'),
            style: FilledButton.styleFrom(
              backgroundColor: const Color(0xFF25D366),
              foregroundColor: Colors.white,
            ),
          ),
        ],
      ),
    );
  }

  void _resetForm() {
    _formKey.currentState?.reset();
    _titleController.clear();
    _descriptionController.clear();
    _ageController.clear();
    _priceController.clear();
    setState(() {
      _condition = _conditions.first;
      _branch = null;
      _academicYear = null;
      _photos.clear();
      _analysis = null;
      _isScanning = false;
      _uploadingSlot = 0;
      _titleEdited = false;
      _descriptionEdited = false;
      _priceEdited = false;
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
                fontFamily: 'Georgia',
                fontSize: 19,
                fontWeight: FontWeight.w700,
                color: AppColors.inkBlack,
              ),
            ),
            Text(
              '4-photo AI vision scan · smart pricing & safety check',
              style: TextStyle(
                fontSize: 11.5,
                fontWeight: FontWeight.w500,
                color: AppColors.royalBlue,
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
              _buildPhotoGrid(),
              const SizedBox(height: 12),
              _buildScanStatus(),
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
                        hintText: 'e.g. 450',
                        prefixText: '₹ ',
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
              const SizedBox(height: 16),
              DropdownButtonFormField<String>(
                value: _branch,
                dropdownColor: AppColors.surfaceHigh,
                decoration: const InputDecoration(
                  labelText: 'Target Branch (Auto-detected by AI)',
                  hintText: 'Select Branch',
                ),
                items: _branches
                    .map(
                      (b) => DropdownMenuItem<String>(
                        value: b,
                        child: Text(b),
                      ),
                    )
                    .toList(),
                onChanged: isSubmitting
                    ? null
                    : (value) => setState(() => _branch = value),
              ),
              const SizedBox(height: 16),
              DropdownButtonFormField<String>(
                value: _academicYear,
                dropdownColor: AppColors.surfaceHigh,
                decoration: const InputDecoration(
                  labelText: 'Academic Year (Auto-detected by AI)',
                  hintText: 'Select Year',
                ),
                items: _academicYears
                    .map(
                      (y) => DropdownMenuItem<String>(
                        value: y,
                        child: Text(y),
                      ),
                    )
                    .toList(),
                onChanged: isSubmitting
                    ? null
                    : (value) => setState(() => _academicYear = value),
              ),
              const SizedBox(height: 28),
              FilledButton(
                onPressed: isSubmitting || _isBusy ? null : _submit,
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

  // ---------------------------------------------------------------------------
  // 4-slot photo grid + scan status
  // ---------------------------------------------------------------------------

  /// 2x2 grid of the 4 mandatory vision angles.
  Widget _buildPhotoGrid() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Text(
              'PHOTOS (ALL 4 REQUIRED)',
              style: TextStyle(
                color: AppColors.textMuted,
                fontSize: 11,
                fontWeight: FontWeight.w700,
                letterSpacing: 1.1,
              ),
            ),
            const Spacer(),
            Text(
              '${_photos.length} / 4',
              style: TextStyle(
                color: _photosComplete
                    ? AppColors.success
                    : AppColors.royalBlue,
                fontSize: 12,
                fontWeight: FontWeight.w800,
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        GridView.builder(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: 2,
            mainAxisSpacing: 10,
            crossAxisSpacing: 10,
            childAspectRatio: 1.15,
          ),
          itemCount: _slotLabels.length,
          itemBuilder: (context, index) => _buildPhotoSlot(index),
        ),
        const SizedBox(height: 8),
        Text(
          _photosComplete
              ? 'All 4 angles captured - the AI scans them together for '
                  'category, condition and fair price.'
              : 'Capture Front, Back, Side and a Label close-up. The AI '
                  'vision scan needs all 4 angles.',
          style: const TextStyle(
            color: AppColors.textMuted,
            fontSize: 11.5,
            height: 1.4,
          ),
        ),
        const SizedBox(height: 4),
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: _photosComplete || _isBusy ? null : _pasteUrl,
            icon: const Icon(Icons.link_outlined, size: 15),
            label: const Text('Paste URL instead'),
            style: TextButton.styleFrom(
              foregroundColor: AppColors.textMuted,
              padding: const EdgeInsets.symmetric(horizontal: 4),
            ),
          ),
        ),
      ],
    );
  }

  /// One angle tile: photo preview + remove, or an "add" placeholder.
  Widget _buildPhotoSlot(int index) {
    final hasPhoto = index < _photos.length && _photos[index].isNotEmpty;
    final uploading = _uploadingSlot == index + 1;

    return Material(
      color: AppColors.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: BorderSide(
          color: hasPhoto
              ? AppColors.royalBlue.withOpacity(0.45)
              : AppColors.hairline,
          width: 1.2,
        ),
      ),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: _isBusy
            ? null
            : () => hasPhoto ? _replacePhoto(index) : _choosePhotoSource(index),
        child: Stack(
          fit: StackFit.expand,
          children: [
            if (hasPhoto)
              Image.network(
                _photos[index],
                fit: BoxFit.cover,
                errorBuilder: (context, error, stackTrace) =>
                    _SlotPlaceholder(label: _slotLabels[index]),
              )
            else
              _SlotPlaceholder(label: _slotLabels[index]),

            // Slot number / label strip.
            Positioned(
              left: 0,
              right: 0,
              bottom: 0,
              child: Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
                color: Colors.black.withOpacity(0.62),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(
                        '${index + 1}. ${_slotLabels[index]}',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 10.5,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                    if (hasPhoto && !_isBusy)
                      GestureDetector(
                        onTap: () => _removePhoto(index),
                        child: const Icon(Icons.close,
                            size: 15, color: Colors.white70),
                      ),
                  ],
                ),
              ),
            ),

            if (uploading)
              Container(
                color: AppColors.voidBlack.withOpacity(0.7),
                alignment: Alignment.center,
                child: const Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    SizedBox(
                      width: 24,
                      height: 24,
                      child: CircularProgressIndicator(
                        strokeWidth: 2.4,
                        color: AppColors.royalBlue,
                      ),
                    ),
                    SizedBox(height: 8),
                    Text(
                      'Uploading...',
                      style: TextStyle(
                        color: AppColors.textPrimary,
                        fontSize: 11.5,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }

  /// Tap-to-replace sheet for a filled slot.
  Future<void> _replacePhoto(int index) async {
    if (_isBusy) return;
    final label = _slotLabels[index];
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
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 18, 20, 12),
              child: Text(
                'REPLACE PHOTO: ${label.toUpperCase()}',
                style: const TextStyle(
                  color: AppColors.textMuted,
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 1.2,
                ),
              ),
            ),
            ListTile(
              leading: const Icon(Icons.photo_camera_outlined,
                  color: AppColors.royalBlue),
              title: const Text('Take a photo',
                  style: TextStyle(color: AppColors.textPrimary)),
              onTap: () => Navigator.of(sheetContext).pop(ImageSource.camera),
            ),
            ListTile(
              leading: const Icon(Icons.photo_library_outlined,
                  color: AppColors.royalBlue),
              title: const Text('Choose from gallery',
                  style: TextStyle(color: AppColors.textPrimary)),
              onTap: () => Navigator.of(sheetContext).pop(ImageSource.gallery),
            ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
    if (source != null) await _pickAndUploadImage(source, index);
  }

  /// Scan progress / result strip shown under the grid.
  Widget _buildScanStatus() {
    final analysis = _analysis;

    if (_isScanning) {
      return Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: AppColors.royalBlue.withOpacity(0.08),
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: AppColors.royalBlue.withOpacity(0.4)),
        ),
        child: const Row(
          children: [
            SizedBox(
              width: 20,
              height: 20,
              child: CircularProgressIndicator(
                strokeWidth: 2.4,
                color: AppColors.royalBlue,
              ),
            ),
            SizedBox(width: 12),
            Expanded(
              child: Text(
                'AI vision scanning all 4 photos - category, condition, '
                'tags and fair price incoming...',
                style: TextStyle(
                  color: AppColors.textPrimary,
                  fontSize: 12.5,
                  height: 1.35,
                ),
              ),
            ),
          ],
        ),
      );
    }

    if (analysis == null) {
      if (!_photosComplete) return const SizedBox.shrink();
      return OutlinedButton.icon(
        onPressed: _runAiScan,
        icon: const Icon(Icons.auto_awesome, size: 16),
        label: const Text('Scan 4 Photos with AI'),
        style: OutlinedButton.styleFrom(
          foregroundColor: AppColors.royalBlue,
          side: BorderSide(color: AppColors.royalBlue.withOpacity(0.5)),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
        ),
      );
    }

    final rangeLabel = analysis.priceMinInr > 0
        ? '${formatInr(analysis.priceMinInr)} – ${formatInr(analysis.priceMaxInr)}'
        : formatInr(analysis.suggestedPriceInr);

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.success.withOpacity(0.08),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.success.withOpacity(0.4)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.check_circle, size: 15, color: AppColors.success),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  analysis.isLiveVision
                      ? 'AI vision scan complete (${analysis.source})'
                      : 'AI scan complete (offline heuristic)',
                  style: const TextStyle(
                    color: AppColors.success,
                    fontSize: 12.5,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 7),
          if ((analysis.brand ?? '').isNotEmpty) ...[
            Text(
              '${analysis.brand}'
              '${(analysis.modelName ?? '').isEmpty ? '' : ' ${analysis.modelName}'}'
              ' · ${analysis.category} · ${analysis.condition}',
              style: const TextStyle(
                color: AppColors.textPrimary,
                fontSize: 12.5,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 5),
          ],
          if (analysis.conditionNotes.isNotEmpty) ...[
            Text(
              analysis.conditionNotes,
              style: const TextStyle(
                color: AppColors.textMuted,
                fontSize: 12,
                height: 1.4,
              ),
            ),
            const SizedBox(height: 5),
          ],
          Text(
            'AI fair range $rangeLabel · suggested '
            '${formatInr(analysis.suggestedPriceInr)}',
            style: const TextStyle(
              color: AppColors.royalBlue,
              fontSize: 12.5,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            'Tags: ${analysis.tagsCsv}',
            style: const TextStyle(
              color: AppColors.textMuted,
              fontSize: 11,
              height: 1.35,
            ),
          ),
        ],
      ),
    );
  }
}

/// Empty / error state inside one photo slot (with its angle label).
class _SlotPlaceholder extends StatelessWidget {
  const _SlotPlaceholder({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        const Icon(Icons.add_a_photo_outlined,
            size: 26, color: AppColors.textMuted),
        const SizedBox(height: 7),
        Text(
          label,
          style: const TextStyle(
            color: AppColors.textPrimary,
            fontSize: 12,
            fontWeight: FontWeight.w700,
          ),
        ),
        const SizedBox(height: 3),
        const Text(
          'Tap to add',
          style: TextStyle(color: AppColors.textMuted, fontSize: 10.5),
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
              color: AppColors.royalBlue,
            ),
          ),
          SizedBox(height: 14),
          Text(
            'AI Orchestrator is analyzing listing & verifying price...',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: AppColors.royalBlue,
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
