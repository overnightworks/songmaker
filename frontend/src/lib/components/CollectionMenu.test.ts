import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ShareResult } from '$lib/api/types';
import CollectionMenu from './CollectionMenu.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];
const SHARE_WARNING_LABEL = 'Missing from the share page';

beforeEach(() => {
	Object.defineProperty(navigator, 'clipboard', {
		value: { writeText: vi.fn().mockResolvedValue(undefined) },
		configurable: true
	});
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
});

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
		kind: 'album' as 'album' | 'playlist',
		title: 'Test Album',
		isShared: false,
		shareSlug: null,
		onshare: vi.fn<() => Promise<ShareResult>>().mockResolvedValue(shareResult()),
		onunshare: vi.fn(),
		onrename: vi.fn(),
		ondelete: vi.fn()
	};
}

async function render(overrides: Partial<ReturnType<typeof defaultProps>> = {}) {
	const target = document.createElement('div');
	document.body.append(target);
	const props = { ...defaultProps(), ...overrides };
	mounted.push(mount(CollectionMenu, { target, props }));
	await tick();
	return { target, props };
}

async function openMenuAndShare(target: HTMLElement) {
	target.querySelector<HTMLButtonElement>('.menu-trigger')?.click();
	await tick();
	target.querySelector<HTMLButtonElement>('.share-btn')?.click();
	await tick();
	await tick();
}

function shareWarningDialog(target: HTMLElement): Element | null {
	return target.querySelector(`[role="dialog"][aria-label="${SHARE_WARNING_LABEL}"]`);
}

describe('CollectionMenu share warning', () => {
	it('opens a warning dialog listing songs without a playable take after sharing an album, closing the menu behind it', async () => {
		const { target } = await render({
			onshare: vi
				.fn<() => Promise<ShareResult>>()
				.mockResolvedValue(
					shareResult({ songs_without_playable_take: [{ id: 's1', title: 'No Take Song' }] })
				)
		});

		await openMenuAndShare(target);

		const dialog = shareWarningDialog(target);
		expect(dialog).not.toBeNull();
		expect(dialog?.textContent).toContain('No Take Song');
		expect(target.querySelector('.menu-panel')).toBeNull();
	});

	it('closes only the warning dialog on Escape, leaving no stacked modal behind', async () => {
		const { target } = await render({
			onshare: vi
				.fn<() => Promise<ShareResult>>()
				.mockResolvedValue(
					shareResult({ songs_without_playable_take: [{ id: 's1', title: 'No Take Song' }] })
				)
		});

		await openMenuAndShare(target);
		expect(shareWarningDialog(target)).not.toBeNull();

		window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
		await tick();

		expect(shareWarningDialog(target)).toBeNull();
		expect(target.querySelector('.menu-panel')).toBeNull();
		expect(target.querySelectorAll('[role="dialog"]')).toHaveLength(0);
	});

	it('does not open a warning dialog when every song has a playable take', async () => {
		const { target } = await render();

		await openMenuAndShare(target);

		expect(shareWarningDialog(target)).toBeNull();
	});

	it('does not warn for playlist shares', async () => {
		const { target } = await render({
			kind: 'playlist',
			onshare: vi
				.fn<() => Promise<ShareResult>>()
				.mockResolvedValue(
					shareResult({ songs_without_playable_take: [{ id: 's1', title: 'No Take Song' }] })
				)
		});

		await openMenuAndShare(target);

		expect(shareWarningDialog(target)).toBeNull();
	});
});
