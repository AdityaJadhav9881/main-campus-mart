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
    this.imageUrl,
    this.isRead = false,
  });

  factory ChatMessage.fromJson(Map<String, dynamic> json) {
    final imageUrl = json['image_url']?.toString();
    return ChatMessage(
      id: json['id']?.toString() ?? '',
      productId: json['product_id']?.toString() ?? '',
      senderId: json['sender_id']?.toString() ?? '',
      receiverId: json['receiver_id']?.toString() ?? '',
      message: json['message']?.toString() ?? '',
      imageUrl: (imageUrl == null || imageUrl.isEmpty) ? null : imageUrl,
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

  /// Cloudinary URL of the attached photo (WhatsApp-style photo messages).
  final String? imageUrl;
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
    this.sessionId,
    this.sessionTitle,
  });

  factory AiChatReply.fromJson(Map<String, dynamic> json) {
    final sessionId = json['session_id']?.toString();
    return AiChatReply(
      reply: json['reply']?.toString() ?? '',
      source: json['source']?.toString() ?? 'catalog',
      recommendedProductIds: (json['recommended_product_ids']
                  as List<dynamic>? ??
              const <dynamic>[])
          .map((dynamic id) => id.toString())
          .where((id) => id.isNotEmpty)
          .toList(growable: false),
      sessionId: (sessionId == null || sessionId.isEmpty) ? null : sessionId,
      sessionTitle: json['session_title']?.toString(),
    );
  }

  final String reply;
  final String source;
  final List<String> recommendedProductIds;

  /// Persisted conversation this turn was saved to (Gemini-style history).
  final String? sessionId;

  /// Auto-derived title when the server created a brand-new session.
  final String? sessionTitle;
}

/// One saved Ask-AI conversation (GET /ai/sessions row) for the history drawer.
class AiSession {
  const AiSession({
    required this.id,
    required this.title,
    required this.createdAt,
    required this.updatedAt,
    this.messageCount = 0,
    this.lastMessage,
  });

  factory AiSession.fromJson(Map<String, dynamic> json) {
    return AiSession(
      id: json['id']?.toString() ?? '',
      title: json['title']?.toString() ?? 'New chat',
      createdAt: DateTime.tryParse(json['created_at']?.toString() ?? '') ??
          DateTime.now(),
      updatedAt: DateTime.tryParse(json['updated_at']?.toString() ?? '') ??
          DateTime.now(),
      messageCount: (json['message_count'] as num?)?.toInt() ?? 0,
      lastMessage: json['last_message']?.toString(),
    );
  }

  final String id;
  final String title;
  final DateTime createdAt;
  final DateTime updatedAt;
  final int messageCount;
  final String? lastMessage;
}

/// One persisted turn inside an [AiSession] (GET /ai/sessions/{id} detail).
class AiSessionTurnItem {
  const AiSessionTurnItem({
    required this.id,
    required this.role,
    required this.content,
    required this.createdAt,
    this.imageUrl,
    this.matchedProductIds = const <String>[],
  });

  factory AiSessionTurnItem.fromJson(Map<String, dynamic> json) {
    final imageUrl = json['image_url']?.toString();
    return AiSessionTurnItem(
      id: json['id']?.toString() ?? '',
      role: json['role']?.toString() ?? 'assistant',
      content: json['content']?.toString() ?? '',
      imageUrl: (imageUrl == null || imageUrl.isEmpty) ? null : imageUrl,
      matchedProductIds: (json['matched_product_ids'] as List<dynamic>? ??
              const <dynamic>[])
          .map((dynamic id) => id.toString())
          .where((id) => id.isNotEmpty)
          .toList(growable: false),
      createdAt: DateTime.tryParse(json['created_at']?.toString() ?? '') ??
          DateTime.now(),
    );
  }

  final String id;
  final String role;
  final String content;
  final String? imageUrl;
  final List<String> matchedProductIds;
  final DateTime createdAt;
}

/// Full transcript of one saved conversation (session row + messages).
class AiSessionDetail {
  const AiSessionDetail({required this.session, required this.messages});

  factory AiSessionDetail.fromJson(Map<String, dynamic> json) {
    return AiSessionDetail(
      session: AiSession.fromJson(json),
      messages: (json['messages'] as List<dynamic>? ?? const <dynamic>[])
          .whereType<Map<String, dynamic>>()
          .map(AiSessionTurnItem.fromJson)
          .toList(growable: false),
    );
  }

  final AiSession session;
  final List<AiSessionTurnItem> messages;
}

/// One transcript turn the client sends in `history` for POST /ai/chat.
class AiChatTurn {
  const AiChatTurn({required this.role, required this.content});

  final String role; // 'user' | 'assistant'
  final String content;

  Map<String, dynamic> toJson() =>
      <String, dynamic>{'role': role, 'content': content};
}
