export const MAX_CHAT_MESSAGES = 50;
export const MAX_CHAT_CONVERSATIONS = 100;

const CHAT_KEY_PREFIX = 'songmaker:chat:';

export function trimChatHistory<T>(messages: T[]): T[] {
	return messages.length > MAX_CHAT_MESSAGES ? messages.slice(-MAX_CHAT_MESSAGES) : messages;
}

export function pruneOldChatKeys(): void {
	const keys: string[] = [];
	for (let i = 0; i < localStorage.length; i++) {
		const key = localStorage.key(i);
		if (key?.startsWith(CHAT_KEY_PREFIX)) {
			keys.push(key);
		}
	}
	if (keys.length <= MAX_CHAT_CONVERSATIONS) return;

	const keysWithSize = keys.map((key) => {
		try {
			const raw = localStorage.getItem(key);
			const messages: unknown[] = raw ? JSON.parse(raw) : [];
			return { key, count: messages.length };
		} catch {
			return { key, count: 0 };
		}
	});

	keysWithSize.sort((a, b) => a.count - b.count);
	const toRemove = keysWithSize.slice(0, keysWithSize.length - MAX_CHAT_CONVERSATIONS);
	for (const { key } of toRemove) {
		localStorage.removeItem(key);
	}
}
