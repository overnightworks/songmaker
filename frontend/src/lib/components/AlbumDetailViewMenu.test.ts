import {
	makeAlbum as album,
	makeGeneration as generation,
	makeSong as song
} from '#lib/test-utils/factories.ts';
import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import { lostNetwork, serverRefusal } from '#lib/test-utils/network.ts';
import { resetConnectivityForTests } from '#lib/stores/connectivity.ts';
import { ALBUM_COVER_ALT_TYPE } from '#lib/constants/album.ts';
import { words } from '#lib/words/en.ts';
import { getByRoleButton } from '#lib/test-utils/accessible-name.ts';
import { menuRowLabels } from '#lib/test-utils/collection-menu.ts';
import {
	createComponentMount,
	openCollectionMenu,
	requireElement
} from './shell/rail-test-fixtures';
import { coverSuggestions } from '#lib/test-utils/album-cover-editor.ts';
import { clearHitboxStyles, clearPointer } from '#lib/test-utils/hitbox.ts';
import { clearComponentStyles } from '#lib/test-utils/component-styles.ts';
import { albumList, resetLibraryDataForTests, songList } from '#lib/stores/libraryData.ts';
import {
	curationActive,
	nowPlayingSurface,
	queueContext,
	selectedAlbumId
} from '#lib/stores/player.ts';
import { openCollection } from '#lib/stores/collection.ts';

const uploadAlbumCover = vi.fn();
const updateAlbum = vi.fn();
const archiveAlbum = vi.fn();
const unarchiveAlbum = vi.fn();
const fetchAlbumCoverSuggestions = vi.fn();
const createSong = vi.fn();

vi.mock('#lib/api/client.ts', async (importOriginal) => {
	const actual = await importOriginal<typeof import('#lib/api/client.ts')>();
	return {
		...actual,
		uploadAlbumCover: (...args: unknown[]) => uploadAlbumCover(...args),
		deleteAlbumCover: vi.fn(),
		updateAlbum: (...args: unknown[]) => updateAlbum(...args),
		shareAlbum: vi.fn(),
		unshareAlbum: vi.fn(),
		deleteAlbum: vi.fn().mockResolvedValue(undefined),
		restoreAlbum: vi.fn(),
		archiveAlbum: (...args: unknown[]) => archiveAlbum(...args),
		unarchiveAlbum: (...args: unknown[]) => unarchiveAlbum(...args),
		createSong: (...args: unknown[]) => createSong(...args)
	};
});
vi.mock('#lib/api/songs.ts', () => ({
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false })
}));
vi.mock('#lib/api/albums.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/albums.ts')>()),
	fetchAlbumCoverSuggestions: (...args: unknown[]) => fetchAlbumCoverSuggestions(...args),
	discardAlbumCoverSuggestions: async () => undefined
}));
vi.mock('#lib/stores/toast.ts', () => ({
	addToast: vi.fn(),
	addUndoToast: vi.fn(),
	dismissToast: vi.fn()
}));
vi.mock('#lib/stores/playlists.ts', async (importOriginal) => {
	const actual = await importOriginal<typeof import('#lib/stores/playlists.ts')>();
	return {
		...actual,
		addAlbumToPlaylist: vi.fn()
	};
});
vi.mock('#lib/stores/navigation.ts', async (importOriginal) => {
	const actual = await importOriginal<typeof import('#lib/stores/navigation.ts')>();
	return { ...actual, selectSong: vi.fn() };
});
vi.mock('#lib/stores/player.ts', async (importOriginal) => {
	const actual = await importOriginal<typeof import('#lib/stores/player.ts')>();
	return {
		...actual,
		ensureGenerationsLoaded: vi.fn(),
		playAlbum: vi.fn(),
		playAlbumSong: vi.fn()
	};
});

import AlbumDetailView from './AlbumDetailView.svelte';
const { render: renderDetail, cleanup } = createComponentMount(AlbumDetailView);
import { selectSong } from '#lib/stores/navigation.ts';
import {
	ensureGenerationsLoaded,
	playAlbum,
	playAlbumSong,
	playStartNotice,
	setPendingStartForTests,
	setShuffle
} from '#lib/stores/player.ts';
import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import { addToast } from '#lib/stores/toast.ts';

beforeEach(() => {
	albumList.set([album({ id: 'a-local', title: 'Night Drive' })]);
	songList.set([
		song({ id: 's-local', album_id: 'a-local', album_title: 'Night Drive', generation_count: 1 })
	]);
	selectedAlbumId.set('a-local');
	uploadAlbumCover.mockReset();
	updateAlbum.mockReset();
	archiveAlbum.mockReset();
	unarchiveAlbum.mockReset();
	fetchAlbumCoverSuggestions.mockReset().mockResolvedValue(coverSuggestions());
	vi.mocked(addToast).mockReset();
	vi.mocked(selectSong).mockReset();
	createSong.mockReset();
	vi.mocked(ensureGenerationsLoaded).mockReset();
	vi.mocked(playAlbum).mockReset();
	vi.mocked(playAlbumSong).mockReset();
	setShuffle(false);
});

afterEach(async () => {
	await cleanup();
	clearHitboxStyles();
	clearComponentStyles();
	clearPointer();
	selectedAlbumId.set(null);
	albumList.set([]);
	songList.set([]);
	openCollection.set(null);
	curationActive.set(false);
	queueContext.set({ type: 'library' });
	nowPlayingSurface.set('closed');
	audioPlayer.current = null;
	audioPlayer.status = 'idle';
	playStartNotice.set('idle');
	setPendingStartForTests(null);
	vi.unstubAllGlobals();
	vi.useRealTimers();
	resetConnectivityForTests();
	resetLibraryDataForTests();
});

describe('AlbumDetailView menu', () => {
	it('915_C3: names the album and lists Edit details, Cover, Pick album takes, Add to playlist, Share, Archive, Delete in the menu', async () => {
		const target = await renderDetail();
		const menu = await openCollectionMenu(target);
		expect(menu.querySelector('.menu-heading')?.textContent).toBe(
			words['collectionMenu.albumHeading']({ title: 'Night Drive' })
		);
		expect(menuRowLabels(menu)).toEqual([
			words['collectionMenu.editDetails'],
			words['collectionMenu.cover'],
			words['collectionMenu.curate'],
			words['collectionMenu.addToPlaylist'],
			words['collectionMenu.albumShare'],
			words['collectionMenu.archive'],
			words['collectionMenu.albumDelete']
		]);
	});

	it('opens curation mode from the menu', async () => {
		songList.set([
			song({
				id: 's-local',
				album_id: 'a-local',
				album_title: 'Night Drive',
				generation_count: 1,
				generations: [generation({ song_id: 's-local' })]
			})
		]);
		const target = await renderDetail();
		const menu = await openCollectionMenu(target);
		const curateItem = Array.from(menu.querySelectorAll<HTMLButtonElement>('.menu-item')).find(
			(el) => el.textContent?.trim() === words['collectionMenu.curate']
		);
		curateItem?.click();
		await tick();

		await vi.waitFor(() => expect(get(curationActive)).toBe(true));
	});

	it('uploads a cover through the cover editor the menu opens', async () => {
		uploadAlbumCover.mockResolvedValue(
			album({
				id: 'a-local',
				title: 'Night Drive',
				cover: {
					card: '/api/albums/a-local/cover?variant=card&v=abc.jpg',
					detail: '/api/albums/a-local/cover?variant=detail&v=abc.jpg'
				}
			})
		);
		const target = await renderDetail();
		const input = requireElement<HTMLInputElement>(target, '.cover-file-input');
		await uploadFromCoverEditor(target);
		const file = new File([new Uint8Array([1, 2, 3])], 'cover.jpg', { type: 'image/jpeg' });
		Object.defineProperty(input, 'files', { configurable: true, value: [file] });
		input.dispatchEvent(new Event('change', { bubbles: true }));
		await vi.waitFor(() => expect(uploadAlbumCover).toHaveBeenCalledTimes(1));
		await vi.waitFor(() =>
			expect(target.querySelector('img')?.getAttribute('alt')).toBe(
				`${ALBUM_COVER_ALT_TYPE} Night Drive`
			)
		);
	});

	it.each([
		{ failure: lostNetwork(), toast: words['albumPage.coverUploadFailed'] },
		{ failure: serverRefusal('Cover must be an image'), toast: 'Cover must be an image' }
	])('toasts $toast when a cover upload fails', async ({ failure, toast }) => {
		uploadAlbumCover.mockRejectedValue(failure);
		const target = await renderDetail();
		const input = requireElement<HTMLInputElement>(target, '.cover-file-input');
		await uploadFromCoverEditor(target);
		const file = new File([new Uint8Array([1, 2, 3])], 'cover.jpg', { type: 'image/jpeg' });
		Object.defineProperty(input, 'files', { configurable: true, value: [file] });
		input.dispatchEvent(new Event('change', { bubbles: true }));

		await vi.waitFor(() => expect(addToast).toHaveBeenCalledWith(toast, 'error'));
	});

	it('clears the open collection on delete so the wall takes over instead of a blank panel', async () => {
		openCollection.set({ kind: 'album', id: 'a-local' });
		const target = await renderDetail();
		const menu = await openCollectionMenu(target);
		requireElement<HTMLButtonElement>(menu, '.menu-item.destructive').click();
		await tick();
		requireElement<HTMLButtonElement>(document.body, '.confirm-btn').click();
		await tick();
		await Promise.resolve();
		await tick();

		expect(get(openCollection)).toBeNull();
	});

	it('archives the album through the menu without a confirmation dialog', async () => {
		archiveAlbum.mockResolvedValue(
			album({ id: 'a-local', title: 'Night Drive', is_archived: true })
		);
		openCollection.set({ kind: 'album', id: 'a-local' });
		const target = await renderDetail();
		const menu = await openCollectionMenu(target);
		const archiveItem = Array.from(menu.querySelectorAll<HTMLButtonElement>('.menu-item')).find(
			(el) => el.textContent?.trim() === words['collectionMenu.archive']
		);
		archiveItem?.click();
		await tick();
		await Promise.resolve();
		await tick();

		expect(archiveAlbum).toHaveBeenCalledWith('a-local');
		expect(document.body.querySelector('.confirm-btn')).toBeNull();
		expect(get(albumList).some((a) => a.id === 'a-local')).toBe(false);
		expect(get(openCollection)).toBeNull();
	});
});

async function uploadFromCoverEditor(target: HTMLElement): Promise<void> {
	const menu = await openCollectionMenu(target);
	Array.from(menu.querySelectorAll<HTMLButtonElement>('.menu-item'))
		.find((item) => item.textContent?.trim().startsWith(words['collectionMenu.cover']))
		?.click();
	await vi.waitFor(() => expect(target.querySelector('.cover-editor')).not.toBeNull());
	getByRoleButton(requireElement(target, '.cover-editor'), words['albumCover.upload']).click();
}
