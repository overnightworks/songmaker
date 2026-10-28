import { makeSong as song } from '$lib/test-utils/factories';
import { describe, expect, it } from 'vitest';

import { COWRITER_BUSY_WAIT_CEILING_SECONDS } from '$lib/constants';
import type { ChatTurnFailureFrame, ChatTurnProblemFrame, ConversationItem } from '$lib/api/types';
import {
	conversationConfirmLabel,
	conversationLineLabel,
	conversationMenuOrder,
	conversationMessageCountLabel,
	conversationRowLabel,
	cowriterThinkingLabel,
	cowriterToolCallTarget,
	cowriterTurnError,
	cowriterWaitClock,
	providerDisplayName,
	type CowriterTurnError
} from './cowriter-ui';

describe('co-writer copy', () => {
	it('A-thinking names no vendor in the thinking line', () => {
		expect(cowriterThinkingLabel()).toBe('Co-writer is thinking…');
	});

	it.each([
		[
			'sign in again, with no wait',
			{ type: 'error', status: 401, problem: 'sign_in_again', retry_after_seconds: null },
			{ problem: 'sign_in_again', text: 'Sign in again to use the co-writer', waitSeconds: 0 }
		],
		[
			'busy, with the service’s own wait',
			{ type: 'error', status: 429, problem: 'busy', retry_after_seconds: 40 },
			{ problem: 'busy', text: 'The co-writer is busy', waitSeconds: 40 }
		],
		[
			'busy without a stated wait',
			{ type: 'error', status: 429, problem: 'busy', retry_after_seconds: null },
			{ problem: 'busy', text: 'The co-writer is busy', waitSeconds: 0 }
		],
		[
			'busy with a wait the panel does not promise',
			{ type: 'error', status: 429, problem: 'busy', retry_after_seconds: 86_400 },
			{
				problem: 'busy',
				text: 'The co-writer is busy',
				waitSeconds: COWRITER_BUSY_WAIT_CEILING_SECONDS
			}
		],
		[
			'not enabled, as the account has none',
			{ type: 'error', status: 403, problem: 'not_enabled', retry_after_seconds: null },
			{
				problem: 'not_enabled',
				text: 'The co-writer is not enabled for your account',
				waitSeconds: 0
			}
		],
		[
			'unavailable',
			{ type: 'error', status: 503, problem: 'unavailable', retry_after_seconds: null },
			{ problem: 'unavailable', text: 'The co-writer is unavailable', waitSeconds: 0 }
		],
		[
			'the endpoint’s own failure message, with no named problem',
			{ type: 'error', status: 500, message: 'Chat request failed' },
			{ problem: null, text: 'Chat request failed', waitSeconds: 0 }
		]
	] satisfies Array<[string, ChatTurnProblemFrame | ChatTurnFailureFrame, CowriterTurnError]>)(
		'C8 words a turn that ended as %s',
		(_case, frame, error) => {
			expect(cowriterTurnError(frame)).toEqual(error);
		}
	);

	it('defect:#1856: names no failure for a frame that carries an empty message', () => {
		expect(cowriterTurnError({ type: 'error', status: 500, message: '' })).toBeNull();
	});

	it.each([
		[0, '0:00'],
		[40, '0:40'],
		[65, '1:05'],
		[COWRITER_BUSY_WAIT_CEILING_SECONDS, '5:00']
	])('C8 shows a wait of %i seconds as %s', (seconds, clock) => {
		expect(cowriterWaitClock(seconds)).toBe(clock);
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
		[
			'one started today',
			conversationFrom('2026-09-27T09:12:00'),
			'Conversation since today 09:12'
		],
		[
			'an archived one started earlier today',
			conversationFrom('2026-09-27T07:30:00', { archived_at: '2026-09-27T09:12:00' }),
			'Archived · today 07:30'
		],
		[
			'one started this week by weekday',
			conversationFrom('2026-09-22T10:00:00'),
			'Conversation since Tue 10:00'
		],
		[
			'one started earlier this year by month and day',
			conversationFrom('2026-09-12T10:00:00'),
			'Conversation since Sep 12 10:00'
		],
		[
			'an archived one from an earlier year with the year',
			conversationFrom('2025-09-17T10:00:00', { archived_at: '2025-09-20T10:00:00' }),
			'Archived · Sep 17, 2025 10:00'
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
			'Archived · Sep 20 10:00'
		],
		[
			'a titled one',
			conversationFrom('2026-09-22T10:00:00', { title: 'Bridge ideas' }),
			'Bridge ideas'
		]
	])('names %s in the conversation menu with the same day form', (_case, conversation, label) => {
		expect(conversationRowLabel(conversation, now)).toBe(label);
	});

	it.each([
		[1, '1 msg'],
		[4, '4 msgs'],
		[0, '0 msgs']
	])('counts %i message(s) as “%s”', (count, label) => {
		expect(conversationMessageCountLabel(count)).toBe(label);
	});

	it('names the conversation a delete confirm asks about by its row name and count', () => {
		expect(
			conversationConfirmLabel(conversationFrom('2026-09-27T09:12:00', { message_count: 4 }), now)
		).toBe('Conversation since today 09:12 · 4 msgs');
		expect(
			conversationConfirmLabel(
				conversationFrom('2026-09-27T07:30:00', {
					message_count: 2,
					archived_at: '2026-09-27T09:12:00'
				}),
				now
			)
		).toBe('Archived · today 07:30 · 2 msgs');
	});

	it('lists the active conversation first, then the rest newest first, whatever order they arrive in', () => {
		const active = conversationFrom('2026-09-20T10:00:00', { id: 'active' });
		const newer = conversationFrom('2026-09-26T10:00:00', {
			id: 'newer',
			archived_at: '2026-09-27T08:00:00'
		});
		const older = conversationFrom('2026-09-24T10:00:00', {
			id: 'older',
			archived_at: '2026-09-25T08:00:00'
		});
		const order = (list: ConversationItem[]) =>
			conversationMenuOrder(list, 'active').map((conversation) => conversation.id);

		expect(order([older, active, newer])).toEqual(['active', 'newer', 'older']);
		expect(order([newer, older, active])).toEqual(['active', 'newer', 'older']);
	});
});
