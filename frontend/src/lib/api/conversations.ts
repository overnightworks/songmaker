import type {
	ChatTurnV2Result,
	ConversationItem,
	ConversationListResponse,
	ConversationMessagesResponse
} from './types';
import { apiFetch, CHAT_TIMEOUT_MS } from './fetch';

export async function sendCoWriterTurn(
	message: string,
	currentSongId: string | null = null
): Promise<ChatTurnV2Result> {
	return apiFetch<ChatTurnV2Result>(
		'/api/chat/turn',
		{
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				message,
				current_song_id: currentSongId
			})
		},
		CHAT_TIMEOUT_MS
	);
}

export async function fetchConversations(): Promise<ConversationItem[]> {
	const result = await apiFetch<ConversationListResponse>('/api/conversations');
	return result.conversations;
}

export async function fetchConversationMessages(
	conversationId: string
): Promise<ConversationMessagesResponse> {
	return apiFetch<ConversationMessagesResponse>(`/api/conversations/${conversationId}`);
}

export async function startNewConversation(): Promise<ConversationItem> {
	return apiFetch<ConversationItem>('/api/conversations/new', { method: 'POST' });
}

export async function deleteConversation(conversationId: string): Promise<void> {
	await apiFetch(`/api/conversations/${conversationId}`, { method: 'DELETE' });
}
