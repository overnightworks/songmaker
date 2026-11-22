import { mount, tick, unmount } from 'svelte';
import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from 'vitest';
import { words } from '#lib/words/en.ts';
import { menuRow, menuRowLabels } from '#lib/test-utils/collection-menu.ts';
import { describeBackClosesOverlay, plannedHistoryIndex } from '#lib/test-utils/library-history.ts';
import { makeAlbum, makePlaylist, makeSong } from '#lib/test-utils/factories.ts';
import type { AlbumItem, ShareResult, SongItem } from '#lib/api/types.ts';
import { moveSong } from '#lib/api/songs.ts';
import { songList } from '#lib/stores/libraryData.ts';
import { selectedSongId } from '#lib/stores/player.ts';
import { closeSongMovePicker, songMoveConfirm, songMoveRun } from '#lib/stores/songMove.ts';
import { playlistList, playlistLoad, resetPlaylistsForTests } from '#lib/stores/playlists.ts';
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
		onaddto: vi.fn(),
		ondelete: vi.fn(),
		isShared: false,
		shareSlug: null as string | null,
		onshare: vi.fn<() => Promise<ShareResult>>().mockResolvedValue({
			status: 'shared',
			share_url: 'https://example.test/share/abc',
			share_slug: 'abc',
			songs_without_playable_take: []
		}),
		onunshare: vi.fn<() => Promise<void>>().mockResolvedValue(undefined)
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
	});

	it('915_C3: lists Save version · Rename · Move · Add to… · Share · Delete, each with an icon, Delete red and last', async () => {
		const { target } = await renderMenu();
		openSongMenu(target);
		await tick();
		const items = Array.from(target.querySelectorAll<HTMLButtonElement>('.menu-item'));
		expect(menuRowLabels(target)).toEqual([
			words['songMenu.save'],
			words['songMenu.rename'],
			words['songMenu.move'],
			words['songMenu.addTo'],
			words['songMenu.share'],
			words['songMenu.delete']
		]);
		expect(items.every((item) => item.querySelector('svg') !== null)).toBe(true);
	});

	it.each([
		{ isShared: false, hint: words['collectionMenu.shareOff'], handler: 'onshare' as const },
		{ isShared: true, hint: words['collectionMenu.shareOn'], handler: 'onunshare' as const }
	])(
		'shows the Share row $hint and runs $handler on a tap, keeping the menu open',
		async ({ isShared, hint, handler }) => {
			const { target, props } = await renderMenu({ isShared, shareSlug: isShared ? 'abc' : null });
			openSongMenu(target);
			await tick();
			const share = menuRow(target, words['songMenu.share']);
			expect(share.getAttribute('aria-pressed')).toBe(String(isShared));
			expect(share.querySelector('.menu-item-hint')?.textContent).toContain(hint);

			share.click();
			await tick();
			expect(props[handler]).toHaveBeenCalled();
			expect(target.querySelector('.menu-panel')).not.toBeNull();
		}
	);

	it.each([true, false])(
		'defect:#1495: enables saving only when the draft is dirty (disabled: %s)',
		async (saveDisabled) => {
			const { target, props } = await renderMenu({ saveDisabled });
			openSongMenu(target);
			await tick();
			const save = menuRow(target, words['songMenu.save']);
			expect(save.disabled).toBe(saveDisabled);
			save.click();
			await tick();
			if (saveDisabled) expect(props.onsave).not.toHaveBeenCalled();
			else expect(props.onsave).toHaveBeenCalled();
			expect(target.querySelector('.menu-panel') !== null).toBe(saveDisabled);
		}
	);

	it.each([
		{ label: words['songMenu.save'], handler: 'onsave' as const },
		{ label: words['songMenu.rename'], handler: 'onrename' as const },
		{ label: words['songMenu.delete'], handler: 'ondelete' as const }
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
					if (name === handler) expect(action).toHaveBeenCalled();
					else expect(action).not.toHaveBeenCalled();
				}
			}
			expect(target.querySelector('.menu-panel')).toBeNull();
		}
	);

	describe('Add to…', () => {
		beforeEach(() => {
			playlistList.set([makePlaylist({ id: 'p-night', title: 'Night Drive' })]);
			playlistLoad.set({ status: 'ready', error: null });
		});

		afterEach(resetPlaylistsForTests);

		it('turns the menu into the playlist picker, and Back returns to the rows', async () => {
			const { target } = await renderMenu();
			openSongMenu(target);
			await tick();
			menuRow(target, words['songMenu.addTo']).click();
			await tick();
			expect(target.querySelector('.menu-panel')?.textContent).toContain('Night Drive');
			expect(target.querySelector('.menu-heading')).toBeNull();

			target.querySelector<HTMLButtonElement>('.menu-picker-back')?.click();
			await tick();
			expect(menuRowLabels(target)).toContain(words['songMenu.addTo']);
		});

		it('adds to the chosen playlist, closes the menu and opens on its rows again', async () => {
			const { target, props } = await renderMenu();
			openSongMenu(target);
			await tick();
			menuRow(target, words['songMenu.addTo']).click();
			await tick();
			target.querySelector<HTMLButtonElement>('.menu-picker-row')?.click();
			await tick();
			expect(props.onaddto).toHaveBeenCalledWith('p-night');
			expect(target.querySelector('.menu-panel')).toBeNull();

			openSongMenu(target);
			await tick();
			expect(menuRowLabels(target)).toContain(words['songMenu.save']);
		});
	});

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
		menuRow(target, words['songMenu.rename']).click();
		await focusSettled();
		expect(document.activeElement).toBe(titleField);
	});

	it('defect:#1495: hands focus back to its trigger after Delete', async () => {
		const { target } = await renderMenu();
		openSongMenu(target);
		await tick();
		menuRow(target, words['songMenu.delete']).click();
		await focusSettled();
		expect(document.activeElement).toBe(target.querySelector('.menu-trigger'));
	});
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
			close: (target) => menuRow(target, words['songMenu.rename']).click(),
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
		menuRow(target, words['songMenu.move']).click();
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
			expect(target.querySelector('.pk-empty')?.textContent).toBe(words['songMove.noMatch'])
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
		menuRow(target, words['songMenu.move']).click();
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
		expect(target.querySelector('.pk-empty')?.textContent).toBe(words['songMove.noOtherAlbum']);
	});

	it('goes back to the menu rows with the back button', async () => {
		const target = await openPicker();

		target.querySelector<HTMLButtonElement>(`[aria-label="${words['songMove.back']}"]`)?.click();
		await tick();

		expect(menuRowLabels(target)).toContain(words['songMenu.move']);
	});

	it('opens on the menu rows again after the popover closed over the picker', async () => {
		const target = await openPicker();

		target.querySelector<HTMLButtonElement>('.menu-backdrop')?.click();
		await tick();
		openSongMenu(target);
		await tick();

		expect(menuRowLabels(target)).toContain(words['songMenu.move']);
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

		function holdMoveRunning(): void {
			const pending = Promise.withResolvers<SongItem>();
			vi.mocked(moveSong).mockReturnValue(pending.promise);
			onTestFinished(async () => {
				pending.reject(new Error('test over'));
				await vi.waitFor(() => expect(get(songMoveRun).status).toBe('failed'));
				closeSongMovePicker();
			});
		}

		async function openSharedAlbumQuestion(): Promise<HTMLElement> {
			const target = await openPickerOver(
				[homeAlbum, makeAlbum({ id: 'c', title: 'Cologne', is_shared: true })],
				'.pk-list'
			);
			target.querySelector<HTMLButtonElement>('.pk-list .pk-row')?.click();
			await vi.waitFor(() => expect(get(songMoveConfirm)).not.toBeNull());
			return target;
		}

		function rowTitled(target: HTMLElement, title: string): HTMLButtonElement {
			const row = [...target.querySelectorAll<HTMLButtonElement>('.pk-list .pk-row')].find((item) =>
				item.textContent?.includes(title)
			);
			if (!row) throw new Error(`no row for ${title}`);
			return row;
		}

		it('wires Retry to the failed move: the album row is busy again', async () => {
			vi.mocked(moveSong).mockRejectedValueOnce(new Error('boom'));
			holdMoveRunning();
			const target = await openPickerOver(albums, '.pk-list');
			rowTitled(target, 'Berlin').click();
			await vi.waitFor(() => expect(target.querySelector('.pk-error')).not.toBeNull());

			target.querySelector<HTMLButtonElement>('.pk-retry')?.click();
			await tick();

			expect(rowTitled(target, 'Berlin').getAttribute('aria-busy')).toBe('true');
		});

		it('wires Cancel of the shared-album question to leaving the song where it is', async () => {
			await openSharedAlbumQuestion();

			[...document.body.querySelectorAll('button')]
				.find((button) => button.textContent?.trim() === words['dialog.cancel'])
				?.click();
			await tick();

			expect(get(songMoveConfirm)).toBeNull();
			expect(get(songList)[0].album_id).toBe('home');
		});

		it('shows no busy row and disables every row on another song while a move runs', async () => {
			holdMoveRunning();
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
			const target = await openSharedAlbumQuestion();
			[...document.body.querySelectorAll('button')]
				.find((button) => button.textContent?.trim() === words['songMenu.move'])
				?.click();

			await vi.waitFor(() => expect(target.querySelector('.pk-error')).not.toBeNull());

			expect(target.querySelector('.pk-error span')?.textContent).toBe(
				words['songMove.notMoved']({ reason: words['songMove.failedReason'] })
			);
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
