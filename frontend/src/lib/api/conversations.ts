import type {
	AssistantTextEvent,
	ChatTurnFailureFrame,
	ChatTurnFinalFrame,
	ChatTurnRouteErrorFrame,
	ChatTurnV2Request,
	ConversationItem,
	ConversationListResponse,
	ConversationMessagesResponse,
	ToolCallEvent,
	ToolResultEvent
} from './types';
import { COWRITER_TURN_PATH, COWRITER_TURN_TIMEOUT_MS } from '$lib/constants';
import { apiFetch, sseFetch } from './fetch';

export type CoWriterStreamEvent =
	| AssistantTextEvent
	| ToolCallEvent
	| ToolResultEvent
	| ChatTurnFinalFrame
	| ChatTurnRouteErrorFrame
	| ChatTurnFailureFrame;

export function streamCoWriterTurn(req: ChatTurnV2Request): AsyncGenerator<CoWriterStreamEvent> {
	return sseFetch<CoWriterStreamEvent>(
		COWRITER_TURN_PATH,
		{
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(req)
		},
		COWRITER_TURN_TIMEOUT_MS
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
