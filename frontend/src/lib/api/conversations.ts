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

export interface CoWriterTurnRequest {
	message: string;
	current_song_id: string | null;
	mentioned_song_ids?: string[];
	mentioned_version_ids?: string[];
	mentioned_album_id?: string | null;
	current_generation_id?: string | null;
}

export function streamCoWriterTurn(req: CoWriterTurnRequest): AsyncGenerator<CoWriterStreamEvent> {
	return sseFetch<CoWriterStreamEvent>(
		'/api/chat/turn',
		{
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				message: req.message,
				current_song_id: req.current_song_id,
				mentioned_song_ids: req.mentioned_song_ids ?? [],
				mentioned_version_ids: req.mentioned_version_ids ?? [],
				mentioned_album_id: req.mentioned_album_id ?? null,
				current_generation_id: req.current_generation_id ?? null
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
