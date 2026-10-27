import { makeGeneration as gen } from '$lib/test-utils/factories';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
	HITBOX_COMPACT_PX,
	HITBOX_FREQUENT_PX,
	TAKE_COVER_LABEL,
	TAKE_DELETE_LABEL,
	TAKE_PLAYLIST_LABEL,
	TAKE_REPAINT_LABEL,
	TAKE_SHARE_LABEL
} from '$lib/constants';
import { TAKE_USE_SEED_LABEL } from '$lib/constants/take-task';
import { menuRow, menuRowLabels } from '$lib/test-utils/collection-menu';
import { describeBackClosesOverlay, plannedHistoryIndex } from '$lib/test-utils/library-history';
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
		gen: gen({ version_number: 3, generation_number: 2, seed: null }),
		onrepaint: vi.fn(),
		oncover: vi.fn(),
		onuseseed: vi.fn(),
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

async function mountMenu(overrides: Partial<ReturnType<typeof defaultProps>> = {}) {
	const target = document.createElement('div');
	document.body.append(target);
	const props = { ...defaultProps(), ...overrides };
	mounted.push(mount(TakeMenu, { target, props }));
	await tick();
	return { target, props };
}

function moreButtonIn(target: ParentNode): HTMLButtonElement {
	const trigger = target.querySelector<HTMLButtonElement>('.menu-trigger');
	if (!trigger) throw new Error('Expected the More trigger');
	return trigger;
}

async function render(overrides: Partial<ReturnType<typeof defaultProps>> = {}) {
	const rendered = await mountMenu(overrides);
	moreButtonIn(rendered.target).click();
	await tick();
	return rendered;
}

describe('TakeMenu', () => {
	it.each([
		{ case: 'its version and number', version: 3, heading: 'Take · v3 · 2' },
		{ case: 'its number alone when it has no version', version: null, heading: 'Take · 2' }
	])('915_C3: names the take by $case on the first row', async ({ version, heading }) => {
		const { target } = await render({
			gen: gen({ version_number: version, generation_number: 2 })
		});
		expect(target.querySelector('.menu-heading')?.textContent).toBe(heading);
	});

	it('names the take share page in the shared tooltip', async () => {
		const { target } = await render({ gen: gen({ is_shared: true, share_slug: 'take' }) });

		expect(menuRow(target, TAKE_SHARE_LABEL).title).toBe('Shared: /share/gen/take');
	});

	it.each([
		{ seed: null, rows: [] as string[] },
		{ seed: 4127730, rows: [TAKE_USE_SEED_LABEL] }
	])(
		'915_C3: offers ordered actions with an icon each, Use seed third only for a take with seed $seed, Delete last in red',
		async ({ seed, rows: seedRows }) => {
			const { target } = await render({
				gen: gen({ is_kept: true, is_shared: true, is_archived: true, seed })
			});
			expect(menuRowLabels(target)).toEqual([
				TAKE_REPAINT_LABEL,
				TAKE_COVER_LABEL,
				...seedRows,
				TAKE_PLAYLIST_LABEL,
				TAKE_SHARE_LABEL,
				TAKE_DELETE_LABEL
			]);
			const rows = Array.from(target.querySelectorAll('.menu-item'));
			expect(rows.every((row) => row.querySelector('svg') !== null)).toBe(true);
			expect(rows.map((row) => row.classList.contains('destructive'))).toEqual([
				...rows.slice(0, -1).map(() => false),
				true
			]);
		}
	);

	it('shows the seed as the Use seed row hint', async () => {
		const { target } = await render({ gen: gen({ seed: 4127730 }) });
		expect(menuRow(target, TAKE_USE_SEED_LABEL).querySelector('.menu-item-hint')?.textContent).toBe(
			'4127730'
		);
	});

	it('915_C3: is a dialog of plain buttons named More, not a menu', async () => {
		const { target } = await render();
		const panel = target.querySelector('.menu-panel');
		expect(panel?.getAttribute('role')).toBe('dialog');
		expect(panel?.getAttribute('aria-label')).toBe('More');
		expect(target.querySelector('[role="menu"], [role="menuitem"]')).toBeNull();
	});

	it.each([
		['Repaint', 'onrepaint'],
		['Cover', 'oncover'],
		['Use seed', 'onuseseed'],
		['Add to playlist', 'onaddtoplaylist'],
		['Delete', 'ondelete']
	] as const)(
		'915_C3: runs %s and closes the menu, handing focus back to More',
		async (label, callback) => {
			const { target, props } = await render({ gen: gen({ seed: 4127730 }) });
			menuRow(target, label).click();
			await vi.waitFor(() => expect(document.activeElement).toBe(moreButtonIn(target)));
			expect(props[callback]).toHaveBeenCalledOnce();
			expect(target.querySelector('.menu-panel')).toBeNull();
		}
	);

	it.each([false, true])(
		'915_C3: shares or unshares from its Share row and stays open when shared is %s',
		async (shared) => {
			const writeText = vi.fn(async () => undefined);
			vi.stubGlobal('navigator', { clipboard: { writeText } });
			const { target, props } = await render({
				gen: gen({ is_shared: shared, share_slug: shared ? 'take' : null })
			});
			const share = menuRow(target, TAKE_SHARE_LABEL);
			expect(share.getAttribute('aria-pressed')).toBe(String(shared));
			expect(share.querySelector('.menu-item-hint')?.textContent?.trim()).toBe(
				shared ? 'on' : 'off'
			);

			share.click();
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
			expect(target.querySelector('.menu-panel')).not.toBeNull();
		}
	);

	it('915_C3: sizes the More trigger to the frequent hitbox on a coarse pointer, keeping its face', async () => {
		const { target } = await render();
		const btn = moreButtonIn(target);
		expect(btn.hasAttribute('data-hitbox-face')).toBe(true);
		document.documentElement.dataset.pointer = 'coarse';
		const coarse = getComputedStyle(btn);
		expect(px(coarse.minWidth)).toBe(HITBOX_FREQUENT_PX);
		expect(px(coarse.minHeight)).toBe(HITBOX_FREQUENT_PX);
		document.documentElement.dataset.pointer = 'fine';
		const fine = getComputedStyle(btn);
		expect(px(fine.minWidth)).toBeGreaterThanOrEqual(HITBOX_COMPACT_PX);
	});

	it('915_C3: focuses the first action and returns focus on Escape', async () => {
		const { target } = await render();
		expect(document.activeElement?.textContent?.trim()).toBe('Repaint');
		window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
		await vi.waitFor(() => expect(document.activeElement).toBe(moreButtonIn(target)));
		expect(target.querySelector('.menu-panel')).toBeNull();
	});
});

let repaintSawHistoryAt: number | undefined;

describeBackClosesOverlay({
	name: 'the take menu',
	render: async () =>
		(
			await mountMenu({
				onrepaint: vi.fn(() => {
					repaintSawHistoryAt = plannedHistoryIndex();
				})
			})
		).target,
	open: (target) => moreButtonIn(target).click(),
	isShown: (target) => target.querySelector('.menu-panel') !== null,
	closeWays: [
		{
			way: 'a tap outside',
			close: (target) => target.querySelector<HTMLButtonElement>('.menu-backdrop')?.click()
		},
		{
			way: 'Escape',
			close: () =>
				window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
		},
		{
			way: 'choosing Repaint',
			close: (target) => menuRow(target, TAKE_REPAINT_LABEL).click(),
			actionSawHistoryAt: () => repaintSawHistoryAt
		}
	]
});
