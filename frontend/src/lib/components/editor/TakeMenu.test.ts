import { makeGeneration as gen } from '$lib/test-utils/factories';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { HITBOX_COMPACT_PX, HITBOX_FREQUENT_PX } from '$lib/constants';
import { HITBOX_STYLE as hitboxCss } from '$lib/styles/hitbox';
import TakeMenu from './TakeMenu.svelte';

function px(value: string): number {
	const resolved = value.startsWith('var(')
		? getComputedStyle(document.documentElement)
				.getPropertyValue(value.slice('var('.length, -1).trim())
				.trim()
		: value;
	return Number.parseFloat(resolved);
}

const mounted: Array<ReturnType<typeof mount>> = [];

beforeEach(() => {
	const sheet = document.createElement('style');
	sheet.dataset.hitboxStyles = 'true';
	sheet.textContent = hitboxCss;
	document.head.append(sheet);
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
	document.head.querySelectorAll('[data-hitbox-styles]').forEach((el) => el.remove());
	delete document.documentElement.dataset.pointer;
});

function defaultProps() {
	return {
		gen: gen({ version_number: 3, generation_number: 2 }),
		onrepaint: vi.fn(),
		oncover: vi.fn(),
		onkeep: vi.fn(),
		onshare: vi.fn(async () => ({
			status: 'ok',
			share_url: 'https://example.com/share/gen/take',
			share_slug: 'take',
			songs_without_playable_take: []
		})),
		onunshare: vi.fn(async () => undefined),
		onaddtoplaylist: vi.fn(),
		ondelete: vi.fn()
	};
}

async function render(overrides: Partial<ReturnType<typeof defaultProps>> = {}) {
	const target = document.createElement('div');
	document.body.append(target);
	const props = { ...defaultProps(), ...overrides };
	mounted.push(mount(TakeMenu, { target, props }));
	await tick();
	target.querySelector<HTMLButtonElement>('.overflow-btn')?.click();
	await tick();
	return { target, props };
}

describe('TakeMenu', () => {
	it('names the take on the first row', async () => {
		const { target } = await render();
		expect(target.querySelector('.menu-heading')?.textContent).toBe('Take · v3 · 2');
	});

	it.each([false, true])('offers exactly six ordered actions when kept is %s', async (kept) => {
		const { target } = await render({
			gen: gen({ is_kept: kept, is_shared: true, is_archived: true })
		});
		const rows = target.querySelectorAll('.overflow-menu > button, .share-row');
		expect(Array.from(rows, (row) => row.textContent?.trim())).toEqual([
			'Repaint',
			'Cover',
			kept ? 'Unkeep' : 'Keep',
			'Add to playlist',
			'Share',
			'Delete'
		]);
		expect(target.querySelectorAll('.overflow-menu button')).toHaveLength(6);
	});

	it.each([
		['Repaint', 'onrepaint'],
		['Cover', 'oncover'],
		['Keep', 'onkeep'],
		['Add to playlist', 'onaddtoplaylist'],
		['Delete', 'ondelete']
	] as const)('runs %s and closes the menu', async (label, callback) => {
		const { target, props } = await render();
		const button = Array.from(target.querySelectorAll<HTMLButtonElement>('button')).find(
			(button) => button.textContent?.trim() === label
		);
		button?.click();
		await tick();
		expect(props[callback]).toHaveBeenCalledOnce();
		expect(target.querySelector('.overflow-menu')).toBeNull();
		expect(document.activeElement).toBe(target.querySelector('.overflow-btn'));
	});

	it.each([false, true])(
		'uses the shared ShareButton behavior when shared is %s',
		async (shared) => {
			const writeText = vi.fn(async () => undefined);
			vi.stubGlobal('navigator', { clipboard: { writeText } });
			const { target, props } = await render({
				gen: gen({ is_shared: shared, share_slug: shared ? 'take' : null })
			});
			target.querySelector<HTMLButtonElement>('.share-btn')?.click();
			await tick();
			if (shared) {
				expect(props.onunshare).toHaveBeenCalledOnce();
				expect(props.onshare).not.toHaveBeenCalled();
				expect(writeText).not.toHaveBeenCalled();
			} else {
				expect(props.onshare).toHaveBeenCalledOnce();
				expect(props.onunshare).not.toHaveBeenCalled();
				expect(writeText).toHaveBeenCalledWith('https://example.com/share/gen/take');
			}
		}
	);

	it('sizes the overflow trigger to the frequent hitbox on a coarse pointer', async () => {
		const { target } = await render();
		const btn = target.querySelector<HTMLButtonElement>('.overflow-btn');
		if (!btn) throw new Error('Expected the overflow trigger button');
		document.documentElement.dataset.pointer = 'coarse';
		const coarse = getComputedStyle(btn);
		expect(px(coarse.minWidth)).toBe(HITBOX_FREQUENT_PX);
		expect(px(coarse.minHeight)).toBe(HITBOX_FREQUENT_PX);
		document.documentElement.dataset.pointer = 'fine';
		const fine = getComputedStyle(btn);
		expect(px(fine.minWidth)).toBeGreaterThanOrEqual(HITBOX_COMPACT_PX);
	});

	it('focuses the first action and returns focus on Escape', async () => {
		const { target } = await render();
		expect(document.activeElement?.textContent?.trim()).toBe('Repaint');
		document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
		await tick();
		expect(target.querySelector('.overflow-menu')).toBeNull();
		expect(document.activeElement).toBe(target.querySelector('.overflow-btn'));
	});

	it('opens downward when there is enough space below the trigger', async () => {
		vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
			bottom: 400,
			top: 0,
			left: 0,
			right: 0,
			height: 0,
			width: 0,
			x: 0,
			y: 0,
			toJSON: () => ({})
		});
		vi.stubGlobal('innerHeight', 800);
		const { target } = await render();
		await tick();
		expect(target.querySelector('.overflow-menu')?.classList.contains('flip-up')).toBe(false);
		vi.unstubAllGlobals();
	});

	it('flips upward when there is not enough space below the trigger', async () => {
		vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
			bottom: 900,
			top: 500,
			left: 0,
			right: 0,
			height: 0,
			width: 0,
			x: 0,
			y: 0,
			toJSON: () => ({})
		});
		vi.stubGlobal('innerHeight', 800);
		const { target } = await render();
		await tick();
		expect(target.querySelector('.overflow-menu')?.classList.contains('flip-up')).toBe(true);
		vi.unstubAllGlobals();
	});
});
