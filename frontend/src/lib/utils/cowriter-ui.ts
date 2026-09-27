import type { ConversationItem, SongItem } from '$lib/api/types';
import {
	COWRITER_ARCHIVED_CONVERSATION_ROW_TEMPLATE,
	COWRITER_ARCHIVED_CONVERSATION_TEMPLATE,
	COWRITER_CONVERSATION_ROW_TEMPLATE,
	COWRITER_CONVERSATION_SINCE_TEMPLATE,
	COWRITER_CONVERSATION_STARTED_TODAY,
	COWRITER_NEW_CONVERSATION_LABEL,
	COWRITER_NEW_CONVERSATION_LINE,
	COWRITER_TURN_FAILURE_TEMPLATE
} from '$lib/constants';
import { localDaysBetween } from '$lib/utils/format';

const DAYS_NAMED_BY_WEEKDAY = 7;
const CONVERSATION_DAY_LOCALE = 'en-US';

const SONG_ID_TARGETING_TOOLS = new Set([
	'update_song_lyrics',
	'update_song_prompt',
	'update_song_style',
	'rename_song'
]);

interface CowriterToolCallTarget {
	title: string;
	/** True when this proposal targets a song other than the one currently open. */
	foreign: boolean;
}

/**
 * The co-writer is one global conversation (REQ-COWRITER-01): a tool call
 * streamed while song X is open can still target song Y. Resolve which song
 * a write tool call actually targets from the data the frontend already
 * carries (the tool's own arguments plus the songs already loaded into the
 * editor), so a proposal for another song is visibly attributed instead of
 * looking like it applies to whatever is open.
 */
export function cowriterToolCallTarget(
	toolName: string,
	toolInput: Record<string, unknown>,
	allSongs: SongItem[],
	currentSongId: string
): CowriterToolCallTarget | null {
	if (toolName === 'create_song') {
		return typeof toolInput.title === 'string' ? { title: toolInput.title, foreign: true } : null;
	}
	if (!SONG_ID_TARGETING_TOOLS.has(toolName)) return null;
	const songId = typeof toolInput.song_id === 'string' ? toolInput.song_id : null;
	if (!songId) return null;
	const song = allSongs.find((candidate) => candidate.id === songId);
	if (!song) return null;
	return { title: song.title, foreign: songId !== currentSongId };
}

export function cowriterThinkingLabel(provider: string): string {
	return `${providerDisplayName(provider)} is thinking…`;
}

export function cowriterUnavailableLabel(provider: string): string {
	return `${providerDisplayName(provider)} is currently unavailable`;
}

/** The reason text comes from the provider library; the panel only says whose it is. */
export function cowriterTurnFailureLabel(provider: string, reason: string): string {
	return COWRITER_TURN_FAILURE_TEMPLATE.replace(
		'{provider}',
		providerDisplayName(provider)
	).replace('{reason}', reason);
}

export function providerDisplayName(provider: string): string {
	return provider.charAt(0).toUpperCase() + provider.slice(1);
}

export function cowriterHeaderLabel(provider: string, model: string): string {
	if (!model) return 'Co-Writer';
	return `${providerDisplayName(provider)} · ${model}`;
}

/** The one English day form every conversation label uses: "today", "Tue", "Sep 12", "Sep 12, 2025". */
function conversationDayLabel(createdAt: string, now: Date): string {
	const started = new Date(createdAt);
	const daysAgo = localDaysBetween(started, now);
	if (daysAgo === 0) return COWRITER_CONVERSATION_STARTED_TODAY;
	if (daysAgo < DAYS_NAMED_BY_WEEKDAY) {
		return started.toLocaleDateString(CONVERSATION_DAY_LOCALE, { weekday: 'short' });
	}
	const sameYear = started.getFullYear() === now.getFullYear();
	return started.toLocaleDateString(CONVERSATION_DAY_LOCALE, {
		day: 'numeric',
		month: 'short',
		year: sameYear ? undefined : 'numeric'
	});
}

/** A live conversation nobody has written in yet; the line and its menu row both ask this. */
function isNewConversation(
	conversation: ConversationItem | undefined,
	chatHasMessages = false
): boolean {
	if (conversation?.archived_at) return false;
	return !chatHasMessages && (conversation?.message_count ?? 0) === 0;
}

/**
 * The line above the chat never contradicts the chat: a message in it means
 * a conversation is running, even before the conversation list has caught up
 * with the first turn; an empty conversation is a new one.
 */
export function conversationLineLabel(
	conversation: ConversationItem | undefined,
	chatHasMessages: boolean,
	now: Date
): string {
	if (conversation?.archived_at) {
		return COWRITER_ARCHIVED_CONVERSATION_TEMPLATE.replace(
			'{day}',
			conversationDayLabel(conversation.created_at, now)
		);
	}
	if (isNewConversation(conversation, chatHasMessages)) return COWRITER_NEW_CONVERSATION_LINE;
	const day = conversation
		? conversationDayLabel(conversation.created_at, now)
		: COWRITER_CONVERSATION_STARTED_TODAY;
	return COWRITER_CONVERSATION_SINCE_TEMPLATE.replace('{day}', day);
}

export function conversationRowLabel(conversation: ConversationItem, now: Date): string {
	if (conversation.title) return conversation.title;
	if (isNewConversation(conversation)) return COWRITER_NEW_CONVERSATION_LABEL;
	const template = conversation.archived_at
		? COWRITER_ARCHIVED_CONVERSATION_ROW_TEMPLATE
		: COWRITER_CONVERSATION_ROW_TEMPLATE;
	return template.replace('{day}', conversationDayLabel(conversation.created_at, now));
}
