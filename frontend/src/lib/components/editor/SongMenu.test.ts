import { mount, tick, unmount } from 'svelte';
import { get } from 'svelte/store';
import { ApiError } from '#lib/api/fetch.ts';
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from 'vitest';
import {
	SONG_MENU_ADD_TO_PLAYLIST_LABEL,
	SONG_MENU_DELETE_LABEL,
	SONG_MENU_MOVE_LABEL,
	SONG_MENU_RENAME_LABEL,
	SONG_MENU_SAVE_LABEL,
	SONG_MOVE_ALBUM_GONE,
	SONG_MOVE_BACK_LABEL,
	SONG_MOVE_FAILED_REASON,
	SONG_MOVE_NO_MATCH,
	SONG_MOVE_NO_OTHER_ALBUM,
	SONG_MOVE_SHARED_TITLE,
	songMoveFailedLine,
	songMoveSharedMessage
} from '#lib/constants/song.ts';
import { LIBRARY_RETRY_LABEL } from '#lib/constants/library.ts';
import { DIALOG_CANCEL_LABEL } from '#lib/constants/dialog.ts';
import { menuRow, menuRowLabels } from '#lib/test-utils/collection-menu.ts';
import { describeBackClosesOverlay, plannedHistoryIndex } from '#lib/test-utils/library-history.ts';
import { makeAlbum, makeSong } from '#lib/test-utils/factories.ts';
import type { AlbumItem, SongItem } from '#lib/api/types.ts';
import { moveSong } from '#lib/api/songs.ts';
import { songList } from '#lib/stores/libraryData.ts';
import { selectedSongId } from '#lib/stores/player.ts';
import { closeSongMovePicker, songMoveConfirm, songMoveRun } from '#lib/stores/songMove.ts';
import { libraryWallOrder } from '#lib/stores/ui.ts';
import SongMenu from './SongMenu.svelte';

vi.mock('#lib/api/client.ts', () => ({
	fetchAlbums: vi.fn(),
	fetchSongs: vi.fn()
}));
vi.mock('#lib/api/songs.ts', () => ({ moveSong: vi.fn() }));

import { fetchAlbums } from '#lib/api/client.ts';

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

	it('915_C3: lists Save version · Rename · Add to playlist · Move · Delete song, each with an icon, Delete red and last', async () => {
		const { target } = await renderMenu();
		openSongMenu(target);
		await tick();
		const items = Array.from(target.querySelectorAll<HTMLButtonElement>('.menu-item'));
		expect(menuRowLabels(target)).toEqual([
			SONG_MENU_SAVE_LABEL,
			SONG_MENU_RENAME_LABEL,
			SONG_MENU_ADD_TO_PLAYLIST_LABEL,
			SONG_MENU_MOVE_LABEL,
			SONG_MENU_DELETE_LABEL
		]);
		expect(items.every((item) => item.querySelector('svg') !== null)).toBe(true);
		expect(items.map((item) => item.classList.contains('destructive'))).toEqual([
			false,
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

describe('SongMenu move picker', () => {
	async function openPickerOver(albums: AlbumItem[], settled: string) {
		libraryWallOrder.set('title');
		songList.set([makeSong({ id: 's1', album_id: 'home' })]);
		selectedSongId.set('s1');
		vi.mocked(fetchAlbums).mockResolvedValue({
			items: albums,
			total: albums.length,
			offset: 0,
			limit: 50,
			has_more: false
		});
		const { target } = await renderMenu();
		openSongMenu(target);
		await tick();
		menuRow(target, SONG_MENU_MOVE_LABEL).click();
		await vi.waitFor(() => expect(target.querySelector(settled)).not.toBeNull());
		return target;
	}

	function openPicker() {
		return openPickerOver([makeAlbum({ id: 'home', title: 'Homeoffice' })], '.pk-empty');
	}

	const homeAlbum = makeAlbum({ id: 'home', title: 'Homeoffice' });

	it('lists the other albums with their cover or initials and a shared mark, and filters them', async () => {
		const target = await openPickerOver(
			[
				homeAlbum,
				makeAlbum({
					id: 'b',
					title: 'Berlin',
					cover: { card: '/covers/b.webp' } as AlbumItem['cover']
				}),
				makeAlbum({ id: 'c', title: 'Cologne', is_shared: true })
			],
			'.pk-list'
		);

		expect(target.querySelectorAll('.pk-list .pk-row')).toHaveLength(2);
		expect(target.querySelector('.pk-list img')).not.toBeNull();
		expect(target.querySelector('.pk-list .pk-shared')).not.toBeNull();

		const filter = target.querySelector<HTMLInputElement>('.pk-filter');
		if (!filter) throw new Error('filter missing');
		filter.value = 'zzz';
		filter.dispatchEvent(new Event('input', { bubbles: true }));
		await vi.waitFor(() =>
			expect(target.querySelector('.pk-empty')?.textContent).toBe(SONG_MOVE_NO_MATCH)
		);
	});

	it('shows no current-album row when the song album is not among the own albums', async () => {
		const target = await openPickerOver([makeAlbum({ id: 'b', title: 'Berlin' })], '.pk-list');

		expect(target.querySelector('.pk-row.here')).toBeNull();
		expect(target.querySelectorAll('.pk-list .pk-row')).toHaveLength(1);
	});

	it('says when the albums did not load and loads them again on retry', async () => {
		libraryWallOrder.set('title');
		songList.set([makeSong({ id: 's1', album_id: 'home' })]);
		selectedSongId.set('s1');
		vi.mocked(fetchAlbums).mockRejectedValueOnce(new Error('offline'));
		const { target } = await renderMenu();
		openSongMenu(target);
		await tick();
		menuRow(target, SONG_MENU_MOVE_LABEL).click();
		await vi.waitFor(() => expect(target.querySelector('.pk-error')).not.toBeNull());

		vi.mocked(fetchAlbums).mockResolvedValue({
			items: [homeAlbum],
			total: 1,
			offset: 0,
			limit: 50,
			has_more: false
		});
		target.querySelector<HTMLButtonElement>('.pk-retry')?.click();
		await vi.waitFor(() => expect(target.querySelector('.pk-empty')).not.toBeNull());
	});

	it("turns the popover into the person's albums and says when there is no other one", async () => {
		const target = await openPicker();

		expect(target.querySelector('.menu-item')).toBeNull();
		expect(target.querySelector('.pk-row.here')?.textContent).toContain('Homeoffice');
		expect(target.querySelector('.pk-empty')?.textContent).toBe(SONG_MOVE_NO_OTHER_ALBUM);
	});

	it('goes back to the menu rows with the back button', async () => {
		const target = await openPicker();

		target.querySelector<HTMLButtonElement>(`[aria-label="${SONG_MOVE_BACK_LABEL}"]`)?.click();
		await tick();

		expect(menuRowLabels(target)).toContain(SONG_MENU_MOVE_LABEL);
	});

	it('opens on the menu rows again after the popover closed over the picker', async () => {
		const target = await openPicker();

		target.querySelector<HTMLButtonElement>('.menu-backdrop')?.click();
		await tick();
		openSongMenu(target);
		await tick();

		expect(menuRowLabels(target)).toContain(SONG_MENU_MOVE_LABEL);
	});
	describe('moving into a shared album', () => {
		async function chooseSharedAlbum() {
			const target = await openPickerOver(
				[homeAlbum, makeAlbum({ id: 'c', title: 'Cologne', is_shared: true })],
				'.pk-list'
			);
			target.querySelector<HTMLButtonElement>('.pk-list .pk-row')?.click();
			await vi.waitFor(() => expect(target.querySelector('.pk-list')).toBeNull());
			return target;
		}

		it('asks with the consequence line once the popover closed, and moves nothing on Cancel', async () => {
			const target = await chooseSharedAlbum();
			const dialog = document.body.querySelector('[role="dialog"], [role="alertdialog"]');
			expect(dialog?.textContent).toContain(SONG_MOVE_SHARED_TITLE);
			expect(dialog?.textContent).toContain(songMoveSharedMessage('Sommerlicht', 'Cologne'));
			expect(target.querySelector('.pk-list')).toBeNull();

			[...document.body.querySelectorAll('button')]
				.find((button) => button.textContent?.trim() === DIALOG_CANCEL_LABEL)
				?.click();
			await tick();

			expect(document.body.querySelector('[role="dialog"], [role="alertdialog"]')).toBeNull();
			expect(moveSong).not.toHaveBeenCalled();
		});
	});

	describe('while a move runs and after it failed', () => {
		const albums = [
			homeAlbum,
			makeAlbum({ id: 'b', title: 'Berlin' }),
			makeAlbum({ id: 'd', title: 'Dresden' })
		];

		beforeEach(() => {
			vi.mocked(moveSong).mockReset();
		});

		function rowTitled(target: HTMLElement, title: string): HTMLButtonElement {
			const row = [...target.querySelectorAll<HTMLButtonElement>('.pk-list .pk-row')].find((item) =>
				item.textContent?.includes(title)
			);
			if (!row) throw new Error(`no row for ${title}`);
			return row;
		}

		it('marks only the tapped row busy, disables the rest and keeps the popover open', async () => {
			const pending = Promise.withResolvers<SongItem>();
			vi.mocked(moveSong).mockReturnValue(pending.promise);
			// A move that never ends would leave the shared run busy for the next test.
			onTestFinished(async () => {
				pending.reject(new Error('test over'));
				await vi.waitFor(() => expect(get(songMoveRun).status).toBe('failed'));
				closeSongMovePicker();
			});
			const target = await openPickerOver(albums, '.pk-list');

			rowTitled(target, 'Berlin').click();
			await tick();

			expect(rowTitled(target, 'Berlin').getAttribute('aria-busy')).toBe('true');
			expect(rowTitled(target, 'Dresden').disabled).toBe(true);
			expect(target.querySelector<HTMLInputElement>('.pk-filter')?.disabled).toBe(true);
			expect(
				target.querySelector<HTMLButtonElement>(`[aria-label="${SONG_MOVE_BACK_LABEL}"]`)?.disabled
			).toBe(true);
			expect(target.querySelector('.menu-panel')).not.toBeNull();
		});

		it('keeps the picker open with a red row, one line and Retry that repeats the move', async () => {
			vi.mocked(moveSong).mockRejectedValue(new Error('boom'));
			const target = await openPickerOver(albums, '.pk-list');

			rowTitled(target, 'Berlin').click();
			await vi.waitFor(() => expect(target.querySelector('.pk-error')).not.toBeNull());

			expect(target.querySelector('.pk-error')?.getAttribute('role')).toBe('alert');
			expect(target.querySelector('.pk-error span')?.textContent).toBe(
				songMoveFailedLine(SONG_MOVE_FAILED_REASON)
			);
			expect(rowTitled(target, 'Berlin').classList.contains('failed')).toBe(true);
			expect(rowTitled(target, 'Dresden').disabled).toBe(false);

			target.querySelector<HTMLButtonElement>('.pk-retry')?.click();
			await tick();
			expect(moveSong).toHaveBeenCalledTimes(2);
			expect(moveSong).toHaveBeenLastCalledWith('s1', 'b');
		});

		it('shows no Retry when the album is gone', async () => {
			vi.mocked(moveSong).mockRejectedValue(
				new ApiError(404, 'Song or album not found', '/api/songs/s1/album')
			);
			const target = await openPickerOver(albums, '.pk-list');

			rowTitled(target, 'Berlin').click();
			await vi.waitFor(() => expect(target.querySelector('.pk-error')).not.toBeNull());

			expect(target.querySelector('.pk-error')?.textContent).toContain(
				songMoveFailedLine(SONG_MOVE_ALBUM_GONE)
			);
			expect(target.querySelector('.pk-error')?.textContent).not.toContain(LIBRARY_RETRY_LABEL);
		});

		it('shows no busy row and disables every row on another song while a move runs', async () => {
			const pending = Promise.withResolvers<SongItem>();
			vi.mocked(moveSong).mockReturnValue(pending.promise);
			onTestFinished(async () => {
				pending.reject(new Error('test over'));
				await vi.waitFor(() => expect(get(songMoveRun).status).toBe('failed'));
				closeSongMovePicker();
			});
			const target = await openPickerOver(albums, '.pk-list');
			rowTitled(target, 'Berlin').click();
			await tick();

			selectedSongId.set('s2');
			await tick();

			expect(target.querySelector('[aria-busy="true"]')).toBeNull();
			const rows = [...target.querySelectorAll<HTMLButtonElement>('.pk-list .pk-row')];
			expect(rows.length).toBeGreaterThan(0);
			expect(rows.every((row) => row.disabled)).toBe(true);
		});

		it('shows no red row and no Retry on another song after a move failed', async () => {
			vi.mocked(moveSong).mockRejectedValue(new Error('boom'));
			const target = await openPickerOver(albums, '.pk-list');
			rowTitled(target, 'Berlin').click();
			await vi.waitFor(() => expect(target.querySelector('.pk-error')).not.toBeNull());

			selectedSongId.set('s2');
			await tick();

			expect(target.querySelector('.pk-error')).toBeNull();
			expect(target.querySelector('.pk-retry')).toBeNull();
			expect(target.querySelector('.pk-row.failed')).toBeNull();
			const rows = [...target.querySelectorAll<HTMLButtonElement>('.pk-list .pk-row')];
			expect(rows.some((row) => row.disabled)).toBe(false);
		});

		it('reopens the picker for a failed run only while its song is the open song', async () => {
			const pending = Promise.withResolvers<SongItem>();
			vi.mocked(moveSong).mockReturnValue(pending.promise);
			const target = await openPickerOver(albums, '.pk-list');
			rowTitled(target, 'Berlin').click();
			await tick();
			window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
			await tick();
			selectedSongId.set('s2');

			pending.reject(new Error('boom'));
			await vi.waitFor(() => expect(get(songMoveRun).status).toBe('failed'));
			await tick();
			expect(target.querySelector('.menu-panel')).toBeNull();

			selectedSongId.set('s1');
			await vi.waitFor(() => expect(target.querySelector('.pk-error')).not.toBeNull());
		});

		it('reopens the picker with the red row when a move into a shared album is refused', async () => {
			vi.mocked(moveSong).mockRejectedValue(new Error('boom'));
			const target = await openPickerOver(
				[homeAlbum, makeAlbum({ id: 'c', title: 'Cologne', is_shared: true })],
				'.pk-list'
			);
			target.querySelector<HTMLButtonElement>('.pk-list .pk-row')?.click();
			await vi.waitFor(() => expect(get(songMoveConfirm)).not.toBeNull());
			[...document.body.querySelectorAll('button')]
				.find((button) => button.textContent?.trim() === SONG_MENU_MOVE_LABEL)
				?.click();

			await vi.waitFor(() => expect(target.querySelector('.pk-error')).not.toBeNull());

			expect(target.querySelector('.pk-error span')?.textContent).toBe(
				songMoveFailedLine(SONG_MOVE_FAILED_REASON)
			);
			expect(target.querySelector('.pk-list .pk-row.failed')).not.toBeNull();
		});
	});

	it('forgets an open ask when the menu unmounts', async () => {
		const target = await openPickerOver(
			[homeAlbum, makeAlbum({ id: 'c', title: 'Cologne', is_shared: true })],
			'.pk-list'
		);
		target.querySelector<HTMLButtonElement>('.pk-list .pk-row')?.click();
		await vi.waitFor(() => expect(get(songMoveConfirm)).not.toBeNull());

		await unmount(mounted.pop() as ReturnType<typeof mount>);

		expect(get(songMoveConfirm)).toBeNull();
	});
});
