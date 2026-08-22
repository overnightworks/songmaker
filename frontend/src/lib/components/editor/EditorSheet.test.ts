import { createRawSnippet, mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import EditorSheet from './EditorSheet.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
});

const contentSnippet = createRawSnippet(() => ({
	render: () => `<button id="inner">Inner</button>`
}));

async function render(open: boolean, onclose = vi.fn()) {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(
		mount(EditorSheet, {
			target,
			props: { open, label: 'Recipe', onclose, children: contentSnippet }
		})
	);
	await tick();
	return { target, onclose };
}

describe('EditorSheet', () => {
	it('renders nothing when closed', async () => {
		const { target } = await render(false);
		expect(target.querySelector('.sheet-panel')).toBeNull();
	});

	it('renders a modal bottom sheet with the given content when open', async () => {
		const { target } = await render(true);
		const panel = target.querySelector('.sheet-panel');
		expect(panel).not.toBeNull();
		expect(panel?.getAttribute('aria-modal')).toBe('true');
		expect(panel?.getAttribute('aria-label')).toBe('Recipe');
		expect(target.querySelector('#inner')).not.toBeNull();
	});

	it('closes on backdrop click and on Escape', async () => {
		const { target, onclose } = await render(true);
		target.querySelector<HTMLButtonElement>('.sheet-backdrop')?.click();
		expect(onclose).toHaveBeenCalledTimes(1);

		const { onclose: onclose2 } = await render(true);
		window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
		expect(onclose2).toHaveBeenCalledTimes(1);
	});
});
