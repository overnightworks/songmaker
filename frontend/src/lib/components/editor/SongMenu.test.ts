import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
	SONG_MENU_ADD_TO_PLAYLIST_LABEL,
	SONG_MENU_DELETE_LABEL,
	SONG_MENU_RENAME_LABEL,
	SONG_MENU_SAVE_LABEL
} from '#lib/constants.ts';
import { menuRow, menuRowLabels } from '#lib/test-utils/collection-menu.ts';
import { describeBackClosesOverlay, plannedHistoryIndex } from '#lib/test-utils/library-history.ts';
import SongMenu from './SongMenu.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
});

function defaultProps() {
	return {
		title: 'Sommerlicht',
		saveDisabled: true,
		onsave: vi.fn(),
		onrename: vi.fn(),
		onaddtoplaylist: vi.fn(),
		ondelete: vi.fn()
	};
}

async function renderMenu(overrides: Partial<ReturnType<typeof defaultProps>> = {}) {
	const target = document.createElement('div');
	document.body.append(target);
	const props = { ...defaultProps(), ...overrides };
	mounted.push(mount(SongMenu, { target, props }));
	await tick();
	return { target, props };
}

function openSongMenu(target: HTMLElement): void {
	target.querySelector<HTMLButtonElement>('.menu-trigger')?.click();
}

async function focusSettled(): Promise<void> {
	await Promise.resolve();
	await tick();
}

describe('SongMenu', () => {
	it('defect:#1495: names the song on the first row', async () => {
		const { target } = await renderMenu();
		openSongMenu(target);
		await tick();
		expect(target.querySelector('.menu-heading')?.textContent).toBe('Song · Sommerlicht');
		expect(target.querySelector('.share-btn')).toBeNull();
	});

	it('915_C3: lists Save version · Rename · Add to playlist · Delete song, each with an icon, Delete red and last', async () => {
		const { target } = await renderMenu();
		openSongMenu(target);
		await tick();
		const items = Array.from(target.querySelectorAll<HTMLButtonElement>('.menu-item'));
		expect(menuRowLabels(target)).toEqual([
			SONG_MENU_SAVE_LABEL,
			SONG_MENU_RENAME_LABEL,
			SONG_MENU_ADD_TO_PLAYLIST_LABEL,
			SONG_MENU_DELETE_LABEL
		]);
		expect(items.every((item) => item.querySelector('svg') !== null)).toBe(true);
		expect(items.map((item) => item.classList.contains('destructive'))).toEqual([
			false,
			false,
			false,
			true
		]);
	});

	it.each([true, false])(
		'defect:#1495: enables saving only when the draft is dirty (disabled: %s)',
		async (saveDisabled) => {
			const { target, props } = await renderMenu({ saveDisabled });
			openSongMenu(target);
			await tick();
			const save = menuRow(target, SONG_MENU_SAVE_LABEL);
			expect(save.disabled).toBe(saveDisabled);
			save.click();
			await tick();
			expect(props.onsave).toHaveBeenCalledTimes(saveDisabled ? 0 : 1);
			expect(target.querySelector('.menu-panel') !== null).toBe(saveDisabled);
		}
	);

	it.each([
		{ label: SONG_MENU_SAVE_LABEL, handler: 'onsave' as const },
		{ label: SONG_MENU_RENAME_LABEL, handler: 'onrename' as const },
		{ label: SONG_MENU_ADD_TO_PLAYLIST_LABEL, handler: 'onaddtoplaylist' as const },
		{ label: SONG_MENU_DELETE_LABEL, handler: 'ondelete' as const }
	])(
		'defect:#1495: runs only $handler and closes the menu on $label',
		async ({ label, handler }) => {
			const { target, props } = await renderMenu({ saveDisabled: false });
			openSongMenu(target);
			await tick();
			menuRow(target, label).click();
			await tick();
			for (const [name, action] of Object.entries(props)) {
				if (typeof action === 'function') {
					expect(action).toHaveBeenCalledTimes(name === handler ? 1 : 0);
				}
			}
			expect(target.querySelector('.menu-panel')).toBeNull();
		}
	);

	it('defect:#1495: closes on Escape without triggering an action and hands focus back to its trigger', async () => {
		const { target } = await renderMenu();
		openSongMenu(target);
		await tick();
		window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
		await focusSettled();
		expect(target.querySelector('.menu-panel')).toBeNull();
		expect(document.activeElement).toBe(target.querySelector('.menu-trigger'));
	});

	it('1495_S10: leaves focus in the title field once Rename starts editing it', async () => {
		const titleField = document.createElement('input');
		document.body.append(titleField);
		const { target } = await renderMenu({
			onrename: vi.fn(() => queueMicrotask(() => titleField.focus()))
		});
		openSongMenu(target);
		await tick();
		menuRow(target, SONG_MENU_RENAME_LABEL).click();
		await focusSettled();
		expect(document.activeElement).toBe(titleField);
	});

	it.each([SONG_MENU_ADD_TO_PLAYLIST_LABEL, SONG_MENU_DELETE_LABEL])(
		'defect:#1495: hands focus back to its trigger after %s',
		async (label) => {
			const { target } = await renderMenu();
			openSongMenu(target);
			await tick();
			menuRow(target, label).click();
			await focusSettled();
			expect(document.activeElement).toBe(target.querySelector('.menu-trigger'));
		}
	);
});

let renameSawHistoryAt: number | undefined;

describeBackClosesOverlay({
	name: 'the song menu',
	render: async () =>
		(
			await renderMenu({
				onrename: vi.fn(() => {
					renameSawHistoryAt = plannedHistoryIndex();
				})
			})
		).target,
	open: (target) => target.querySelector<HTMLButtonElement>('.menu-trigger')?.click(),
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
			way: 'choosing Rename',
			close: (target) => menuRow(target, SONG_MENU_RENAME_LABEL).click(),
			actionSawHistoryAt: () => renameSawHistoryAt
		}
	]
});
