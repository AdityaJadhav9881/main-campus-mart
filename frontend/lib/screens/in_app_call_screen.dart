import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_webrtc/flutter_webrtc.dart';

import '../services/api_service.dart';
import '../widgets/app_theme.dart';

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

/// Full-screen in-app call UI for a buyer-seller thread with real WebRTC two-way audio & video.
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

  final RTCVideoRenderer _localRenderer = RTCVideoRenderer();
  final RTCVideoRenderer _remoteRenderer = RTCVideoRenderer();
  RTCPeerConnection? _peerConnection;
  MediaStream? _localStream;

  bool _connected = false;
  int _seconds = 0;
  bool _muted = false;
  bool _speaker = false;
  late bool _video;
  bool _hasRemoteDescription = false;
  bool _callTerminated = false;
  final Set<String> _appliedCandidates = <String>{};

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

    _initWebRtcAndSignaling();
  }

  Future<void> _initWebRtcAndSignaling() async {
    try {
      await _localRenderer.initialize();
      await _remoteRenderer.initialize();

      // Create WebRTC PeerConnection with Google STUN servers
      final rtcConfig = <String, dynamic>{
        'iceServers': [
          {'urls': 'stun:stun.l.google.com:19302'},
          {'urls': 'stun:stun1.l.google.com:19302'},
        ],
        'sdpSemantics': 'unified-plan',
      };

      _peerConnection = await createPeerConnection(rtcConfig);

      // Hardware mic + camera acquisition
      final mediaConstraints = <String, dynamic>{
        'audio': {
          'echoCancellation': true,
          'noiseSuppression': true,
          'autoGainControl': true,
        },
        'video': _video
            ? {
                'facingMode': 'user',
                'mandatory': {
                  'minWidth': '640',
                  'minHeight': '480',
                  'minFrameRate': '30',
                },
              }
            : false,
      };

      _localStream = await navigator.mediaDevices.getUserMedia(mediaConstraints);
      _localRenderer.srcObject = _localStream;

      for (final track in _localStream!.getTracks()) {
        await _peerConnection?.addTrack(track, _localStream!);
      }

      // Handle remote incoming track
      _peerConnection?.onTrack = (RTCTrackEvent event) {
        if (event.streams.isNotEmpty) {
          _remoteRenderer.srcObject = event.streams[0];
          if (mounted) setState(() {});
        }
      };

      // Gather local ICE candidates and post to server
      _peerConnection?.onIceCandidate = (RTCIceCandidate candidate) {
        if (candidate.candidate != null &&
            widget.callId != null &&
            widget.token != null) {
          final candMap = {
            'candidate': candidate.candidate,
            'sdpMid': candidate.sdpMid,
            'sdpMLineIndex': candidate.sdpMLineIndex,
          };
          ApiService.instance.signalCall(
            widget.callId!,
            iceCandidate: jsonEncode(candMap),
            isCaller: !widget.isReceiver,
            token: widget.token!,
          );
        }
      };

      if (!widget.isReceiver) {
        // Caller creates WebRTC SDP offer
        final offer = await _peerConnection!.createOffer();
        await _peerConnection!.setLocalDescription(offer);
        if (widget.callId != null && widget.token != null) {
          await ApiService.instance.signalCall(
            widget.callId!,
            sdpOffer: offer.sdp,
            isCaller: true,
            token: widget.token!,
          );
        }
      }
    } catch (_) {}

    if (widget.isReceiver) {
      _startConnectedTimer();
    }

    _startFastStatusPolling();
  }

  void _startFastStatusPolling() {
    if (widget.callId == null || widget.token == null) return;

    // Fast 800ms status & signaling sync loop
    _pollTimer?.cancel();
    _pollTimer = Timer.periodic(const Duration(milliseconds: 800), (_) async {
      if (_callTerminated || !mounted) return;
      try {
        final session = await ApiService.instance.fetchCallSession(
          widget.callId!,
          token: widget.token!,
        );

        if (!mounted || _callTerminated) return;

        // Instant hang-up sync: if status is cancelled, declined, ended, or missed, tear down immediately
        if (session.status == 'cancelled' ||
            session.status == 'declined' ||
            session.status == 'ended' ||
            session.status == 'missed' ||
            session.isEnded) {
          _closeRemote(session.status);
          return;
        }

        // Connection state transition
        if (session.status == 'connected' && !_connected) {
          _startConnectedTimer();
        }

        // Caller receives SDP answer from Receiver
        if (!widget.isReceiver &&
            session.sdpAnswer != null &&
            !_hasRemoteDescription &&
            _peerConnection != null) {
          _hasRemoteDescription = true;
          final answerDesc = RTCSessionDescription(session.sdpAnswer!, 'answer');
          await _peerConnection?.setRemoteDescription(answerDesc);
        }

        // Receiver receives SDP offer from Caller
        if (widget.isReceiver &&
            session.sdpOffer != null &&
            !_hasRemoteDescription &&
            _peerConnection != null) {
          _hasRemoteDescription = true;
          final offerDesc = RTCSessionDescription(session.sdpOffer!, 'offer');
          await _peerConnection?.setRemoteDescription(offerDesc);

          final answer = await _peerConnection!.createAnswer();
          await _peerConnection!.setLocalDescription(answer);
          await ApiService.instance.answerCall(
            widget.callId!,
            sdpAnswer: answer.sdp,
            token: widget.token!,
          );
        }

        // Exchange peer ICE candidates
        final signal = await ApiService.instance.fetchCallSignal(
          widget.callId!,
          token: widget.token!,
        );

        final peerCandidates = signal['peer_ice_candidates'] as List<dynamic>? ?? const [];
        for (final item in peerCandidates) {
          final candStr = item.toString();
          if (_appliedCandidates.add(candStr)) {
            try {
              final candMap = jsonDecode(candStr) as Map<String, dynamic>;
              final candidate = RTCIceCandidate(
                candMap['candidate']?.toString(),
                candMap['sdpMid']?.toString(),
                candMap['sdpMLineIndex'] as int?,
              );
              await _peerConnection?.addCandidate(candidate);
            } catch (_) {}
          }
        }
      } catch (_) {}
    });
  }

  void _startConnectedTimer() {
    if (!mounted || _connected) return;
    setState(() => _connected = true);
    _callTimer?.cancel();
    _callTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted) return;
      setState(() => _seconds += 1);
    });
  }

  Future<void> _disposeWebRtc() async {
    try {
      _localStream?.getTracks().forEach((track) {
        track.stop();
      });
      await _localStream?.dispose();
      _localStream = null;
      _localRenderer.srcObject = null;
      _remoteRenderer.srcObject = null;
      await _localRenderer.dispose();
      await _remoteRenderer.dispose();
      await _peerConnection?.close();
      await _peerConnection?.dispose();
      _peerConnection = null;
    } catch (_) {}
  }

  void _closeRemote(String status) async {
    if (_callTerminated) return;
    _callTerminated = true;
    _pollTimer?.cancel();
    _callTimer?.cancel();
    await _disposeWebRtc();
    if (!mounted) return;
    Navigator.of(context).pop(
      CallOutcome(
        status: _connected ? 'completed' : 'missed',
        durationSeconds: _connected ? _seconds : 0,
        callType: _video ? 'video' : 'voice',
      ),
    );
  }

  Future<void> _hangUp() async {
    if (_callTerminated) return;
    _callTerminated = true;
    _pollTimer?.cancel();
    _callTimer?.cancel();

    if (widget.callId != null && widget.token != null) {
      try {
        if (!_connected && !widget.isReceiver) {
          // Caller cancelling while still ringing
          await ApiService.instance.cancelCall(widget.callId!, token: widget.token!);
        } else {
          // Connected call ended or receiver hanging up
          await ApiService.instance.endCall(widget.callId!, token: widget.token!);
        }
      } catch (_) {}
    }

    await _disposeWebRtc();
    if (!mounted) return;
    Navigator.of(context).pop(
      CallOutcome(
        status: _connected ? 'completed' : 'missed',
        durationSeconds: _connected ? _seconds : 0,
        callType: _video ? 'video' : 'voice',
      ),
    );
  }

  @override
  void dispose() {
    _callTerminated = true;
    _pollTimer?.cancel();
    _callTimer?.cancel();
    _pulse.dispose();
    _disposeWebRtc();
    super.dispose();
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
                        color: AppColors.royalBlue.withOpacity(0.45),
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

  /// Video layout: remote peer feed full stage + local user camera PiP chip.
  Widget _buildVideoStage() {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20),
      child: Stack(
        children: [
          // Remote peer feed (full stage)
          ClipRRect(
            borderRadius: BorderRadius.circular(22),
            child: Container(
              width: double.infinity,
              height: double.infinity,
              color: const Color(0xFF111C2E),
              child: _remoteRenderer.srcObject != null
                  ? RTCVideoView(
                      _remoteRenderer,
                      objectFit: RTCVideoViewObjectFit.RTCVideoViewObjectFitCover,
                    )
                  : Column(
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
                              ? '${widget.receiverName} is streaming video'
                              : 'Connecting video with ${widget.receiverName}...',
                          style: const TextStyle(
                            color: Colors.white54,
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ],
                    ),
            ),
          ),
          // Local self feed (top-right PiP chip)
          Positioned(
            top: 12,
            right: 12,
            child: ClipRRect(
              borderRadius: BorderRadius.circular(14),
              child: Container(
                width: 90,
                height: 130,
                color: Colors.black54,
                child: _localRenderer.srcObject != null
                    ? RTCVideoView(
                        _localRenderer,
                        mirror: true,
                        objectFit: RTCVideoViewObjectFit.RTCVideoViewObjectFitCover,
                      )
                    : const Center(
                        child: Icon(Icons.person, color: Colors.white38),
                      ),
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
            onTap: () {
              setState(() {
                _muted = !_muted;
                _localStream?.getAudioTracks().forEach((track) {
                  track.enabled = !_muted;
                });
              });
            },
          ),
          _DockButton(
            icon: _speaker ? Icons.volume_up : Icons.volume_down,
            label: 'Speaker',
            active: _speaker,
            onTap: () {
              setState(() {
                _speaker = !_speaker;
                try {
                  Helper.setSpeakerphoneOn(_speaker);
                } catch (_) {}
              });
            },
          ),
          _DockButton(
            icon: _video ? Icons.videocam : Icons.videocam_off,
            label: 'Video',
            active: _video,
            onTap: () async {
              setState(() => _video = !_video);
              try {
                if (_localStream != null) {
                  for (final track in _localStream!.getVideoTracks()) {
                    track.enabled = _video;
                  }
                }
              } catch (_) {}
            },
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
