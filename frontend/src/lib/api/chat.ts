import type { ChatHistoryResult, ChatTurnResult, RecentChatItem } from './types';
import { apiFetch, CHAT_TIMEOUT_MS } from './fetch';

export async function sendChatMessage(
	songId: string,
	message: string,
	mentionedSongIds: string[] = [],
	mentionedVersionIds: string[] = []
): Promise<ChatTurnResult> {
	return apiFetch<ChatTurnResult>(
		`/api/songs/${songId}/chat`,
		{
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				message,
				mentioned_song_ids: mentionedSongIds,
				mentioned_version_ids: mentionedVersionIds
			})
		},
		CHAT_TIMEOUT_MS
	);
}

export async function fetchChatHistory(songId: string): Promise<ChatHistoryResult> {
	return apiFetch<ChatHistoryResult>(`/api/songs/${songId}/chat`);
}

export async function clearChatHistory(songId: string): Promise<void> {
	await apiFetch(`/api/songs/${songId}/chat`, { method: 'DELETE' });
}

export async function fetchRecentChats(): Promise<RecentChatItem[]> {
	return apiFetch<RecentChatItem[]>('/api/chat/recent');
}
