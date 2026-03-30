import { afterEach, describe, expect, it } from 'vitest';
import {
	trimChatHistory,
	pruneOldChatKeys,
	MAX_CHAT_MESSAGES,
	MAX_CHAT_CONVERSATIONS
} from './chat';

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

describe('pruneOldChatKeys', () => {
	afterEach(() => {
		localStorage.clear();
	});

	it('does nothing when under the limit', () => {
		for (let i = 0; i < 5; i++) {
			localStorage.setItem(`songmaker:chat:song-${i}`, JSON.stringify([{ text: 'hi' }]));
		}
		pruneOldChatKeys();
		let count = 0;
		for (let i = 0; i < localStorage.length; i++) {
			if (localStorage.key(i)?.startsWith('songmaker:chat:')) count++;
		}
		expect(count).toBe(5);
	});

	it('removes conversations with fewest messages first', () => {
		for (let i = 0; i < MAX_CHAT_CONVERSATIONS + 10; i++) {
			const msgCount = i < 10 ? 1 : 20;
			const msgs = Array.from({ length: msgCount }, (_, j) => ({ text: `msg-${j}` }));
			localStorage.setItem(`songmaker:chat:song-${i}`, JSON.stringify(msgs));
		}
		pruneOldChatKeys();
		let remaining = 0;
		for (let i = 0; i < localStorage.length; i++) {
			if (localStorage.key(i)?.startsWith('songmaker:chat:')) remaining++;
		}
		expect(remaining).toBe(MAX_CHAT_CONVERSATIONS);

		for (let i = 0; i < 10; i++) {
			expect(localStorage.getItem(`songmaker:chat:song-${i}`)).toBeNull();
		}
	});

	it('ignores non-chat localStorage keys', () => {
		localStorage.setItem('songmaker:theme', 'dark');
		for (let i = 0; i < MAX_CHAT_CONVERSATIONS + 5; i++) {
			localStorage.setItem(`songmaker:chat:song-${i}`, JSON.stringify([{ text: 'hi' }]));
		}
		pruneOldChatKeys();
		expect(localStorage.getItem('songmaker:theme')).toBe('dark');
	});

	it('handles invalid JSON gracefully', () => {
		for (let i = 0; i < MAX_CHAT_CONVERSATIONS + 5; i++) {
			const value = i < 3 ? 'not-json' : JSON.stringify([{ text: 'hi' }]);
			localStorage.setItem(`songmaker:chat:song-${i}`, value);
		}
		pruneOldChatKeys();
		let remaining = 0;
		for (let i = 0; i < localStorage.length; i++) {
			if (localStorage.key(i)?.startsWith('songmaker:chat:')) remaining++;
		}
		expect(remaining).toBe(MAX_CHAT_CONVERSATIONS);
	});
});
