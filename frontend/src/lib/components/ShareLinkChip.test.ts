import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SHARE_LINK_COPIED_TOAST, SHARE_LINK_COPY_FAILED_TOAST } from '$lib/constants';

const addToast = vi.hoisted(() => vi.fn());
vi.mock('$lib/stores/toast', () => ({ addToast }));

import ShareLinkChip from './ShareLinkChip.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

async function render(url = 'https://example.test/share/song/abc123') {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(ShareLinkChip, { target, props: { url } }));
	await tick();
	return { target, url };
}

function chipButton(target: HTMLElement): HTMLButtonElement {
	const button = target.querySelector<HTMLButtonElement>('.share-link-chip');
	if (!button) throw new Error('Expected the share link chip button');
	return button;
}

beforeEach(() => {
	addToast.mockClear();
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
});

describe('ShareLinkChip', () => {
	it('renders a designed chip instead of the raw URL as page text', async () => {
		const { target, url } = await render();

		const button = chipButton(target);
		expect(button.textContent?.trim()).toBe('Copy link');
		expect(target.textContent).not.toContain(url);
		expect(button.title).toBe(url);
	});

	it('copies the share URL to the clipboard and reports success', async () => {
		Object.defineProperty(navigator, 'clipboard', {
			value: { writeText: vi.fn().mockResolvedValue(undefined) },
			configurable: true
		});
		const { target, url } = await render('https://example.test/share/song/xyz789');

		chipButton(target).click();
		await vi.waitFor(() => expect(addToast).toHaveBeenCalledTimes(1));

		expect(navigator.clipboard.writeText).toHaveBeenCalledWith(url);
		expect(addToast).toHaveBeenCalledWith(SHARE_LINK_COPIED_TOAST, 'success');
	});

	it('reports a copy failure without crashing when the clipboard write throws', async () => {
		Object.defineProperty(navigator, 'clipboard', {
			value: { writeText: vi.fn().mockRejectedValue(new Error('no clipboard permission')) },
			configurable: true
		});
		const { target } = await render();

		chipButton(target).click();
		await vi.waitFor(() => expect(addToast).toHaveBeenCalledTimes(1));

		expect(addToast).toHaveBeenCalledWith(SHARE_LINK_COPY_FAILED_TOAST, 'error');
	});
});
