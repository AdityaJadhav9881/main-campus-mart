import 'dart:async';

import 'package:flutter/material.dart';

import '../widgets/app_theme.dart';

import '../services/api_service.dart';

/// Outcome returned to the chat thread when a call screen is closed.
class CallOutcome {
  const CallOutcome({
    required this.status,
    required this.durationSeconds,
    required this.callType,
  });

  /// 'completed' (connected then ended) or 'missed' (ended while ringing).
  final String status;
  final int durationSeconds;

  /// 'voice' | 'video' (video also when toggled mid-call).
  final String callType;
}

/// Full-screen in-app call UI for a buyer-seller thread with real two-phone signaling.
class InAppCallScreen extends StatefulWidget {
  const InAppCallScreen({
    super.key,
    required this.receiverName,
    this.initialVideo = false,
    this.callId,
    this.token,
    this.isReceiver = false,
  });

  final String receiverName;
  final bool initialVideo;
  final String? callId;
  final String? token;
  final bool isReceiver;

  @override
  State<InAppCallScreen> createState() => _InAppCallScreenState();
}

class _InAppCallScreenState extends State<InAppCallScreen>
    with SingleTickerProviderStateMixin {
  late final AnimationController _pulse;

  bool _connected = false;
  int _seconds = 0;
  bool _muted = false;
  bool _speaker = false;
  late bool _video;
  Timer? _pollTimer;
  Timer? _callTimer;

  @override
  void initState() {
    super.initState();
    _video = widget.initialVideo;
    _pulse = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1800),
    )..repeat();

    if (widget.isReceiver) {
      _startConnectedTimer();
    } else if (widget.callId != null && widget.token != null) {
      // Poll Phone 2 ringing/answer status every 1.5 seconds
      _pollTimer = Timer.periodic(const Duration(milliseconds: 1500), (_) async {
        try {
          final session = await ApiService.instance.fetchCallSession(
            widget.callId!,
            token: widget.token!,
          );
          if (!mounted) return;
          if (session.status == 'connected' && !_connected) {
            _startConnectedTimer();
          } else if (session.status == 'declined' || session.status == 'ended') {
            _pollTimer?.cancel();
            _hangUp();
          }
        } catch (_) {}
      });
    } else {
      // Local fallback
      Timer(const Duration(milliseconds: 1600), () {
        if (!mounted) return;
        _startConnectedTimer();
      });
    }
  }

  void _startConnectedTimer() {
    _pollTimer?.cancel();
    if (!mounted) return;
    setState(() => _connected = true);
    _callTimer?.cancel();
    _callTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted) return;
      setState(() => _seconds += 1);
    });
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _callTimer?.cancel();
    _pulse.dispose();
    super.dispose();
  }

  Future<void> _hangUp() async {
    _pollTimer?.cancel();
    _callTimer?.cancel();
    if (widget.callId != null && widget.token != null) {
      try {
        await ApiService.instance.endCall(widget.callId!, token: widget.token!);
      } catch (_) {}
    }
    if (!mounted) return;
    Navigator.of(context).pop(
      CallOutcome(
        status: _connected ? 'completed' : 'missed',
        durationSeconds: _connected ? _seconds : 0,
        callType: _video ? 'video' : 'voice',
      ),
    );
  }

  String get _timerLabel {
    final minutes = _seconds ~/ 60;
    final seconds = (_seconds % 60).toString().padLeft(2, '0');
    return '$minutes:$seconds';
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _hangUp();
      },
      child: Scaffold(
        backgroundColor: const Color(0xFF0B1220),
        body: SafeArea(
          child: Column(
            children: [
              const SizedBox(height: 18),
              const Text(
                'CAMPUSMART CALL',
                style: TextStyle(
                  color: Colors.white54,
                  fontSize: 10,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 2,
                ),
              ),
              const SizedBox(height: 10),
              Text(
                widget.receiverName,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontFamily: 'Georgia',
                  color: Colors.white,
                  fontSize: 24,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 8),
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(
                    _video ? Icons.videocam : Icons.call,
                    size: 14,
                    color: _connected
                        ? const Color(0xFF34D399)
                        : Colors.white54,
                  ),
                  const SizedBox(width: 6),
                  Text(
                    _connected
                        ? 'Connected · $_timerLabel'
                        : (widget.isReceiver
                            ? 'Connecting...'
                            : "Calling... Ringing on student's phone..."),
                    style: TextStyle(
                      color: _connected
                          ? const Color(0xFF34D399)
                          : Colors.white70,
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 26),
              Expanded(
                child: _video ? _buildVideoStage() : _buildVoiceStage(),
              ),
              _buildControlDock(),
              const SizedBox(height: 18),
            ],
          ),
        ),
      ),
    );
  }

  /// Voice layout: breathing avatar with expanding pulse rings.
  Widget _buildVoiceStage() {
    return Center(
      child: AnimatedBuilder(
        animation: _pulse,
        builder: (context, _) {
          final t = _pulse.value;
          return SizedBox(
            width: 260,
            height: 260,
            child: Stack(
              alignment: Alignment.center,
              children: [
                for (final phase in const [0.0, 0.33, 0.66])
                  _ring((t + phase) % 1.0),
                Container(
                  width: 108,
                  height: 108,
                  decoration: BoxDecoration(
                    gradient: const LinearGradient(
                      colors: [AppColors.royalBlue, Color(0xFF1D4ED8)],
                      begin: Alignment.topLeft,
                      end: Alignment.bottomRight,
                    ),
                    shape: BoxShape.circle,
                    boxShadow: [
                      BoxShadow(
                        color:
                            AppColors.royalBlue.withOpacity(0.45),
                        blurRadius: 30,
                        spreadRadius: 4,
                      ),
                    ],
                  ),
                  child: Center(
                    child: Text(
                      widget.receiverName.trim().isEmpty
                          ? '?'
                          : widget.receiverName.trim()[0].toUpperCase(),
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 42,
                        fontWeight: FontWeight.w800,
                      ),
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

  Widget _ring(double progress) {
    final size = 116 + progress * 144;
    final opacity = (1 - progress) * 0.35;
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        border: Border.all(
          color: AppColors.royalBlue.withOpacity(opacity),
          width: 1.6,
        ),
      ),
    );
  }

  /// Video layout: large "camera preview" stage + small self chip.
  Widget _buildVideoStage() {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20),
      child: Stack(
        children: [
          Container(
            width: double.infinity,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(22),
              gradient: const LinearGradient(
                colors: [Color(0xFF111C2E), Color(0xFF1E293B)],
                begin: Alignment.topCenter,
                end: Alignment.bottomCenter,
              ),
              border: Border.all(color: Colors.white12),
            ),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Container(
                  width: 84,
                  height: 84,
                  decoration: BoxDecoration(
                    color: Colors.white.withOpacity(0.06),
                    shape: BoxShape.circle,
                    border: Border.all(color: Colors.white12),
                  ),
                  child: const Icon(
                    Icons.videocam_outlined,
                    size: 36,
                    color: Colors.white38,
                  ),
                ),
                const SizedBox(height: 16),
                Text(
                  _connected
                      ? '${widget.receiverName} joined the video call'
                      : 'Waiting for ${widget.receiverName} to join video...',
                  style: const TextStyle(
                    color: Colors.white54,
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 6),
                const Text(
                  'Camera preview appears here on campus Wi-Fi',
                  style: TextStyle(color: Colors.white24, fontSize: 11),
                ),
              ],
            ),
          ),
          // Self preview chip (top-right).
          Positioned(
            top: 12,
            right: 12,
            child: Container(
              width: 74,
              height: 104,
              decoration: BoxDecoration(
                color: const Color(0xFF0F172A),
                borderRadius: BorderRadius.circular(14),
                border: Border.all(color: Colors.white12),
              ),
              child: const Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.person_outline,
                      size: 22, color: Colors.white38),
                  SizedBox(height: 4),
                  Text(
                    'You',
                    style: TextStyle(
                      color: Colors.white38,
                      fontSize: 10,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  /// Mute / Speaker / Toggle Video / End dock.
  Widget _buildControlDock() {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 28),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          _DockButton(
            icon: _muted ? Icons.mic_off : Icons.mic,
            label: 'Mute',
            active: _muted,
            onTap: () => setState(() => _muted = !_muted),
          ),
          _DockButton(
            icon: _speaker ? Icons.volume_up : Icons.volume_down,
            label: 'Speaker',
            active: _speaker,
            onTap: () => setState(() => _speaker = !_speaker),
          ),
          _DockButton(
            icon: _video ? Icons.videocam : Icons.videocam_off,
            label: 'Video',
            active: _video,
            onTap: () => setState(() => _video = !_video),
          ),
          _DockButton(
            icon: Icons.call_end,
            label: 'End',
            active: false,
            danger: true,
            onTap: _hangUp,
          ),
        ],
      ),
    );
  }
}

/// One round control in the bottom dock.
class _DockButton extends StatelessWidget {
  const _DockButton({
    required this.icon,
    required this.label,
    required this.active,
    required this.onTap,
    this.danger = false,
  });

  final IconData icon;
  final String label;
  final bool active;
  final bool danger;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final Color background;
    final Color foreground;
    if (danger) {
      background = const Color(0xFFDC2626);
      foreground = Colors.white;
    } else if (active) {
      background = Colors.white;
      foreground = const Color(0xFF0B1220);
    } else {
      background = Colors.white.withOpacity(0.1);
      foreground = Colors.white;
    }

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Material(
          color: background,
          shape: const CircleBorder(),
          child: InkWell(
            customBorder: const CircleBorder(),
            onTap: onTap,
            child: Padding(
              padding: const EdgeInsets.all(15),
              child: Icon(icon, size: 22, color: foreground),
            ),
          ),
        ),
        const SizedBox(height: 7),
        Text(
          label,
          style: const TextStyle(
            color: Colors.white54,
            fontSize: 10.5,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    );
  }
}
