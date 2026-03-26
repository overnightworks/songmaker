import { describe, expect, it } from 'vitest';
import { trimChatHistory, MAX_CHAT_MESSAGES } from './chat';

function makeMessages(count: number) {
	return Array.from({ length: count }, (_, i) => ({
		role: 'user' as const,
		text: `message-${i}`
	}));
}

describe('trimChatHistory', () => {
	it('returns messages unchanged when under the limit', () => {
		const msgs = makeMessages(10);
		expect(trimChatHistory(msgs)).toEqual(msgs);
	});

	it('returns messages unchanged when exactly at the limit', () => {
		const msgs = makeMessages(MAX_CHAT_MESSAGES);
		expect(trimChatHistory(msgs)).toEqual(msgs);
		expect(trimChatHistory(msgs)).toHaveLength(MAX_CHAT_MESSAGES);
	});

	it('trims to limit keeping newest messages', () => {
		const msgs = makeMessages(MAX_CHAT_MESSAGES + 20);
		const result = trimChatHistory(msgs);
		expect(result).toHaveLength(MAX_CHAT_MESSAGES);
		expect(result[0]).toEqual({ role: 'user', text: 'message-20' });
		expect(result[result.length - 1]).toEqual({
			role: 'user',
			text: `message-${MAX_CHAT_MESSAGES + 19}`
		});
	});

	it('returns same reference when no trimming needed', () => {
		const msgs = makeMessages(5);
		expect(trimChatHistory(msgs)).toBe(msgs);
	});

	it('returns empty array for empty input', () => {
		expect(trimChatHistory([])).toEqual([]);
	});
});

describe('MAX_CHAT_MESSAGES', () => {
	it('is 50', () => {
		expect(MAX_CHAT_MESSAGES).toBe(50);
	});
});
