import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import ChatInput from './ChatInput.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
});

async function render(disabled: boolean, onsend = vi.fn()) {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(
		mount(ChatInput, {
			target,
			props: { value: '', disabled, oninput: vi.fn(), onkeydown: vi.fn(), onsend }
		})
	);
	await tick();
	return target;
}

function sendButton(target: HTMLElement): HTMLButtonElement {
	const button = target.querySelector('button');
	if (!button) throw new Error('Expected the Send button');
	return button;
}

describe('ChatInput', () => {
	it('asks for a rewrite and offers Send as a worded primary, as frame 7 draws the composer', async () => {
		const target = await render(false);

		expect(target.querySelector('textarea')?.placeholder).toBe('Ask for a rewrite…');
		expect(sendButton(target).textContent?.trim()).toBe('Send');
	});

	it('sends when Send is pressed', async () => {
		const onsend = vi.fn();
		const target = await render(false, onsend);

		sendButton(target).click();

		expect(onsend).toHaveBeenCalledOnce();
	});

	it('keeps Send unavailable while there is nothing to send', async () => {
		const onsend = vi.fn();
		const target = await render(true, onsend);

		sendButton(target).click();

		expect(sendButton(target).disabled).toBe(true);
		expect(onsend).not.toHaveBeenCalled();
	});
});
