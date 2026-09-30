import {
	makeAlbum as album,
	makeGeneration as generation,
	makeSong as song
} from '$lib/test-utils/factories';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { CoverSuggestionsResponse } from '$lib/api/types';
import { ApiError } from '$lib/api/fetch';
import { lostNetwork, serverRefusal } from '$lib/test-utils/network';
import { reportResourceStreamReachable, resetConnectivityForTests } from '$lib/stores/connectivity';
import {
	ALBUM_COVER_ALT_TYPE,
	ALBUM_YEAR_MIN,
	HITBOX_FREQUENT_PX,
	collectionPauseLabel,
	collectionPlayLabel,
	PLAYING_MARK_LABEL,
	collectionShuffleLabel
} from '$lib/constants';
import { getByRoleButton } from '$lib/test-utils/accessible-name';
import { findElementByRoleAndName } from './shell/rail-test-fixtures';
import {
	clearHitboxStyles,
	clearPointer,
	injectHitboxStyles,
	minHeightPx,
	px,
	setPointer
} from '$lib/test-utils/hitbox';
import {
	clearComponentStyles,
	elementScopeClass,
	injectComponentStyles
} from '$lib/test-utils/component-styles';
import {
	albumList,
	loadSongsForAlbum,
	resetLibraryDataForTests,
	songList
} from '$lib/stores/libraryData';
import { fetchSongs } from '$lib/api/songs';
import {
	curationActive,
	nowPlayingSurface,
	queueContext,
	selectedAlbumId
} from '$lib/stores/player';
import { openCollection } from '$lib/stores/collection';

const uploadAlbumCover = vi.fn();
const updateAlbum = vi.fn();
const archiveAlbum = vi.fn();
const unarchiveAlbum = vi.fn();
const fetchAlbumCoverSuggestions = vi.fn();

vi.mock('$lib/api/client', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/api/client')>();
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
		unarchiveAlbum: (...args: unknown[]) => unarchiveAlbum(...args)
	};
});
vi.mock('$lib/api/songs', () => ({
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false })
}));
vi.mock('$lib/api/albums', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/albums')>()),
	fetchAlbumCoverSuggestions: (...args: unknown[]) => fetchAlbumCoverSuggestions(...args)
}));
vi.mock('$lib/stores/toast', () => ({
	addToast: vi.fn(),
	addUndoToast: vi.fn()
}));
vi.mock('$lib/stores/shares', () => ({
	refreshSharesAfterMutation: vi.fn()
}));
vi.mock('$lib/stores/playlists', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/stores/playlists')>();
	return {
		...actual,
		addAlbumToPlaylist: vi.fn()
	};
});
vi.mock('$lib/stores/navigation', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/stores/navigation')>();
	return {
		...actual,
		selectSong: vi.fn()
	};
});
vi.mock('$lib/stores/player', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/stores/player')>();
	return {
		...actual,
		playAlbum: vi.fn()
	};
});

import AlbumDetailView from './AlbumDetailView.svelte';
import albumDetailViewSource from './AlbumDetailView.svelte?raw';
import { selectSong } from '$lib/stores/navigation';
import { playAlbum, setShuffle, shuffleEnabled } from '$lib/stores/player';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import { addToast } from '$lib/stores/toast';

const mounted: Array<ReturnType<typeof mount>> = [];

const NO_COVER_SUGGESTIONS: CoverSuggestionsResponse = {
	job: null,
	suggestions: [],
	used_today: 0,
	daily_limit: 10
};

async function renderDetail(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(AlbumDetailView, { target }));
	await tick();
	return target;
}

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
	fetchAlbumCoverSuggestions.mockReset().mockResolvedValue(NO_COVER_SUGGESTIONS);
	vi.mocked(addToast).mockReset();
	vi.mocked(selectSong).mockReset();
	vi.mocked(playAlbum).mockReset();
	setShuffle(false);
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
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
	vi.unstubAllGlobals();
	vi.useRealTimers();
	resetConnectivityForTests();
	resetLibraryDataForTests();
});

function requireElement<T extends Element>(root: ParentNode, selector: string): T {
	const element = root.querySelector<T>(selector);
	if (!element) throw new Error(`Expected ${selector} to be rendered`);
	return element;
}

async function openCollectionMenu(target: HTMLElement): Promise<HTMLElement> {
	requireElement<HTMLButtonElement>(target, '.collection-menu [aria-haspopup="dialog"]').click();
	await tick();
	return requireElement<HTMLElement>(document.body, '.menu-panel');
}

describe('AlbumDetailView songs that could not load', () => {
	const ALBUM_SONGS_FAILURE = 'Failed to load songs';

	function songsPage(items: ReturnType<typeof song>[]) {
		return { items, total: items.length, offset: 0, limit: 200, has_more: false };
	}

	function retryButton(target: HTMLElement): HTMLButtonElement | undefined {
		return Array.from(target.querySelectorAll('button')).find(
			(button) => button.textContent?.trim() === 'Retry'
		);
	}

	beforeEach(() => {
		songList.set([]);
	});

	it('offline names no failure and offers no Retry, then lists the songs once back online', async () => {
		reportResourceStreamReachable(false);
		vi.mocked(fetchSongs)
			.mockRejectedValueOnce(lostNetwork())
			.mockResolvedValueOnce(
				songsPage([song({ id: 's-back', album_id: 'a-local', title: 'Back Online' })])
			);
		await loadSongsForAlbum('a-local');
		const target = await renderDetail();

		expect(target.textContent).not.toContain(ALBUM_SONGS_FAILURE);
		expect(target.querySelector('[role="alert"]')).toBeNull();
		expect(retryButton(target)).toBeUndefined();

		reportResourceStreamReachable(true);

		await vi.waitFor(() => expect(target.textContent).toContain('Back Online'));
		expect(fetchSongs).toHaveBeenLastCalledWith('a-local', 0, 200);
	});

	it('names a refusal once with a styled Retry that loads the songs again', async () => {
		vi.mocked(fetchSongs)
			.mockRejectedValueOnce(new ApiError(500, '', '/api/songs'))
			.mockResolvedValueOnce(
				songsPage([song({ id: 's-again', album_id: 'a-local', title: 'Loaded Again' })])
			);
		await loadSongsForAlbum('a-local');
		const target = await renderDetail();

		const alerts = Array.from(target.querySelectorAll('[role="alert"]'));
		expect(alerts.map((alert) => alert.textContent?.trim())).toEqual([ALBUM_SONGS_FAILURE]);
		const retry = retryButton(target);
		expect(retry && elementScopeClass(retry)).toBeDefined();

		retry?.click();

		await vi.waitFor(() => expect(target.textContent).toContain('Loaded Again'));
		expect(target.textContent).not.toContain(ALBUM_SONGS_FAILURE);
	});
});

describe('AlbumDetailView header', () => {
	it('renders the albumId prop instead of the selected album', async () => {
		albumList.set([
			album({ id: 'a-local', title: 'Night Drive' }),
			album({ id: 'a-other', title: 'Other Night' })
		]);
		selectedAlbumId.set('a-other');
		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(mount(AlbumDetailView, { target, props: { albumId: 'a-local' } }));
		await tick();
		expect(target.textContent).toContain('Night Drive');
		expect(target.textContent).not.toContain('Other Night');
	});

	it('shows the cover, title, the play circle and shuffle beside the menu', async () => {
		const target = await renderDetail();
		const header = requireElement(target, '.collection-header');
		expect(header.querySelector('.header-cover')).not.toBeNull();
		expect(header.querySelector('.header-title')?.textContent).toContain('Night Drive');
		expect(getByRoleButton(header, collectionPlayLabel('album'))).not.toBeNull();
		expect(getByRoleButton(header, collectionShuffleLabel('album'))).not.toBeNull();
		expect(header.querySelector('.collection-menu')).not.toBeNull();
	});

	it('starts this album in order from its play circle', async () => {
		setShuffle(true);
		const target = await renderDetail();

		getByRoleButton(
			requireElement(target, '.collection-header'),
			collectionPlayLabel('album')
		).click();

		expect(playAlbum).toHaveBeenCalledWith('a-local', 'top');
		expect(get(shuffleEnabled)).toBe(false);
	});

	it('starts this album shuffled from a drawn song from its shuffle square', async () => {
		const target = await renderDetail();

		getByRoleButton(
			requireElement(target, '.collection-header'),
			collectionShuffleLabel('album')
		).click();

		expect(playAlbum).toHaveBeenCalledWith('a-local', 'random');
		expect(get(shuffleEnabled)).toBe(true);
	});

	it('offers to pause this album while it plays', async () => {
		queueContext.set({ type: 'album', albumId: 'a-local' });
		audioPlayer.current = { songId: 's-local' } as unknown as typeof audioPlayer.current;
		audioPlayer.status = 'playing';

		const target = await renderDetail();

		expect(
			getByRoleButton(requireElement(target, '.collection-header'), collectionPauseLabel('album'))
		).not.toBeNull();
	});

	it.each([
		['without songs', []],
		[
			'whose songs have no takes',
			[
				song({
					id: 's-local',
					album_id: 'a-local',
					album_title: 'Night Drive',
					generation_count: 0
				})
			]
		]
	])(
		'dims play and shuffle on an album %s, and a tap keeps the running queue',
		async (_, songs) => {
			setShuffle(true);
			songList.set(songs);
			const running = { type: 'library' as const, index: 3 };
			queueContext.set(running);
			const target = await renderDetail();
			const header = requireElement(target, '.collection-header');
			const buttons = [collectionPlayLabel('album'), collectionShuffleLabel('album')].map((label) =>
				getByRoleButton(header, label)
			);

			for (const button of buttons) button.click();
			await tick();

			expect(buttons.map((button) => button.disabled)).toEqual([true, true]);
			expect(playAlbum).not.toHaveBeenCalled();
			expect(get(queueContext)).toBe(running);
			expect(get(shuffleEnabled)).toBe(true);
		}
	);

	it('keeps pause on the circle of a playing album whose songs have no takes, with shuffle dimmed', async () => {
		songList.set([
			song({ id: 's-local', album_id: 'a-local', album_title: 'Night Drive', generation_count: 0 })
		]);
		queueContext.set({ type: 'album', albumId: 'a-local' });
		audioPlayer.current = { songId: 's-local' } as unknown as typeof audioPlayer.current;
		audioPlayer.status = 'playing';
		const target = await renderDetail();
		const header = requireElement(target, '.collection-header');

		expect(getByRoleButton(header, collectionPauseLabel('album')).disabled).toBe(false);
		expect(getByRoleButton(header, collectionShuffleLabel('album')).disabled).toBe(true);
	});

	it.each([collectionPlayLabel('album'), collectionShuffleLabel('album')])(
		'sizes "%s" to the frequent hitbox on a coarse pointer',
		async (label) => {
			// #163/6: the album header's play is the shortest path to hearing the
			// album, and on a phone it has to be reachable with a thumb.
			injectHitboxStyles();
			const target = await renderDetail();
			const button = getByRoleButton(requireElement(target, '.collection-header'), label);
			setPointer('coarse');

			expect(minHeightPx(button, label)).toBe(HITBOX_FREQUENT_PX);
		}
	);

	it('names the object and lists Share, Cover, Rename, Add to playlist, Archive, Delete in the menu', async () => {
		const target = await renderDetail();
		const menu = await openCollectionMenu(target);
		expect(menu.querySelector('.menu-heading')?.textContent).toBe('Album · Night Drive');
		expect(menu.querySelector('.menu-row-label')?.textContent).toBe('Share album');
		const items = Array.from(menu.querySelectorAll('.menu-item')).map((el) =>
			el.textContent?.trim()
		);
		expect(items).toEqual([
			'Upload…',
			'Rename',
			'Add to playlist',
			'Curate album',
			'Archive album',
			'Delete album'
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
			(el) => el.textContent?.trim() === 'Curate album'
		);
		curateItem?.click();
		await tick();

		await vi.waitFor(() => expect(get(curationActive)).toBe(true));
	});

	it('uploads a cover from the menu action', async () => {
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
		const menu = await openCollectionMenu(target);
		const input = target.querySelector('.cover-file-input');
		expect(input).toBeInstanceOf(HTMLInputElement);
		if (!(input instanceof HTMLInputElement)) return;
		requireElement<HTMLButtonElement>(menu, '.menu-item').click();
		const file = new File([new Uint8Array([1, 2, 3])], 'cover.jpg', { type: 'image/jpeg' });
		Object.defineProperty(input, 'files', { configurable: true, value: [file] });
		input.dispatchEvent(new Event('change', { bubbles: true }));
		await vi.waitFor(() => expect(uploadAlbumCover).toHaveBeenCalledTimes(1));
		await tick();
		expect(target.querySelector('img')?.getAttribute('alt')).toBe(
			`${ALBUM_COVER_ALT_TYPE} Night Drive`
		);
	});

	it.each([
		{ failure: lostNetwork(), toast: 'Cover upload failed' },
		{ failure: serverRefusal('Cover must be an image'), toast: 'Cover must be an image' }
	])('toasts $toast when a cover upload fails', async ({ failure, toast }) => {
		uploadAlbumCover.mockRejectedValue(failure);
		const target = await renderDetail();
		const menu = await openCollectionMenu(target);
		const input = requireElement<HTMLInputElement>(target, '.cover-file-input');
		requireElement<HTMLButtonElement>(menu, '.menu-item').click();
		const file = new File([new Uint8Array([1, 2, 3])], 'cover.jpg', { type: 'image/jpeg' });
		Object.defineProperty(input, 'files', { configurable: true, value: [file] });
		input.dispatchEvent(new Event('change', { bubbles: true }));

		await vi.waitFor(() => expect(addToast).toHaveBeenCalledWith(toast, 'error'));
	});

	it('renames the album through the menu, reusing the EditableTitle interaction', async () => {
		const target = await renderDetail();
		const menu = await openCollectionMenu(target);
		const renameItem = Array.from(menu.querySelectorAll<HTMLButtonElement>('.menu-item')).find(
			(el) => el.textContent?.trim() === 'Rename'
		);
		renameItem?.click();
		await tick();
		expect(document.body.querySelector('.menu-panel')).toBeNull();
		expect(target.querySelector('.editable-title-input')).not.toBeNull();
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
			(el) => el.textContent?.trim() === 'Archive album'
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

describe('AlbumDetailView subtitle and year', () => {
	it('shows the album subtitle and year under the title', async () => {
		albumList.set([
			album({ id: 'a-local', title: 'Night Drive', subtitle: 'Live at the Roxy', year: '1994' })
		]);
		const target = await renderDetail();
		expect(target.querySelector('.album-meta')?.textContent).toContain('Live at the Roxy');
		expect(target.querySelector('.album-meta')?.textContent).toContain('1994');
	});

	it('saves an edited subtitle through updateAlbum and updates the store', async () => {
		albumList.set([
			album({ id: 'a-local', title: 'Night Drive', subtitle: 'Old Subtitle', year: '1999' })
		]);
		updateAlbum.mockResolvedValue(
			album({ id: 'a-local', title: 'Night Drive', subtitle: 'New Subtitle', year: '1999' })
		);
		const target = await renderDetail();
		requireElement<HTMLButtonElement>(target, '.album-meta .editable-title-display').click();
		await tick();
		const input = requireElement<HTMLInputElement>(target, '.album-meta .editable-title-input');
		input.value = 'New Subtitle';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
		await vi.waitFor(() =>
			expect(updateAlbum).toHaveBeenCalledWith('a-local', { subtitle: 'New Subtitle' })
		);
		await tick();
		expect(get(albumList)[0].subtitle).toBe('New Subtitle');
	});

	it('saves an edited year as a number through updateAlbum', async () => {
		albumList.set([album({ id: 'a-local', title: 'Night Drive', year: '1999' })]);
		updateAlbum.mockResolvedValue(album({ id: 'a-local', title: 'Night Drive', year: '2005' }));
		const target = await renderDetail();
		const displays = target.querySelectorAll<HTMLButtonElement>(
			'.album-meta .editable-title-display'
		);
		displays[displays.length - 1].click();
		await tick();
		const inputs = target.querySelectorAll<HTMLInputElement>('.album-meta .editable-title-input');
		const input = inputs[inputs.length - 1];
		input.value = '2005';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
		await vi.waitFor(() => expect(updateAlbum).toHaveBeenCalledWith('a-local', { year: 2005 }));
	});

	it('clears the year through updateAlbum when emptied', async () => {
		albumList.set([album({ id: 'a-local', title: 'Night Drive', year: '1999' })]);
		updateAlbum.mockResolvedValue(album({ id: 'a-local', title: 'Night Drive' }));
		const target = await renderDetail();
		const displays = target.querySelectorAll<HTMLButtonElement>(
			'.album-meta .editable-title-display'
		);
		displays[displays.length - 1].click();
		await tick();
		const inputs = target.querySelectorAll<HTMLInputElement>('.album-meta .editable-title-input');
		const input = inputs[inputs.length - 1];
		input.value = '';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
		await vi.waitFor(() => expect(updateAlbum).toHaveBeenCalledWith('a-local', { year: null }));
	});

	it('rejects a non-numeric year without calling updateAlbum', async () => {
		albumList.set([album({ id: 'a-local', title: 'Night Drive', year: '1999' })]);
		const target = await renderDetail();
		const displays = target.querySelectorAll<HTMLButtonElement>(
			'.album-meta .editable-title-display'
		);
		displays[displays.length - 1].click();
		await tick();
		const inputs = target.querySelectorAll<HTMLInputElement>('.album-meta .editable-title-input');
		const input = inputs[inputs.length - 1];
		input.value = 'abcd';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
		await tick();
		expect(updateAlbum).not.toHaveBeenCalled();
	});

	it('rejects a year outside the plausible range without calling updateAlbum', async () => {
		albumList.set([album({ id: 'a-local', title: 'Night Drive', year: '1999' })]);
		const target = await renderDetail();
		const displays = target.querySelectorAll<HTMLButtonElement>(
			'.album-meta .editable-title-display'
		);
		displays[displays.length - 1].click();
		await tick();
		const inputs = target.querySelectorAll<HTMLInputElement>('.album-meta .editable-title-input');
		const input = inputs[inputs.length - 1];
		input.value = String(ALBUM_YEAR_MIN - 1);
		input.dispatchEvent(new Event('input', { bubbles: true }));
		input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
		await tick();
		expect(updateAlbum).not.toHaveBeenCalled();
	});
});

describe('AlbumDetailView song row', () => {
	function renderTwoSongs(): Promise<HTMLElement> {
		songList.set([
			song({
				id: 's-tide',
				album_id: 'a-local',
				album_title: 'Night Drive',
				title: 'Tide',
				generations: [generation({ song_id: 's-tide' })],
				generation_count: 2
			}),
			song({
				id: 's-ebb',
				album_id: 'a-local',
				album_title: 'Night Drive',
				title: 'Ebb',
				generation_count: 1
			})
		]);
		return renderDetail();
	}

	function rowOf(target: HTMLElement, title: string): HTMLElement {
		const row = Array.from(target.querySelectorAll<HTMLElement>('.item-row')).find(
			(candidate) => candidate.querySelector('.item-title')?.textContent === title
		);
		if (!row) throw new Error(`Expected a row for ${title}`);
		return row;
	}

	it('counts takes, not gens, on a song row', async () => {
		const target = await renderTwoSongs();
		expect(rowOf(target, 'Tide').querySelector('.item-meta')?.textContent?.trim()).toBe('2 takes');
	});

	it('opens the song in the editor when the row is tapped, without playing it', async () => {
		const target = await renderTwoSongs();

		requireElement<HTMLButtonElement>(rowOf(target, 'Tide'), '.item-body').click();
		await tick();

		expect(selectSong).toHaveBeenCalledWith('s-tide');
		expect(playAlbum).not.toHaveBeenCalled();
	});

	it('is one target from edge to edge, 44 px high on a coarse pointer', async () => {
		injectHitboxStyles();
		const row = rowOf(await renderTwoSongs(), 'Tide');
		injectComponentStyles(albumDetailViewSource, 'AlbumDetailView.svelte', row);
		setPointer('coarse');

		const { paddingTop, paddingRight, paddingBottom, paddingLeft } = getComputedStyle(row);
		expect([paddingTop, paddingRight, paddingBottom, paddingLeft].map((side) => px(side))).toEqual([
			0, 0, 0, 0
		]);
		expect(minHeightPx(requireElement(row, '.item-body'), 'album row')).toBe(HITBOX_FREQUENT_PX);
	});

	it('carries no play glyph of its own: the row is its only button', async () => {
		const target = await renderTwoSongs();

		expect(rowOf(target, 'Tide').querySelectorAll('button')).toHaveLength(1);
	});

	it.each(['playing', 'paused'] as const)(
		'marks the row the transport holds while %s, and only that row',
		async (status) => {
			audioPlayer.current = { songId: 's-tide' } as unknown as typeof audioPlayer.current;
			audioPlayer.status = status;

			const target = await renderTwoSongs();

			expect(
				findElementByRoleAndName(rowOf(target, 'Tide'), 'img', PLAYING_MARK_LABEL)
			).not.toBeNull();
			expect(rowOf(target, 'Tide').classList.contains('current')).toBe(true);
			expect(findElementByRoleAndName(rowOf(target, 'Ebb'), 'img', PLAYING_MARK_LABEL)).toBeNull();
			expect(rowOf(target, 'Ebb').classList.contains('current')).toBe(false);
		}
	);
});
