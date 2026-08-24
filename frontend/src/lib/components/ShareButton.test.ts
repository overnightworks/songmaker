import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ShareResult } from '$lib/api/types';
import { SHARE_BUTTON_COPY_FAILED_TOAST } from '$lib/constants';

const addToast = vi.hoisted(() => vi.fn());
vi.mock('$lib/stores/toast', () => ({ addToast }));

import ShareButton from './ShareButton.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

function shareResult(overrides: Partial<ShareResult> = {}): ShareResult {
	return {
		status: 'ok',
		share_url: 'https://example.test/share/abc',
		share_slug: 'abc',
		songs_without_playable_take: [],
		...overrides
	};
}

function defaultProps() {
	return {
		isShared: false,
		shareSlug: null,
		onshare: vi.fn<() => Promise<ShareResult>>().mockResolvedValue(shareResult()),
		onunshare: vi.fn().mockResolvedValue(undefined)
	};
}

async function render(overrides: Partial<ReturnType<typeof defaultProps>> = {}) {
	const target = document.createElement('div');
	document.body.append(target);
	const props = { ...defaultProps(), ...overrides };
	mounted.push(mount(ShareButton, { target, props }));
	await tick();
	return { target, props };
}

async function clickShare(target: HTMLElement) {
	target.querySelector<HTMLButtonElement>('.share-btn')?.click();
	await vi.waitFor(() => expect(addToast).toHaveBeenCalledTimes(1));
}

beforeEach(() => {
	addToast.mockClear();
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
});

describe('ShareButton', () => {
	it('shares and copies the link, reporting success', async () => {
		Object.defineProperty(navigator, 'clipboard', {
			value: { writeText: vi.fn().mockResolvedValue(undefined) },
			configurable: true
		});
		const { target, props } = await render();

		await clickShare(target);

		expect(props.onshare).toHaveBeenCalledTimes(1);
		expect(navigator.clipboard.writeText).toHaveBeenCalledWith('https://example.test/share/abc');
		expect(addToast).toHaveBeenCalledWith('Link copied to clipboard', 'success');
	});

	it('reports Share failed when the share itself throws, without touching the clipboard', async () => {
		Object.defineProperty(navigator, 'clipboard', {
			value: { writeText: vi.fn().mockResolvedValue(undefined) },
			configurable: true
		});
		const { target } = await render({
			onshare: vi.fn<() => Promise<ShareResult>>().mockRejectedValue(new Error('network down'))
		});

		await clickShare(target);

		expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
		expect(addToast).toHaveBeenCalledWith('Share failed', 'error');
		expect(addToast).not.toHaveBeenCalledWith(expect.stringContaining('copy'), expect.anything());
	});

	it('reports the share as successful, not failed, when the share succeeds but the clipboard write throws', async () => {
		// Regression for #235: a clipboard failure after a successful share
		// used to fall through to the same catch as the share call and show
		// "Share failed" even though the server-side share had already
		// succeeded (200, slug created). This is red on the pre-fix
		// single-try/catch version and green after separating the two.
		Object.defineProperty(navigator, 'clipboard', {
			value: { writeText: vi.fn().mockRejectedValue(new Error('no clipboard permission')) },
			configurable: true
		});
		const { target, props } = await render();

		await clickShare(target);

		expect(props.onshare).toHaveBeenCalledTimes(1);
		expect(addToast).not.toHaveBeenCalledWith('Share failed', 'error');
		expect(addToast).toHaveBeenCalledWith(SHARE_BUTTON_COPY_FAILED_TOAST, 'success');
	});
});
