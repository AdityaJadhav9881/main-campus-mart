import 'package:flutter/material.dart';
import '../models/call_session.dart';
import '../services/api_service.dart';
import '../services/permission_service.dart';
import 'in_app_call_screen.dart';

/// Full-screen incoming call overlay with sound, vibration, and Answer/Decline buttons.
class IncomingCallOverlay extends StatefulWidget {
  const IncomingCallOverlay({
    super.key,
    required this.call,
    required this.token,
  });

  final CallSession call;
  final String token;

  static Future<void> show(
    BuildContext context, {
    required CallSession call,
    required String token,
  }) async {
    await showGeneralDialog(
      context: context,
      barrierDismissible: false,
      barrierLabel: 'Incoming Call',
      barrierColor: Colors.black.withOpacity(0.85),
      pageBuilder: (context, anim1, anim2) {
        return IncomingCallOverlay(call: call, token: token);
      },
    );
  }

  @override
  State<IncomingCallOverlay> createState() => _IncomingCallOverlayState();
}

class _IncomingCallOverlayState extends State<IncomingCallOverlay>
    with SingleTickerProviderStateMixin {
  late final AnimationController _pulseController;
  bool _actionTaken = false;

  @override
  void initState() {
    super.initState();
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    )..repeat(reverse: true);

    PermissionService.startRingtone();
  }

  @override
  void dispose() {
    PermissionService.stopRingtone();
    _pulseController.dispose();
    super.dispose();
  }

  Future<void> _answer() async {
    if (_actionTaken) return;
    _actionTaken = true;
    await PermissionService.stopRingtone();
    try {
      await ApiService.instance.answerCall(widget.call.id, token: widget.token);
    } catch (_) {}

    if (!mounted) return;
    Navigator.of(context).pop(); // dismiss overlay
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => InAppCallScreen(
          receiverName: widget.call.callerName,
          initialVideo: widget.call.callType == 'video',
          callId: widget.call.id,
          token: widget.token,
          isReceiver: true,
        ),
      ),
    );
  }

  Future<void> _decline() async {
    if (_actionTaken) return;
    _actionTaken = true;
    await PermissionService.stopRingtone();
    try {
      await ApiService.instance.declineCall(widget.call.id, token: widget.token);
    } catch (_) {}
    if (!mounted) return;
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    final callerName = widget.call.callerName;
    final initial = callerName.isNotEmpty ? callerName[0].toUpperCase() : 'S';

    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, dynamic result) async {
        if (didPop) return;
        await _decline();
      },
      child: Scaffold(
        backgroundColor: Colors.transparent,
        body: SafeArea(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              // Top Bar / Call Type
              Padding(
                padding: const EdgeInsets.only(top: 40.0),
                child: Column(
                  children: [
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
                      decoration: BoxDecoration(
                        color: Colors.white.withOpacity(0.15),
                        borderRadius: BorderRadius.circular(20),
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(
                            widget.call.callType == 'video'
                                ? Icons.videocam_rounded
                                : Icons.phone_in_talk_rounded,
                            color: Colors.white,
                            size: 16,
                          ),
                          const SizedBox(width: 6),
                          Text(
                            'Incoming ${widget.call.callType == 'video' ? 'Video' : 'Voice'} Call',
                            style: const TextStyle(
                              color: Colors.white,
                              fontSize: 13,
                              fontWeight: FontWeight.w600,
                              letterSpacing: 0.3,
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 24),
                    Text(
                      callerName,
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 28,
                        fontWeight: FontWeight.bold,
                        fontFamily: 'serif',
                      ),
                    ),
                    if (widget.call.productTitle != null && widget.call.productTitle!.isNotEmpty) ...[
                      const SizedBox(height: 8),
                      Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 32),
                        child: Text(
                          'Regarding: ${widget.call.productTitle}',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            color: Colors.white.withOpacity(0.8),
                            fontSize: 14,
                          ),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ],
                  ],
                ),
              ),

              // Animated Pulsing Avatar
              ScaleTransition(
                scale: Tween<double>(begin: 0.95, end: 1.08).animate(
                  CurvedAnimation(parent: _pulseController, curve: Curves.easeInOut),
                ),
                child: Container(
                  width: 140,
                  height: 140,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: const Color(0xFF2563EB),
                    boxShadow: [
                      BoxShadow(
                        color: const Color(0xFF2563EB).withOpacity(0.4),
                        blurRadius: 30,
                        spreadRadius: 10,
                      ),
                    ],
                  ),
                  child: Center(
                    child: Text(
                      initial,
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 54,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                ),
              ),

              // Bottom Action Buttons: Decline (Red) & Answer (Green)
              Padding(
                padding: const EdgeInsets.only(bottom: 48.0, left: 40, right: 40),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceAround,
                  children: [
                    // Decline
                    Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        GestureDetector(
                          onTap: _decline,
                          child: Container(
                            width: 68,
                            height: 68,
                            decoration: const BoxDecoration(
                              shape: BoxShape.circle,
                              color: Color(0xFFDC2626), // Red
                            ),
                            child: const Icon(Icons.call_end, color: Colors.white, size: 32),
                          ),
                        ),
                        const SizedBox(height: 8),
                        const Text(
                          'Decline',
                          style: TextStyle(color: Colors.white70, fontSize: 13),
                        ),
                      ],
                    ),

                    // Answer
                    Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        GestureDetector(
                          onTap: _answer,
                          child: Container(
                            width: 68,
                            height: 68,
                            decoration: const BoxDecoration(
                              shape: BoxShape.circle,
                              color: Color(0xFF16A34A), // Green
                            ),
                            child: const Icon(Icons.call, color: Colors.white, size: 32),
                          ),
                        ),
                        const SizedBox(height: 8),
                        const Text(
                          'Answer',
                          style: TextStyle(color: Colors.white70, fontSize: 13),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

