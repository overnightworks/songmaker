import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ShareResult } from '#lib/api/types.ts';
import { SHARE_BUTTON_COPY_FAILED_TOAST, SHARE_BUTTON_UNSHARED_TOAST } from '#lib/constants.ts';

const addToast = vi.hoisted(() => vi.fn());
vi.mock('#lib/stores/toast.ts', () => ({ addToast }));

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
		iconOnly: false,
		isShared: false,
		shareSlug: null as string | null,
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

function shareButton(target: HTMLElement): HTMLButtonElement {
	const button = target.querySelector<HTMLButtonElement>('.share-btn');
	if (!button) throw new Error('Expected the share button to be rendered');
	return button;
}

async function clickShare(target: HTMLElement) {
	shareButton(target).click();
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
	it.each([false, true])(
		'shares and copies the link, reporting success (icon only: %s)',
		async (iconOnly) => {
			Object.defineProperty(navigator, 'clipboard', {
				value: { writeText: vi.fn().mockResolvedValue(undefined) },
				configurable: true
			});
			const { target, props } = await render({ iconOnly });

			await clickShare(target);

			expect(props.onshare).toHaveBeenCalledTimes(1);
			expect(navigator.clipboard.writeText).toHaveBeenCalledWith('https://example.test/share/abc');
			expect(addToast).toHaveBeenCalledWith('Link copied to clipboard', 'success');
		}
	);

	it.each([false, true])(
		'names the icon action and exposes its sharing state (%s)',
		async (isShared) => {
			const { target } = await render({ iconOnly: true, isShared });
			const button = target.querySelector('button');
			expect(button?.getAttribute('aria-label')).toBe('Share song');
			expect(button?.getAttribute('aria-pressed')).toBe(String(isShared));
			expect(button?.getAttribute('data-hitbox')).toBe('frequent');
		}
	);

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

	it('1480_R4: unshares a shared item, reporting it, without copying a link', async () => {
		Object.defineProperty(navigator, 'clipboard', {
			value: { writeText: vi.fn().mockResolvedValue(undefined) },
			configurable: true
		});
		const { target, props } = await render({ isShared: true, shareSlug: 'abc' });

		await clickShare(target);

		expect(props.onunshare).toHaveBeenCalledTimes(1);
		expect(props.onshare).not.toHaveBeenCalled();
		expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
		expect(addToast).toHaveBeenCalledWith(SHARE_BUTTON_UNSHARED_TOAST, 'success');
	});

	it('1480_R4: is disabled while a share is under way and enabled again once it is done', async () => {
		let finishShare: (result: ShareResult) => void = () => {};
		const { target } = await render({
			onshare: vi.fn<() => Promise<ShareResult>>(
				() => new Promise((resolve) => (finishShare = resolve))
			)
		});

		shareButton(target).click();
		await tick();
		expect(shareButton(target).disabled).toBe(true);

		finishShare(shareResult());
		await vi.waitFor(() => expect(addToast).toHaveBeenCalledTimes(1));
		await tick();
		expect(shareButton(target).disabled).toBe(false);
	});

	it.each([
		{ isShared: false, shareSlug: null, tooltip: 'Share' },
		{ isShared: true, shareSlug: 'abc', tooltip: 'Shared: /share/song/abc' }
	])(
		'1480_R4: titles the button "$tooltip" when isShared is $isShared',
		async ({ tooltip, ...props }) => {
			const { target } = await render(props);

			expect(shareButton(target).title).toBe(tooltip);
		}
	);

	it('1480_R4: draws a different icon once shared', async () => {
		const iconOf = async (isShared: boolean) => {
			const { target } = await render({ isShared });
			return shareButton(target).querySelector('svg')?.innerHTML;
		};

		expect(await iconOf(true)).not.toBe(await iconOf(false));
	});
});
