import { makeSong as song } from '$lib/test-utils/factories';
import { describe, expect, it } from 'vitest';

import type { ConversationItem } from '$lib/api/types';
import {
	conversationLineLabel,
	conversationRowLabel,
	cowriterHeaderLabel,
	cowriterThinkingLabel,
	cowriterToolCallTarget,
	cowriterTurnFailureLabel,
	cowriterUnavailableLabel,
	providerDisplayName
} from './cowriter-ui';

describe('co-writer provider copy', () => {
	it('names the active provider by its display name in the header, thinking and unavailable copy', () => {
		expect(cowriterHeaderLabel('grok', 'grok-4.6')).toBe('Grok · grok-4.6');
		expect(cowriterThinkingLabel('claude')).toBe('Claude is thinking…');
		expect(cowriterThinkingLabel('codex')).toBe('Codex is thinking…');
		expect(cowriterUnavailableLabel('grok')).toBe('Grok is currently unavailable');
	});

	it.each([
		[
			'the provider its frame names',
			{ provider: 'grok', reason: { message: 'Route is unavailable.' } },
			'Grok: Route is unavailable.'
		],
		[
			'the panel’s provider when the frame names none',
			{ reason: { message: 'CLI is unavailable.' } },
			'Claude: CLI is unavailable.'
		],
		[
			'the panel’s provider in front of the endpoint’s own message',
			{ message: 'Chat request failed' },
			'Claude: Chat request failed'
		]
	])('names %s in front of the reason a turn failed for', (_case, frame, label) => {
		expect(cowriterTurnFailureLabel(frame, 'claude')).toBe(label);
	});

	it('names no failure for a frame that carries no reason', () => {
		expect(cowriterTurnFailureLabel({ provider: 'grok' }, 'claude')).toBeNull();
	});

	it.each([
		['claude', 'Claude'],
		['codex', 'Codex'],
		['openai', 'Openai']
	])('shows the provider id %s as %s, the one spelling every surface uses', (id, name) => {
		expect(providerDisplayName(id)).toBe(name);
	});
});

describe('cowriterToolCallTarget', () => {
	const allSongs = [
		song({ slug: 'open-song', generation_count: 0, title: 'Open Song' }),
		song({ slug: 'open-song', generation_count: 0, id: 's2', title: 'Other Song' })
	];

	it('resolves a write-tool target and flags it foreign when it is not the open song', () => {
		expect(cowriterToolCallTarget('update_song_lyrics', { song_id: 's2' }, allSongs, 's1')).toEqual(
			{ title: 'Other Song', foreign: true }
		);
	});

	it('resolves a write-tool target without the foreign flag when it targets the open song', () => {
		expect(cowriterToolCallTarget('update_song_prompt', { song_id: 's1' }, allSongs, 's1')).toEqual(
			{ title: 'Open Song', foreign: false }
		);
	});

	it('treats create_song as always foreign since it is not the song currently open', () => {
		expect(cowriterToolCallTarget('create_song', { title: 'Brand New' }, allSongs, 's1')).toEqual({
			title: 'Brand New',
			foreign: true
		});
	});

	it('returns null for read-only tools that carry no song target', () => {
		expect(cowriterToolCallTarget('list_songs', {}, allSongs, 's1')).toBeNull();
		expect(cowriterToolCallTarget('search_songs', { query: 'x' }, allSongs, 's1')).toBeNull();
	});

	it('returns null when the referenced song_id is not among the loaded songs', () => {
		expect(
			cowriterToolCallTarget('rename_song', { song_id: 's-missing' }, allSongs, 's1')
		).toBeNull();
	});
});

describe('conversation day and line copy', () => {
	const now = new Date('2026-09-27T12:00:00');

	function conversationFrom(
		createdAt: string,
		overrides: Partial<ConversationItem> = {}
	): ConversationItem {
		return {
			id: 'c1',
			title: null,
			message_count: 2,
			archived_at: null,
			created_at: createdAt,
			updated_at: createdAt,
			last_message_at: null,
			...overrides
		};
	}

	it.each([
		['no conversation and an empty chat', undefined, false, 'new conversation'],
		[
			'a first message the conversation list does not know yet',
			undefined,
			true,
			'conversation since today'
		],
		[
			'a new empty conversation',
			conversationFrom('2026-09-27T08:00:00', { message_count: 0 }),
			false,
			'new conversation'
		],
		[
			'a new conversation whose first message is in the chat',
			conversationFrom('2026-09-27T08:00:00', { message_count: 0 }),
			true,
			'conversation since today'
		],
		[
			'a conversation with messages',
			conversationFrom('2026-09-22T10:00:00'),
			true,
			'conversation since Tue'
		],
		[
			'an archived conversation',
			conversationFrom('2026-09-20T10:00:00', { archived_at: '2026-09-22T10:00:00' }),
			true,
			'archived conversation from Sep 20'
		]
	])('reads the line for %s', (_case, conversation, chatHasMessages, line) => {
		expect(conversationLineLabel(conversation, chatHasMessages, now)).toBe(line);
	});

	it.each([
		['one started today', conversationFrom('2026-09-27T08:00:00'), 'Conversation since today'],
		[
			'one started this week by weekday',
			conversationFrom('2026-09-22T10:00:00'),
			'Conversation since Tue'
		],
		[
			'one started earlier this year by month and day',
			conversationFrom('2026-09-12T10:00:00'),
			'Conversation since Sep 12'
		],
		[
			'an archived one from an earlier year with the year',
			conversationFrom('2025-09-17T10:00:00', { archived_at: '2025-09-20T10:00:00' }),
			'Conversation from Sep 17, 2025'
		],
		[
			'an empty one as a new conversation, like the line above the chat',
			conversationFrom('2026-09-22T10:00:00', { message_count: 0 }),
			'New conversation'
		],
		[
			'an empty archived one by its day',
			conversationFrom('2026-09-20T10:00:00', {
				message_count: 0,
				archived_at: '2026-09-22T10:00:00'
			}),
			'Conversation from Sep 20'
		],
		[
			'a titled one',
			conversationFrom('2026-09-22T10:00:00', { title: 'Bridge ideas' }),
			'Bridge ideas'
		]
	])('names %s in the conversation menu with the same day form', (_case, conversation, label) => {
		expect(conversationRowLabel(conversation, now)).toBe(label);
	});
});
