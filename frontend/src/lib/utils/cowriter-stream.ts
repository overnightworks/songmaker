import type { CoWriterStreamEvent } from '#lib/api/client.ts';
import type { CowriterProblem } from './cowriter-ui.ts';

interface CoWriterToolCall {
	name: string;
	input: Record<string, unknown>;
}

export interface CoWriterMessage {
	persistedId?: string;
	role: 'user' | 'assistant';
	text: string;
	toolCalls?: CoWriterToolCall[];
	/** A tool call ended the round whose words are shown; the next piece starts the next round. */
	roundEnded?: boolean;
	error?: string;
	problem?: CowriterProblem | null;
	waitSeconds?: number;
}

/**
 * The assistant bubble after one stream event. Words of a tool round give way to the next
 * round's words, so the text shown at `final` is already the stored answer. The sent
 * message's stored id is the caller's to set.
 */
export function applyStreamEvent(
	current: CoWriterMessage,
	event: CoWriterStreamEvent
): CoWriterMessage {
	if (event.type === 'assistant_text') {
		const text = current.roundEnded ? event.text : current.text + event.text;
		return { ...current, text, roundEnded: false };
	}
	if (event.type === 'tool_call') {
		const toolCalls = [...(current.toolCalls ?? []), { name: event.name, input: event.input }];
		return { ...current, toolCalls, roundEnded: true };
	}
	if (event.type === 'final') {
		return {
			...current,
			persistedId: event.assistant_message.id,
			text: event.assistant_message.content,
			roundEnded: false
		};
	}
	return current;
}
