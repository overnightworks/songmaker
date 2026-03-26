export const MAX_CHAT_MESSAGES = 50;

export function trimChatHistory<T>(messages: T[]): T[] {
	return messages.length > MAX_CHAT_MESSAGES ? messages.slice(-MAX_CHAT_MESSAGES) : messages;
}
