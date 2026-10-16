// Buyer-seller chat + Ask CampusMart AI models (mirror the FastAPI schemas
// `ChatMessageRead`, `ConversationRead` and `AiChatResponse`).

/// One message on a product thread (POST /chats/messages responses + the
/// GET history rows).
class ChatMessage {
  const ChatMessage({
    required this.id,
    required this.productId,
    required this.senderId,
    required this.receiverId,
    required this.message,
    required this.createdAt,
    this.isRead = false,
  });

  factory ChatMessage.fromJson(Map<String, dynamic> json) {
    return ChatMessage(
      id: json['id']?.toString() ?? '',
      productId: json['product_id']?.toString() ?? '',
      senderId: json['sender_id']?.toString() ?? '',
      receiverId: json['receiver_id']?.toString() ?? '',
      message: json['message']?.toString() ?? '',
      createdAt: DateTime.tryParse(json['created_at']?.toString() ?? '') ??
          DateTime.now(),
      isRead: json['is_read'] == true,
    );
  }

  final String id;
  final String productId;
  final String senderId;
  final String receiverId;
  final String message;
  final DateTime createdAt;
  final bool isRead;
}

/// One inbox thread on the Messages tab (GET /chats/conversations row).
class Conversation {
  const Conversation({
    required this.productId,
    required this.otherUserId,
    required this.otherUserName,
    required this.productTitle,
    required this.lastMessage,
    required this.lastMessageAt,
    required this.lastMessageIsMine,
    this.productImageUrl,
    this.productPrice,
    this.unreadCount = 0,
  });

  factory Conversation.fromJson(Map<String, dynamic> json) {
    return Conversation(
      productId: json['product_id']?.toString() ?? '',
      otherUserId: json['other_user_id']?.toString() ?? '',
      otherUserName: json['other_user_name']?.toString() ?? 'Student',
      productTitle: json['product_title']?.toString() ?? 'Listing',
      productImageUrl: json['product_image_url']?.toString(),
      productPrice: (json['product_price'] as num?)?.toDouble(),
      lastMessage: json['last_message']?.toString() ?? '',
      lastMessageAt:
          DateTime.tryParse(json['last_message_at']?.toString() ?? '') ??
              DateTime.now(),
      lastMessageIsMine: json['last_message_is_mine'] == true,
      unreadCount: (json['unread_count'] as num?)?.toInt() ?? 0,
    );
  }

  final String productId;
  final String otherUserId;
  final String otherUserName;
  final String productTitle;
  final String? productImageUrl;
  final double? productPrice;
  final String lastMessage;
  final DateTime lastMessageAt;
  final bool lastMessageIsMine;
  final int unreadCount;

  bool get hasUnread => unreadCount > 0;
}

/// Reply of POST /ai/chat - `source` is 'llm' when the configured provider
/// answered or 'catalog' for the offline rule-based campus assistant.
class AiChatReply {
  const AiChatReply({
    required this.reply,
    required this.source,
    this.recommendedProductIds = const <String>[],
  });

  factory AiChatReply.fromJson(Map<String, dynamic> json) {
    return AiChatReply(
      reply: json['reply']?.toString() ?? '',
      source: json['source']?.toString() ?? 'catalog',
      recommendedProductIds: (json['recommended_product_ids']
                  as List<dynamic>? ??
              const <dynamic>[])
          .map((dynamic id) => id.toString())
          .where((id) => id.isNotEmpty)
          .toList(growable: false),
    );
  }

  final String reply;
  final String source;
  final List<String> recommendedProductIds;
}

/// One transcript turn the client sends in `history` for POST /ai/chat.
class AiChatTurn {
  const AiChatTurn({required this.role, required this.content});

  final String role; // 'user' | 'assistant'
  final String content;

  Map<String, dynamic> toJson() =>
      <String, dynamic>{'role': role, 'content': content};
}
