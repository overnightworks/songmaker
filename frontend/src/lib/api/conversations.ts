import type {
	ChatMessageItem,
	ConversationItem,
	ConversationListResponse,
	ConversationMessagesResponse
} from './types';
import { apiFetch, sseFetch, CHAT_TIMEOUT_MS } from './fetch';

export type CoWriterStreamEvent =
	| { type: 'assistant_text'; text: string }
	| { type: 'tool_call'; tool_use_id: string; name: string; input: Record<string, unknown> }
	| {
			type: 'tool_result';
			tool_use_id: string;
			content: string;
			is_error: boolean;
	  }
	| {
			type: 'final';
			conversation_id: string;
			user_message: ChatMessageItem;
			assistant_message: ChatMessageItem;
	  }
	| { type: 'error'; status: number; message: string };

export function streamCoWriterTurn(
	message: string,
	currentSongId: string | null = null
): AsyncGenerator<CoWriterStreamEvent> {
	return sseFetch<CoWriterStreamEvent>(
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
