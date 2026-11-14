import { tick } from 'svelte';
import { kitWords } from '#lib/utils/kit-words.ts';
import { words } from '#lib/words/en.ts';

const COMPOSER_SELECTOR = `textarea[aria-label="${kitWords()['helperChat.composerLabel']({ name: words['cowriter.title'] })}"]`;

/** The co-writer's message field inside `target`. */
export const composerOf = (target: ParentNode) =>
	target.querySelector<HTMLTextAreaElement>(COMPOSER_SELECTOR);

/** The co-writer's Send button inside `target`. */
export function sendButtonOf(target: ParentNode): HTMLButtonElement | undefined {
	return Array.from(target.querySelectorAll<HTMLButtonElement>('button')).find(
		(button) => button.textContent?.trim() === kitWords()['helperChat.send']
	);
}

/** Types `text` into the co-writer's field and presses Send. */
export async function sendToCowriter(target: ParentNode, text: string): Promise<void> {
	const input = composerOf(target);
	if (!input) throw new Error('Expected the chat textarea');
	input.value = text;
	input.dispatchEvent(new Event('input', { bubbles: true }));
	await tick();
	sendButtonOf(target)?.click();
}

export type ChatSpeaker = 'person' | 'helper';

const helperName = () => words['cowriter.title'];

const speakerLabel = (speaker: ChatSpeaker) =>
	kitWords()['helperChat.speaker']({
		name: speaker === 'person' ? kitWords()['helperChat.you'] : helperName()
	});

/** The co-writer's named message list; absent while the conversation is empty. */
export const chatListOf = (target: ParentNode) =>
	target.querySelector<HTMLOListElement>(
		`ol[role="list"][aria-label="${kitWords()['helperChat.listLabel']({ name: helperName() })}"]`
	);

/** The chat's messages in order, optionally only those of one speaker. */
export function chatMessagesOf(target: ParentNode, speaker?: ChatSpeaker): HTMLLIElement[] {
	const messages = Array.from(chatListOf(target)?.querySelectorAll<HTMLLIElement>('li') ?? []);
	if (speaker === undefined) return messages;
	const label = speakerLabel(speaker);
	return messages.filter((message) => message.textContent?.startsWith(label));
}

/** What a message says: its text without the speaker prefix, the AI mark and a failure note. */
export function messageTextOf(message: HTMLLIElement): string {
	const shown = message.cloneNode(true) as HTMLLIElement;
	for (const note of shown.querySelectorAll('[role="alert"]')) note.remove();
	for (const mark of shown.querySelectorAll('span')) if (mark.textContent === 'AI') mark.remove();
	const text = (shown.textContent ?? '').replace(/\s+/g, ' ').trim();
	const prefix = [speakerLabel('person'), speakerLabel('helper')].find((label) =>
		text.startsWith(label)
	);
	return prefix === undefined ? text : text.slice(prefix.length).trim();
}

/** The button the archived conversation's banner offers, by its accessible name. */
export function archivedBannerButtonOf(target: ParentNode): HTMLButtonElement | undefined {
	const link = words['cowriter.archivedBanner'].find((part) => typeof part !== 'string');
	if (link === undefined || typeof link === 'string') throw new Error('Expected a banner link');
	return Array.from(target.querySelectorAll<HTMLButtonElement>('button')).find(
		(button) => button.textContent?.trim() === link.text
	);
}
