import 'dart:async';

import 'package:flutter/material.dart';

import '../models/college.dart';
import '../services/api_service.dart';
import 'app_theme.dart';

/// Opens the CET college picker (Sign Up / Profile / Discover filter).
///
/// Resolves to the picked [College] or null when dismissed. Search hits
/// `GET /colleges?q=` with a 250ms debounce; city pills map to `?city=`;
/// unmatched typed text is offered back as a pickable "new campus" entry via
/// `allow_custom=true` so every student can sign up.
Future<College?> showCollegePickerSheet(
  BuildContext context, {
  College? initial,
  String title = 'Pick your college',
}) {
  return showModalBottomSheet<College>(
    context: context,
    isScrollControlled: true,
    backgroundColor: AppColors.surface,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(22)),
    ),
    builder: (_) => _CollegePickerSheet(initial: initial, title: title),
  );
}

class _CollegePickerSheet extends StatefulWidget {
  const _CollegePickerSheet({required this.initial, required this.title});

  final College? initial;
  final String title;

  @override
  State<_CollegePickerSheet> createState() => _CollegePickerSheetState();
}

class _CollegePickerSheetState extends State<_CollegePickerSheet> {
  final ApiService _api = ApiService.instance;
  final TextEditingController _search = TextEditingController();

  Timer? _debounce;
  List<College> _results = const <College>[];
  List<String> _cities = const <String>['All'];
  String _city = 'All';
  bool _isLoading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _fetch();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _search.dispose();
    super.dispose();
  }

  void _onQueryChanged(String value) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 250), _fetch);
  }

  Future<void> _fetch() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });
    try {
      final result = await _api.searchColleges(
        q: _search.text,
        city: _city,
        // Custom echo only makes sense once the student has typed something.
        allowCustom: _search.text.trim().isNotEmpty,
      );
      if (!mounted) return;
      setState(() {
        _results = result.colleges;
        if (result.cities.isNotEmpty) _cities = result.cities;
        _isLoading = false;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _isLoading = false;
        _error = error.message;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _isLoading = false;
        _error = 'Could not search colleges right now.';
      });
    }
  }

  bool _isSelected(College college) {
    final initial = widget.initial;
    if (initial == null) return false;
    if (initial.custom || college.custom) {
      return initial.name.toLowerCase() == college.name.toLowerCase();
    }
    return initial.code.isNotEmpty && initial.code == college.code;
  }

  @override
  Widget build(BuildContext context) {
    final keyboard = MediaQuery.of(context).viewInsets.bottom;
    final height = MediaQuery.of(context).size.height * 0.82;

    return Padding(
      padding: EdgeInsets.only(bottom: keyboard),
      child: SizedBox(
        height: height,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const SizedBox(height: 10),
            Center(
              child: Container(
                width: 42,
                height: 4,
                decoration: BoxDecoration(
                  color: AppColors.hairline,
                  borderRadius: BorderRadius.circular(999),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 16, 20, 4),
              child: Text(
                widget.title,
                style: const TextStyle(
                  fontFamily: 'Georgia',
                  color: AppColors.inkBlack,
                  fontSize: 18,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 4),
              child: Text(
                'Search by college name, short name or DTE/CET code (e.g. 6006).',
                style: TextStyle(
                  color: AppColors.textMuted.withOpacity(0.95),
                  fontSize: 12,
                  height: 1.35,
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(999),
                child: Container(
                  height: 44,
                  decoration: BoxDecoration(
                    color: AppColors.surfaceHigh,
                    borderRadius: BorderRadius.circular(999),
                    border: Border.all(color: AppColors.hairline),
                  ),
                  child: TextField(
                    controller: _search,
                    onChanged: _onQueryChanged,
                    autofocus: false,
                    textInputAction: TextInputAction.search,
                    style: const TextStyle(
                      color: AppColors.textPrimary,
                      fontSize: 14,
                    ),
                    decoration: InputDecoration(
                      isDense: true,
                      filled: false,
                      contentPadding: const EdgeInsets.symmetric(
                        horizontal: 14,
                        vertical: 12,
                      ),
                      hintText: 'Search colleges...',
                      hintStyle: const TextStyle(
                        color: AppColors.textMuted,
                        fontSize: 13.5,
                      ),
                      border: InputBorder.none,
                      enabledBorder: InputBorder.none,
                      focusedBorder: InputBorder.none,
                      prefixIcon: const Icon(
                        Icons.search,
                        color: AppColors.textMuted,
                        size: 20,
                      ),
                      suffixIcon: _search.text.isEmpty
                          ? null
                          : IconButton(
                              icon: const Icon(
                                Icons.clear,
                                color: AppColors.textMuted,
                                size: 17,
                              ),
                              onPressed: () {
                                _debounce?.cancel();
                                _search.clear();
                                _fetch();
                              },
                            ),
                    ),
                  ),
                ),
              ),
            ),
            SizedBox(
              height: 40,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 16),
                itemCount: _cities.length,
                separatorBuilder: (_, __) => const SizedBox(width: 8),
                itemBuilder: (context, index) {
                  final city = _cities[index];
                  final selected = city == _city;
                  return ChoiceChip(
                    label: Text(city),
                    selected: selected,
                    showCheckmark: false,
                    visualDensity: VisualDensity.compact,
                    onSelected: (_) {
                      setState(() => _city = city);
                      _fetch();
                    },
                    selectedColor: AppColors.inkBlack,
                    backgroundColor: AppColors.surface,
                    side: BorderSide(
                      color: selected ? AppColors.inkBlack : AppColors.hairline,
                    ),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(999),
                    ),
                    labelStyle: TextStyle(
                      color: selected ? Colors.white : AppColors.textPrimary,
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                    ),
                  );
                },
              ),
            ),
            const SizedBox(height: 6),
            Expanded(child: _buildResults()),
          ],
        ),
      ),
    );
  }

  Widget _buildResults() {
    if (_isLoading) {
      return const Center(
        child: SizedBox(
          width: 26,
          height: 26,
          child: CircularProgressIndicator(
            strokeWidth: 2.6,
            color: AppColors.royalBlue,
          ),
        ),
      );
    }

    if (_error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 36),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.cloud_off_outlined,
                  size: 38, color: AppColors.textMuted),
              const SizedBox(height: 12),
              Text(
                _error!,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  color: AppColors.textMuted,
                  fontSize: 12.5,
                  height: 1.4,
                ),
              ),
              const SizedBox(height: 10),
              TextButton(
                onPressed: _fetch,
                child: const Text(
                  'Retry',
                  style: TextStyle(
                    color: AppColors.royalBlue,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ],
          ),
        ),
      );
    }

    if (_results.isEmpty) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.symmetric(horizontal: 36),
          child: Text(
            'No colleges match that search yet.\nType your full college name to add it as a new campus.',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: AppColors.textMuted,
              fontSize: 12.5,
              height: 1.5,
            ),
          ),
        ),
      );
    }

    return ListView.separated(
      padding: const EdgeInsets.fromLTRB(16, 6, 16, 20),
      itemCount: _results.length,
      separatorBuilder: (_, __) => const SizedBox(height: 8),
      itemBuilder: (context, index) {
        final college = _results[index];
        return _CollegeRow(
          college: college,
          selected: _isSelected(college),
          onTap: () => Navigator.of(context).pop(college),
        );
      },
    );
  }
}

/// One search-result row: name, short name + city, and the trust badge
/// ("CET 6006" for directory codes, "Verified Campus" for search-discovered
/// campuses without a DTE code, "New campus" for typed-in colleges).
class _CollegeRow extends StatelessWidget {
  const _CollegeRow({
    required this.college,
    required this.selected,
    required this.onTap,
  });

  final College college;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final badge = college.cetBadge;
    return Material(
      color: selected
          ? AppColors.royalBlue.withOpacity(0.07)
          : AppColors.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(13),
        side: BorderSide(
          color: selected
              ? AppColors.royalBlue.withOpacity(0.45)
              : AppColors.hairline,
        ),
      ),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 11, 12, 11),
          child: Row(
            children: [
              Container(
                width: 38,
                height: 38,
                decoration: BoxDecoration(
                  color: college.custom
                      ? AppColors.textMuted.withOpacity(0.12)
                      : AppColors.royalBlue.withOpacity(0.1),
                  shape: BoxShape.circle,
                ),
                child: Icon(
                  college.custom
                      ? Icons.add_home_work_outlined
                      : Icons.school_outlined,
                  size: 19,
                  color: college.custom
                      ? AppColors.textMuted
                      : AppColors.royalBlue,
                ),
              ),
              const SizedBox(width: 11),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      college.name,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: AppColors.textPrimary,
                        fontSize: 13.5,
                        fontWeight: FontWeight.w700,
                        height: 1.25,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      college.custom
                          ? 'Not in the directory yet - added as a new campus'
                          : [
                              if (college.shortName.isNotEmpty)
                                college.shortName,
                              if (college.city.isNotEmpty) college.city,
                            ].join(' · '),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: AppColors.textMuted,
                        fontSize: 11.5,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              if (badge != null)
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: AppColors.royalBlue.withOpacity(0.1),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(
                      color: AppColors.royalBlue.withOpacity(0.35),
                    ),
                  ),
                  child: Text(
                    badge,
                    style: const TextStyle(
                      color: AppColors.royalBlue,
                      fontSize: 10.5,
                      fontWeight: FontWeight.w800,
                      letterSpacing: 0.2,
                    ),
                  ),
                )
              else
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: college.custom
                        ? AppColors.surfaceHigh
                        : AppColors.forestGreen.withOpacity(0.08),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(
                      color: college.custom
                          ? AppColors.hairline
                          : AppColors.forestGreen.withOpacity(0.35),
                    ),
                  ),
                  child: Text(
                    college.custom ? 'New campus' : 'Verified Campus',
                    style: TextStyle(
                      color: college.custom
                          ? AppColors.textMuted
                          : AppColors.forestGreen,
                      fontSize: 10.5,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              if (selected) ...[
                const SizedBox(width: 6),
                const Icon(Icons.check_circle,
                    size: 18, color: AppColors.royalBlue),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
