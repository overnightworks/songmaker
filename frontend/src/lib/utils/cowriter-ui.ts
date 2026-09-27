import type { ConversationItem, SongItem } from '$lib/api/types';
import {
	COWRITER_ARCHIVED_CONVERSATION_ROW_TEMPLATE,
	COWRITER_ARCHIVED_CONVERSATION_TEMPLATE,
	COWRITER_CONVERSATION_CONFIRM_TEMPLATE,
	COWRITER_CONVERSATION_ROW_TEMPLATE,
	COWRITER_CONVERSATION_SINCE_TEMPLATE,
	COWRITER_NEW_CONVERSATION_LABEL,
	COWRITER_MESSAGE_COUNT_TEMPLATE,
	COWRITER_NEW_CONVERSATION_LINE,
	COWRITER_SINGLE_MESSAGE_COUNT,
	COWRITER_TURN_FAILURE_TEMPLATE,
	DAY_LABEL_TODAY
} from '$lib/constants';
import {
	DAY_LABEL_LOCALE,
	DAYS_NAMED_BY_WEEKDAY,
	localClockTime,
	localWeekday,
	localDaysBetween
} from '$lib/utils/format';

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

interface CowriterTurnFailureFrame {
	provider?: string;
	message?: string;
	reason?: { message?: string };
}

/**
 * The reason text comes from the provider library or the endpoint; the panel
 * only says whose it is — the provider the frame names, else its own.
 */
export function cowriterTurnFailureLabel(
	frame: CowriterTurnFailureFrame,
	panelProvider: string
): string | null {
	const reason = frame.reason?.message ?? frame.message;
	if (!reason) return null;
	return COWRITER_TURN_FAILURE_TEMPLATE.replace(
		'{provider}',
		providerDisplayName(frame.provider ?? panelProvider)
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
	if (daysAgo === 0) return DAY_LABEL_TODAY;
	if (daysAgo < DAYS_NAMED_BY_WEEKDAY) {
		return localWeekday(started);
	}
	const sameYear = started.getFullYear() === now.getFullYear();
	return started.toLocaleDateString(DAY_LABEL_LOCALE, {
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
	const day = conversation ? conversationDayLabel(conversation.created_at, now) : DAY_LABEL_TODAY;
	return COWRITER_CONVERSATION_SINCE_TEMPLATE.replace('{day}', day);
}

export function conversationRowLabel(conversation: ConversationItem, now: Date): string {
	if (conversation.title) return conversation.title;
	if (isNewConversation(conversation)) return COWRITER_NEW_CONVERSATION_LABEL;
	const template = conversation.archived_at
		? COWRITER_ARCHIVED_CONVERSATION_ROW_TEMPLATE
		: COWRITER_CONVERSATION_ROW_TEMPLATE;
	return template
		.replace('{day}', conversationDayLabel(conversation.created_at, now))
		.replace('{time}', localClockTime(new Date(conversation.created_at)));
}

export function conversationMessageCountLabel(count: number): string {
	if (count === 1) return COWRITER_SINGLE_MESSAGE_COUNT;
	return COWRITER_MESSAGE_COUNT_TEMPLATE.replace('{count}', String(count));
}

/** The delete confirm names the conversation as its menu row does, count included. */
export function conversationConfirmLabel(conversation: ConversationItem, now: Date): string {
	return COWRITER_CONVERSATION_CONFIRM_TEMPLATE.replace(
		'{name}',
		conversationRowLabel(conversation, now)
	).replace('{count}', conversationMessageCountLabel(conversation.message_count));
}

/**
 * The menu keeps one order however the server sorts its answer: the active
 * conversation first, then the rest by when they started, newest first —
 * a start never moves, so a re-read list never reshuffles the rows.
 */
export function conversationMenuOrder(
	conversations: ConversationItem[],
	activeConversationId: string | null
): ConversationItem[] {
	const newestFirst = conversations
		.filter((conversation) => conversation.id !== activeConversationId)
		.sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
	const active = conversations.filter((conversation) => conversation.id === activeConversationId);
	return [...active, ...newestFirst];
}
