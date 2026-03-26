export const MAX_CHAT_MESSAGES = 50;

export interface StoredMessage {
	role: 'user' | 'assistant';
	text: string;
	applied?: boolean;
	applyData?: Record<string, unknown>;
}

export function trimChatHistory<T>(messages: T[]): T[] {
	return messages.length > MAX_CHAT_MESSAGES ? messages.slice(-MAX_CHAT_MESSAGES) : messages;
}
