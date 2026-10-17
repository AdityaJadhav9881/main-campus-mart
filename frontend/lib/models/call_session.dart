/// Data model for an active, ringing, or ended call session between two students.
class CallSession {
  const CallSession({
    required this.id,
    required this.callerId,
    required this.callerName,
    required this.receiverId,
    required this.receiverName,
    required this.callType,
    required this.status,
    required this.startedAt,
    this.productId,
    this.productTitle,
    this.sdpOffer,
    this.sdpAnswer,
    this.callerIceCandidatesJson,
    this.receiverIceCandidatesJson,
    this.connectedAt,
    this.endedAt,
  });

  factory CallSession.fromJson(Map<String, dynamic> json) {
    return CallSession(
      id: json['id']?.toString() ?? '',
      callerId: json['caller_id']?.toString() ?? '',
      callerName: json['caller_name']?.toString() ?? 'Caller',
      receiverId: json['receiver_id']?.toString() ?? '',
      receiverName: json['receiver_name']?.toString() ?? 'Receiver',
      productId: json['product_id']?.toString(),
      productTitle: json['product_title']?.toString(),
      callType: json['call_type']?.toString() ?? 'voice',
      status: json['status']?.toString() ?? 'ringing',
      sdpOffer: json['sdp_offer']?.toString(),
      sdpAnswer: json['sdp_answer']?.toString(),
      callerIceCandidatesJson: json['caller_ice_candidates_json']?.toString(),
      receiverIceCandidatesJson: json['receiver_ice_candidates_json']?.toString(),
      startedAt: DateTime.tryParse(json['started_at']?.toString() ?? '') ??
          DateTime.now(),
      connectedAt: DateTime.tryParse(json['connected_at']?.toString() ?? ''),
      endedAt: DateTime.tryParse(json['ended_at']?.toString() ?? ''),
    );
  }

  final String id;
  final String callerId;
  final String callerName;
  final String receiverId;
  final String receiverName;
  final String? productId;
  final String? productTitle;
  final String callType;
  final String status;
  final String? sdpOffer;
  final String? sdpAnswer;
  final String? callerIceCandidatesJson;
  final String? receiverIceCandidatesJson;
  final DateTime startedAt;
  final DateTime? connectedAt;
  final DateTime? endedAt;

  bool get isRinging => status == 'ringing';
  bool get isConnected => status == 'connected';
  bool get isEnded =>
      status == 'ended' ||
      status == 'declined' ||
      status == 'missed' ||
      status == 'cancelled';

  Map<String, dynamic> toJson() => {
        'id': id,
        'caller_id': callerId,
        'caller_name': callerName,
        'receiver_id': receiverId,
        'receiver_name': receiverName,
        'product_id': productId,
        'product_title': productTitle,
        'call_type': callType,
        'status': status,
        'sdp_offer': sdpOffer,
        'sdp_answer': sdpAnswer,
        'started_at': startedAt.toIso8601String(),
        'connected_at': connectedAt?.toIso8601String(),
        'ended_at': endedAt?.toIso8601String(),
      };
}

