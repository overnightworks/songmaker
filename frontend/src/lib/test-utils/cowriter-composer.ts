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
