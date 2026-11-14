import type {
	ChatTurnFailureFrame,
	ChatTurnProblemFrame,
	ConversationItem,
	SongItem
} from '#lib/api/types.ts';
import { COWRITER_BUSY_WAIT_CEILING_SECONDS } from '#lib/constants/cowriter.ts';
import { pageLanguage } from './page-language.ts';
import { pageText, type TextKey } from '#lib/utils/page-words.ts';
import {
	DAYS_NAMED_BY_WEEKDAY,
	localClockTime,
	localWeekday,
	localDaysBetween
} from '#lib/utils/format.ts';

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

export type CowriterProblem = ChatTurnProblemFrame['problem'];

/** How a turn that could not run reads in the panel; `problem` is null for the endpoint's own failure message. */
export interface CowriterTurnError {
	problem: CowriterProblem | null;
	text: string;
	waitSeconds: number;
}

const COWRITER_PROBLEM_KEYS: Record<CowriterProblem, TextKey> = {
	unavailable: 'cowriterProblem.unavailable',
	busy: 'cowriterProblem.busy',
	budget_spent: 'cowriterProblem.budgetSpent',
	not_enabled: 'cowriterProblem.notEnabled',
	sign_in_again: 'cowriterProblem.signInAgain'
};

/** The sentence of a problem, read when it is shown so a later language load changes nothing here. */
export function cowriterProblemText(problem: CowriterProblem): string {
	return pageText(COWRITER_PROBLEM_KEYS[problem]);
}

/** The sentence of a turn that ended with no answer and no named problem. */
export function cowriterNoAnswerText(): string {
	return pageText('cowriterProblem.noAnswer');
}

export function cowriterTurnError(
	frame: ChatTurnProblemFrame | ChatTurnFailureFrame
): CowriterTurnError | null {
	if (!('problem' in frame)) {
		return frame.message ? { problem: null, text: frame.message, waitSeconds: 0 } : null;
	}
	const requestedWait = frame.problem === 'busy' ? (frame.retry_after_seconds ?? 0) : 0;
	return {
		problem: frame.problem,
		text: cowriterProblemText(frame.problem),
		waitSeconds: Math.min(requestedWait, COWRITER_BUSY_WAIT_CEILING_SECONDS)
	};
}

/** The tone and glyph a named problem is drawn in: red only where the person alone can end it. */
export const COWRITER_PROBLEM_LOOKS: Record<CowriterProblem, { tone: string; icon: string }> = {
	sign_in_again: { tone: 'bad', icon: 'triangle-alert' },
	busy: { tone: 'wait', icon: 'clock' },
	budget_spent: { tone: 'wait', icon: 'clock' },
	not_enabled: { tone: 'off', icon: 'ban' },
	unavailable: { tone: 'wait', icon: 'circle-alert' }
};

/** The one day form every conversation label uses, in the page's language: "today", "Tue", "Sep 12", "Sep 12, 2025". */
function conversationDayLabel(createdAt: string, now: Date): string {
	const started = new Date(createdAt);
	const daysAgo = localDaysBetween(started, now);
	if (daysAgo === 0) return pageText('cowriter.today');
	if (daysAgo < DAYS_NAMED_BY_WEEKDAY) {
		return localWeekday(started);
	}
	const sameYear = started.getFullYear() === now.getFullYear();
	return started.toLocaleDateString(pageLanguage(), {
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
		return pageText('cowriter.lineArchived', {
			day: conversationDayLabel(conversation.created_at, now)
		});
	}
	if (isNewConversation(conversation, chatHasMessages))
		return pageText('cowriter.newConversationLine');
	const day = conversation
		? conversationDayLabel(conversation.created_at, now)
		: pageText('cowriter.today');
	return pageText('cowriter.lineSince', { day });
}

export function conversationRowLabel(conversation: ConversationItem, now: Date): string {
	if (conversation.title) return conversation.title;
	if (isNewConversation(conversation)) return pageText('cowriter.newConversation');
	const gaps = {
		day: conversationDayLabel(conversation.created_at, now),
		time: localClockTime(new Date(conversation.created_at))
	};
	return pageText(
		conversation.archived_at ? 'cowriter.archivedRow' : 'cowriter.conversationSince',
		gaps
	);
}

export function conversationMessageCountLabel(count: number): string {
	return pageText('cowriter.messageCount', count);
}

/** The delete confirm names the conversation as its menu row does, count included. */
export function conversationConfirmLabel(conversation: ConversationItem, now: Date): string {
	return pageText('cowriter.confirmRow', {
		name: conversationRowLabel(conversation, now),
		messages: conversationMessageCountLabel(conversation.message_count)
	});
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
