import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'app_theme.dart';

/// Breathing brand mark with two counter-rotating orbital rings and drifting
/// sparkles - the cold-start identity piece used on the boot, feed and auth
/// warmup cards (Part B Task 4).
class AnimatedBrandLogo extends StatefulWidget {
  const AnimatedBrandLogo({super.key, this.size = 96});

  /// Diameter of the whole animation box.
  final double size;

  @override
  State<AnimatedBrandLogo> createState() => _AnimatedBrandLogoState();
}

class _AnimatedBrandLogoState extends State<AnimatedBrandLogo>
    with TickerProviderStateMixin {
  late final AnimationController _spin;
  late final AnimationController _breath;

  @override
  void initState() {
    super.initState();
    _spin = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 9),
    )..repeat();
    _breath = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 2300),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _spin.dispose();
    _breath.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final size = widget.size;
    final logoSize = size * 0.52;

    final breathe = Tween<double>(begin: 0.94, end: 1.04).animate(
      CurvedAnimation(parent: _breath, curve: Curves.easeInOut),
    );
    final glow = Tween<double>(begin: 0.10, end: 0.30).animate(
      CurvedAnimation(parent: _breath, curve: Curves.easeInOut),
    );

    return SizedBox(
      width: size,
      height: size,
      child: Stack(
        alignment: Alignment.center,
        children: [
          // Outer ring - clockwise satellite.
          _OrbitingRing(
            size: size,
            rotation: _spin,
            color: AppColors.royalBlue.withOpacity(0.35),
            satelliteColor: AppColors.royalBlue,
            turns: 1,
          ),
          // Inner ring - counter-clockwise satellite.
          _OrbitingRing(
            size: size * 0.76,
            rotation: _spin,
            color: AppColors.forestGreen.withOpacity(0.30),
            satelliteColor: AppColors.forestGreen,
            turns: -1,
            phase: 0.5,
          ),
          // Sparkles breathing around the mark.
          AnimatedBuilder(
            animation: _breath,
            builder: (context, _) {
              final t = _breath.value;
              return Stack(
                alignment: Alignment.center,
                children: [
                  _sparkle(size * 0.20, t, 0.0),
                  _sparkle(size * 0.16, t, 0.38),
                  _sparkle(size * 0.24, t, 0.72),
                ],
              );
            },
          ),
          // Breathing, glowing logo disc.
          AnimatedBuilder(
            animation: _breath,
            builder: (context, child) {
              return Transform.scale(
                scale: breathe.value,
                child: Container(
                  width: logoSize,
                  height: logoSize,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    boxShadow: [
                      BoxShadow(
                        color: AppColors.royalBlue
                            .withOpacity(glow.value),
                        blurRadius: 26,
                        spreadRadius: 3,
                      ),
                    ],
                  ),
                  child: child,
                ),
              );
            },
            child: ClipOval(
              child: Image.asset(
                'assets/logo.png',
                width: logoSize,
                height: logoSize,
                fit: BoxFit.cover,
                // The animation must never break on a missing asset.
                errorBuilder: (context, error, stack) => Container(
                  color: AppColors.surfaceHigh,
                  child: const Icon(
                    Icons.school,
                    color: AppColors.royalBlue,
                    size: 34,
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  /// A tiny four-point star at a fixed orbit position, fading with [t].
  Widget _sparkle(double extent, double t, double phase) {
    final local = (t + phase) % 1.0;
    final opacity = math.sin(local * math.pi).clamp(0.0, 1.0) * 0.9;
    final angle = local * 2 * math.pi;
    final radius = extent;
    return Transform.translate(
      offset: Offset(math.cos(angle) * radius, math.sin(angle) * radius),
      child: Opacity(
        opacity: opacity,
        child: Icon(
          Icons.auto_awesome,
          size: 11,
          color: AppColors.royalBlue.withOpacity(0.8),
        ),
      ),
    );
  }
}

/// One dashed-feel orbit circle with a satellite dot riding it.
/// [turns] = 1 rotates clockwise, -1 counter-clockwise.
class _OrbitingRing extends StatelessWidget {
  const _OrbitingRing({
    required this.size,
    required this.rotation,
    required this.color,
    required this.satelliteColor,
    required this.turns,
    this.phase = 0.0,
  });

  final double size;
  final Animation<double> rotation;
  final Color color;
  final Color satelliteColor;
  final int turns;
  final double phase;

  @override
  Widget build(BuildContext context) {
    return Transform.rotate(
      angle: phase * 2 * math.pi,
      child: AnimatedBuilder(
        animation: rotation,
        builder: (context, _) {
          final angle = rotation.value * turns * 2 * math.pi;
          return SizedBox(
            width: size,
            height: size,
            child: Stack(
              alignment: Alignment.center,
              children: [
                Container(
                  width: size,
                  height: size,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    border: Border.all(color: color, width: 1.2),
                  ),
                ),
                Transform.translate(
                  offset: Offset(
                    math.cos(angle) * (size / 2),
                    math.sin(angle) * (size / 2),
                  ),
                  child: Container(
                    width: 7,
                    height: 7,
                    decoration: BoxDecoration(
                      color: satelliteColor,
                      shape: BoxShape.circle,
                      boxShadow: [
                        BoxShadow(
                          color: satelliteColor.withOpacity(0.5),
                          blurRadius: 8,
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

/// Honest cold-start phase ticker shown under the brand logo while a slow
/// (>3s) request is still pending: each phase check-marks as the next begins.
class WarmupStepIndicator extends StatefulWidget {
  const WarmupStepIndicator({
    super.key,
    this.steps = const <String>[
      'Connecting to CampusMart AI',
      'Waking up the cloud AI server',
      'Loading campus marketplace',
    ],
    this.stepDuration = const Duration(milliseconds: 2600),
  });

  final List<String> steps;
  final Duration stepDuration;

  @override
  State<WarmupStepIndicator> createState() => _WarmupStepIndicatorState();
}

class _WarmupStepIndicatorState extends State<WarmupStepIndicator> {
  int _index = 0;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(widget.stepDuration, (_) {
      if (!mounted) return;
      if (_index >= widget.steps.length - 1) return; // hold on the last step
      setState(() => _index += 1);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        for (var i = 0; i < widget.steps.length; i++)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                SizedBox(
                  width: 16,
                  height: 16,
                  child: i < _index
                      ? const Icon(
                          Icons.check_circle,
                          size: 15,
                          color: AppColors.forestGreen,
                        )
                      : i == _index
                          ? const CircularProgressIndicator(
                              strokeWidth: 2,
                              color: AppColors.royalBlue,
                            )
                          : Container(
                              margin: const EdgeInsets.all(5),
                              decoration: const BoxDecoration(
                                color: AppColors.hairline,
                                shape: BoxShape.circle,
                              ),
                            ),
                ),
                const SizedBox(width: 10),
                AnimatedDefaultTextStyle(
                  duration: const Duration(milliseconds: 350),
                  style: TextStyle(
                    color: i <= _index
                        ? AppColors.textPrimary
                        : AppColors.textMuted,
                    fontSize: 12.5,
                    fontWeight:
                        i == _index ? FontWeight.w700 : FontWeight.w500,
                  ),
                  child: Text(widget.steps[i]),
                ),
              ],
            ),
          ),
      ],
    );
  }
}
