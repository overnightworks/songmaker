import {
	makeAlbum as album,
	makeGeneration as generation,
	makeSong as song
} from '#lib/test-utils/factories.ts';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from 'vitest';
import { get } from 'svelte/store';

import type { CoverSuggestionsResponse } from '#lib/api/types.ts';
import { ApiError } from '#lib/api/fetch.ts';
import { lostNetwork, serverRefusal } from '#lib/test-utils/network.ts';
import {
	reportResourceStreamReachable,
	resetConnectivityForTests
} from '#lib/stores/connectivity.ts';
import {
	ALBUM_COVER_ALT_TYPE,
	ALBUM_NO_SONGS,
	HITBOX_FREQUENT_PX,
	collectionActionLabel,
	NEW_SONG_CLOSE_LABEL,
	NEW_SONG_ROW_LABEL,
	newSongCardLabel,
	PLAYING_MARK_LABEL,
	songEditorOpenLabel,
	TRANSPORT_PLAY_LABEL,
	TRANSPORT_PAUSE_LABEL,
	TRANSPORT_RETRY_LABEL
} from '#lib/constants.ts';
import {
	accessibleName,
	getByRoleButton,
	getByRoleHeading
} from '#lib/test-utils/accessible-name.ts';
import { menuRowLabels } from '#lib/test-utils/collection-menu.ts';
import { shownTransportFace } from '#lib/test-utils/transport-face.ts';
import {
	describeBackClosesOverlay,
	standingHistoryEntry
} from '#lib/test-utils/library-history.ts';
import { createButton, createSettled, field, type } from '#lib/test-utils/new-place-card.ts';
import { findElementByRoleAndName, openCollectionMenu } from './shell/rail-test-fixtures';
import {
	clearHitboxStyles,
	clearPointer,
	injectHitboxStyles,
	minHeightPx,
	px,
	setPointer
} from '#lib/test-utils/hitbox.ts';
import {
	clearComponentStyles,
	elementScopeClass,
	injectComponentStyles
} from '#lib/test-utils/component-styles.ts';
import {
	albumList,
	loadSongsForAlbum,
	resetLibraryDataForTests,
	songList
} from '#lib/stores/libraryData.ts';
import { fetchSongs } from '#lib/api/songs.ts';
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
import songRowSource from './SongRow.svelte?raw';
import { selectSong } from '#lib/stores/navigation.ts';
import {
	ensureGenerationsLoaded,
	pendingStart,
	playAlbum,
	playAlbumSong,
	playStartNotice,
	setPendingStartForTests,
	setShuffle,
	shuffleEnabled
} from '#lib/stores/player.ts';
import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import { addToast } from '#lib/stores/toast.ts';

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
	createSong.mockReset();
	vi.mocked(ensureGenerationsLoaded).mockReset();
	vi.mocked(playAlbum).mockReset();
	vi.mocked(playAlbumSong).mockReset();
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
	playStartNotice.set('idle');
	setPendingStartForTests(null);
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

function songsPage(items: ReturnType<typeof song>[]) {
	return { items, total: items.length, offset: 0, limit: 200, has_more: false };
}

describe('AlbumDetailView songs that could not load', () => {
	const ALBUM_SONGS_FAILURE = 'Failed to load songs';

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

	it('shows cover, title, its song count, Play, ⋯ and the songs, with no breadcrumb and no shuffle (#1354 rule 24)', async () => {
		const target = await renderDetail();
		const header = requireElement(target, '.collection-header');
		expect(header.querySelector('.header-cover')).not.toBeNull();
		expect(header.querySelector('.header-title')?.textContent).toContain('Night Drive');
		expect(requireElement(header, '.header-count').textContent).toBe('1 song');
		expect(
			getByRoleButton(header, collectionActionLabel(TRANSPORT_PLAY_LABEL, 'album'))
		).not.toBeNull();
		expect(header.querySelector('.collection-menu')).not.toBeNull();
		expect(target.querySelectorAll('.song-row')).toHaveLength(1);
		expect(target.querySelector('nav')).toBeNull();
		expect(target.textContent).not.toContain('Library');
		expect(
			[...target.querySelectorAll('button')].filter((button) =>
				/shuffle/i.test(accessibleName(button))
			)
		).toEqual([]);
	});

	it("shows the album's song count while its songs load", async () => {
		albumList.set([album({ id: 'a-local', title: 'Night Drive', song_count: 5 })]);
		songList.set([]);
		let answerSongs: (page: ReturnType<typeof songsPage>) => void = () => {};
		vi.mocked(fetchSongs).mockReturnValueOnce(new Promise((resolve) => (answerSongs = resolve)));
		const songsLoaded = loadSongsForAlbum('a-local');
		onTestFinished(async () => {
			answerSongs(songsPage([]));
			await songsLoaded;
		});
		const target = await renderDetail();

		expect(requireElement(target, '.collection-header .header-count').textContent).toBe('5 songs');
	});

	it('starts this album in order from its play circle', async () => {
		setShuffle(true);
		const target = await renderDetail();

		getByRoleButton(
			requireElement(target, '.collection-header'),
			collectionActionLabel(TRANSPORT_PLAY_LABEL, 'album')
		).click();

		expect(playAlbum).toHaveBeenCalledWith('a-local');
		expect(get(shuffleEnabled)).toBe(false);
	});

	function playCircle(target: HTMLElement): HTMLButtonElement {
		return requireElement<HTMLButtonElement>(target, '.collection-header .play-circle');
	}

	function circleFacts(circle: HTMLButtonElement) {
		return {
			label: circle.getAttribute('aria-label'),
			busy: circle.getAttribute('aria-busy'),
			face: shownTransportFace(circle)
		};
	}

	describe('while a start of this album waits (#1330)', () => {
		const readsBusyPause = {
			label: collectionActionLabel(TRANSPORT_PAUSE_LABEL, 'album'),
			busy: 'true',
			face: 'spinner'
		};

		// A take of another album, loaded and paused, as after a reload or a
		// pause before the listener opened this album.
		function loadPausedTakeOfAnotherAlbum(): void {
			queueContext.set({ type: 'album', albumId: 'a-other' });
			audioPlayer.current = {
				songId: 's-other',
				generation: generation({ song_id: 's-other' })
			} as unknown as typeof audioPlayer.current;
			audioPlayer.status = 'paused';
		}

		it.each([
			{ loaded: 'no take', load: () => {} },
			{ loaded: 'a paused take of another album', load: loadPausedTakeOfAnotherAlbum }
		])(
			'with $loaded loaded, a header start waiting for the network reads Pause with its spinner, and a tap withdraws it',
			async ({ load }) => {
				load();
				setPendingStartForTests({
					albumId: 'a-local',
					song: { songTitle: 'Song', artist: 'Artist', albumTitle: 'Night Drive' }
				});
				playStartNotice.set('awaiting-network');
				const target = await renderDetail();
				const whileWaiting = circleFacts(playCircle(target));

				playCircle(target).click();
				await tick();

				expect({
					whileWaiting,
					afterTheTap: circleFacts(playCircle(target)),
					waiting: get(pendingStart),
					startedAgain: vi.mocked(playAlbum).mock.calls.length
				}).toEqual({
					whileWaiting: readsBusyPause,
					afterTheTap: {
						label: collectionActionLabel(TRANSPORT_PLAY_LABEL, 'album'),
						busy: 'false',
						face: 'play'
					},
					waiting: null,
					startedAgain: 0
				});
			}
		);

		it('a take of it waiting for its bytes reads Pause with its spinner, and a tap pauses it', async () => {
			queueContext.set({ type: 'album', albumId: 'a-local' });
			audioPlayer.current = {
				songId: 's-local',
				generation: generation({ song_id: 's-local' })
			} as unknown as typeof audioPlayer.current;
			audioPlayer.status = 'buffering';
			vi.spyOn(audioPlayer, 'toggle').mockImplementation(() => {
				audioPlayer.status = 'paused';
			});
			const target = await renderDetail();
			const whileWaiting = circleFacts(playCircle(target));

			playCircle(target).click();
			await tick();

			expect({
				whileWaiting,
				status: audioPlayer.status,
				startedAgain: vi.mocked(playAlbum).mock.calls.length
			}).toEqual({ whileWaiting: readsBusyPause, status: 'paused', startedAgain: 0 });
		});
	});

	it.each([
		{
			status: 'playing',
			label: collectionActionLabel(TRANSPORT_PAUSE_LABEL, 'album'),
			face: 'pause'
		},
		{
			status: 'error',
			label: collectionActionLabel(TRANSPORT_RETRY_LABEL, 'album'),
			face: 'refresh-cw'
		}
	] as const)(
		'names and draws the circle as the bar does while a take of this album is $status (#1330)',
		async ({ status, label, face }) => {
			queueContext.set({ type: 'album', albumId: 'a-local' });
			audioPlayer.current = {
				songId: 's-local',
				generation: generation({ song_id: 's-local' })
			} as unknown as typeof audioPlayer.current;
			audioPlayer.status = status;

			const target = await renderDetail();

			expect(circleFacts(playCircle(target))).toEqual({ label, busy: 'false', face });
		}
	);

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
	])('dims play on an album %s, and a tap keeps the running queue', async (_, songs) => {
		setShuffle(true);
		albumList.set([album({ id: 'a-local', title: 'Night Drive', has_playable_take: false })]);
		songList.set(songs);
		const running = { type: 'library' as const, index: 3 };
		queueContext.set(running);
		const target = await renderDetail();
		const circle = getByRoleButton(
			requireElement(target, '.collection-header'),
			collectionActionLabel(TRANSPORT_PLAY_LABEL, 'album')
		);

		circle.click();
		await tick();

		expect(circle.disabled).toBe(true);
		expect(playAlbum).not.toHaveBeenCalled();
		expect(get(queueContext)).toBe(running);
		expect(get(shuffleEnabled)).toBe(true);
	});

	it('1354_rule_11: dims play on an album whose completed load found no songs, whatever the server says', async () => {
		albumList.set([album({ id: 'a-local', title: 'Night Drive', has_playable_take: true })]);
		songList.set([]);
		vi.mocked(fetchSongs).mockResolvedValueOnce(songsPage([]));
		await loadSongsForAlbum('a-local');
		const target = await renderDetail();

		const circle = getByRoleButton(
			requireElement(target, '.collection-header'),
			collectionActionLabel(TRANSPORT_PLAY_LABEL, 'album')
		);
		expect(circle.disabled).toBe(true);
	});

	it.each([
		['the server says nothing is playable', false, 'unloaded'],
		['its loaded songs hold only archived takes (defect:#1386)', true, 'loaded']
	])(
		'1354_rule_11: dims play on an album with takes but nothing to hear, because %s',
		async (_, serverSaysPlayable, songsState) => {
			albumList.set([
				album({ id: 'a-local', title: 'Night Drive', has_playable_take: serverSaysPlayable })
			]);
			const archivedOnly = song({
				id: 's-local',
				album_id: 'a-local',
				album_title: 'Night Drive',
				generation_count: 1,
				generations: [generation({ song_id: 's-local', is_archived: true })]
			});
			if (songsState === 'loaded') {
				vi.mocked(fetchSongs).mockResolvedValueOnce(songsPage([archivedOnly]));
				await loadSongsForAlbum('a-local');
			} else {
				songList.set([archivedOnly]);
			}
			const target = await renderDetail();

			const circle = getByRoleButton(
				requireElement(target, '.collection-header'),
				collectionActionLabel(TRANSPORT_PLAY_LABEL, 'album')
			);
			expect(circle.disabled).toBe(true);
		}
	);

	it('keeps pause on the circle of a playing album whose songs have no takes', async () => {
		songList.set([
			song({ id: 's-local', album_id: 'a-local', album_title: 'Night Drive', generation_count: 0 })
		]);
		queueContext.set({ type: 'album', albumId: 'a-local' });
		audioPlayer.current = {
			songId: 's-local',
			generation: generation({ song_id: 's-local' })
		} as unknown as typeof audioPlayer.current;
		audioPlayer.status = 'playing';
		const target = await renderDetail();
		const header = requireElement(target, '.collection-header');

		expect(
			getByRoleButton(header, collectionActionLabel(TRANSPORT_PAUSE_LABEL, 'album')).disabled
		).toBe(false);
	});

	it('sizes Play album to the frequent hitbox on a coarse pointer', async () => {
		// #163/6: the album header's play is the shortest path to hearing the
		// album, and on a phone it has to be reachable with a thumb.
		const label = collectionActionLabel(TRANSPORT_PLAY_LABEL, 'album');
		injectHitboxStyles();
		const target = await renderDetail();
		const button = getByRoleButton(requireElement(target, '.collection-header'), label);
		setPointer('coarse');

		expect(minHeightPx(button, label)).toBe(HITBOX_FREQUENT_PX);
	});

	it('915_C3: names the album and lists Edit details, Cover, Pick album takes, Add to playlist, Share, Archive, Delete in the menu', async () => {
		const target = await renderDetail();
		const menu = await openCollectionMenu(target);
		expect(menu.querySelector('.menu-heading')?.textContent).toBe('Album · Night Drive');
		expect(menuRowLabels(menu)).toEqual([
			'Edit details',
			'Cover',
			'Pick album takes',
			'Add to playlist',
			'Share',
			'Archive',
			'Delete'
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
			(el) => el.textContent?.trim() === 'Pick album takes'
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
		{ failure: lostNetwork(), toast: 'Cover upload failed' },
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
			(el) => el.textContent?.trim() === 'Archive'
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
		.find((item) => item.textContent?.trim().startsWith('Cover'))
		?.click();
	await vi.waitFor(() => expect(target.querySelector('.cover-editor')).not.toBeNull());
	getByRoleButton(requireElement(target, '.cover-editor'), 'Upload').click();
}

async function openEditDetails(target: HTMLElement): Promise<HTMLFormElement> {
	const menu = await openCollectionMenu(target);
	Array.from(menu.querySelectorAll<HTMLButtonElement>('.menu-item'))
		.find((item) => item.textContent?.trim() === 'Edit details')
		?.click();
	await tick();
	return requireElement<HTMLFormElement>(target, 'form[aria-label="Edit details"]');
}

function detailsForm(target: HTMLElement): HTMLFormElement | null {
	return target.querySelector<HTMLFormElement>('form[aria-label="Edit details"]');
}

async function saveDetails(form: HTMLFormElement): Promise<void> {
	getByRoleButton(form, 'Save').click();
	await tick();
	await tick();
	await tick();
}

describe('AlbumDetailView Edit details', () => {
	beforeEach(() => {
		albumList.set([
			album({ id: 'a-local', title: 'Night Drive', subtitle: 'Live at the Roxy', year: '1994' })
		]);
	});

	it('reads subtitle · year under the title, with no Add subtitle · Add year line', async () => {
		const target = await renderDetail();
		expect(target.querySelector('.header-meta')?.textContent).toBe('Live at the Roxy · 1994');

		albumList.set([album({ id: 'a-local', title: 'Night Drive' })]);
		await tick();

		expect(target.querySelector('.header-meta')).toBeNull();
		expect(target.textContent).not.toContain('Add subtitle');
		expect(target.textContent).not.toContain('Add year');
	});

	it('keeps focus in Title once the menu that opened Edit details has closed', async () => {
		const target = await renderDetail();
		const form = await openEditDetails(target);
		await Promise.resolve();
		await tick();

		expect(document.activeElement).toBe(field(form, 'Title'));
	});

	it('saves title, subtitle and year in one update, and the header reads the new details', async () => {
		updateAlbum.mockResolvedValue(
			album({ id: 'a-local', title: 'Nightdrive', subtitle: 'Late-night synthwave', year: '2026' })
		);
		const target = await renderDetail();
		const form = await openEditDetails(target);

		type(field(form, 'Title'), 'Nightdrive');
		type(field(form, 'Subtitle'), 'Late-night synthwave');
		type(field(form, 'Year'), '2026');
		await saveDetails(form);

		expect(updateAlbum).toHaveBeenCalledWith('a-local', {
			title: 'Nightdrive',
			subtitle: 'Late-night synthwave',
			year: 2026
		});
		await vi.waitFor(() => expect(detailsForm(target)).toBeNull());
		expect(get(albumList)[0].title).toBe('Nightdrive');
		expect(target.querySelector('.header-title')?.textContent?.trim()).toBe('Nightdrive');
		expect(target.querySelector('.header-meta')?.textContent).toBe('Late-night synthwave · 2026');
		expect(addToast).toHaveBeenCalledWith('Details saved', 'success');
	});

	it('clears the year with an emptied field', async () => {
		updateAlbum.mockResolvedValue(album({ id: 'a-local', title: 'Night Drive' }));
		const target = await renderDetail();
		const form = await openEditDetails(target);

		type(field(form, 'Year'), '');
		await saveDetails(form);

		expect(updateAlbum).toHaveBeenCalledWith('a-local', {
			title: 'Night Drive',
			subtitle: 'Live at the Roxy',
			year: null
		});
	});

	it.each([
		{ year: 'abcd', reason: 'Year must be a whole number' },
		{ year: '1899', reason: 'Year must be between 1900 and 2100' }
	])('refuses the year $year with a readable reason, saving nothing', async ({ year, reason }) => {
		const target = await renderDetail();
		const form = await openEditDetails(target);

		type(field(form, 'Year'), year);
		await saveDetails(form);

		expect(updateAlbum).not.toHaveBeenCalled();
		expect(addToast).toHaveBeenCalledWith(reason, 'error');
		expect(detailsForm(target)).not.toBeNull();
		expect(field(form, 'Year').value).toBe(year);
	});

	it('names the server refusal and keeps the editor open with the draft', async () => {
		updateAlbum.mockRejectedValue(serverRefusal('Title is already taken'));
		const target = await renderDetail();
		const form = await openEditDetails(target);

		type(field(form, 'Title'), 'Taken');
		await saveDetails(form);

		await vi.waitFor(() =>
			expect(addToast).toHaveBeenCalledWith('Title is already taken', 'error')
		);
		expect(detailsForm(target)).not.toBeNull();
		expect(field(form, 'Title').value).toBe('Taken');
		expect(get(albumList)[0].title).toBe('Night Drive');
	});

	it('× closes the editor without saving the draft', async () => {
		const target = await renderDetail();
		const form = await openEditDetails(target);

		type(field(form, 'Year'), '2026');
		getByRoleButton(form, 'Close edit details').click();
		await tick();

		expect(detailsForm(target)).toBeNull();
		expect(updateAlbum).not.toHaveBeenCalled();
		expect(target.querySelector('.header-meta')?.textContent).toBe('Live at the Roxy · 1994');
	});

	it('ends editing, its draft unsaved, when another album opens', async () => {
		albumList.update((albums) => [...albums, album({ id: 'a-other', title: 'Other Night' })]);
		const target = await renderDetail();
		await openEditDetails(target);

		selectedAlbumId.set('a-other');
		await tick();

		expect(detailsForm(target)).toBeNull();
		expect(target.querySelector('.header-title')?.textContent?.trim()).toBe('Other Night');
		expect(updateAlbum).not.toHaveBeenCalled();
	});
});

describeBackClosesOverlay({
	name: 'the Edit details editor',
	render: renderDetail,
	open: async (target) => {
		const form = await openEditDetails(target);
		await vi.waitFor(() => expect(standingHistoryEntry()?.layer).toBe('details-editing'));
		type(field(form, 'Year'), '2026');
	},
	isShown: (target) => detailsForm(target) !== null,
	afterBack: () => expect(updateAlbum).not.toHaveBeenCalled(),
	closeWays: [
		{
			way: '×',
			close: (target) => getByRoleButton(target, 'Close edit details').click()
		},
		{
			way: 'Escape in a field',
			close: (target) =>
				detailsForm(target)
					?.querySelector('input')
					?.dispatchEvent(
						new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
					)
		},
		{
			way: 'Escape outside the form',
			close: () =>
				document.body.dispatchEvent(
					new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
				)
		}
	]
});

describe('AlbumDetailView song row', () => {
	function renderSongs(): Promise<HTMLElement> {
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
			}),
			song({
				id: 's-fresh',
				album_id: 'a-local',
				album_title: 'Night Drive',
				title: 'Fresh',
				generation_count: 0
			})
		]);
		return renderDetail();
	}

	function rowOf(target: HTMLElement, title: string): HTMLElement {
		const row = Array.from(target.querySelectorAll<HTMLElement>('.song-row')).find(
			(candidate) => candidate.querySelector('.song-row-title')?.textContent?.trim() === title
		);
		if (!row) throw new Error(`Expected a row for ${title}`);
		return row;
	}

	function boxOf(target: HTMLElement, title: string): HTMLButtonElement {
		return requireElement<HTMLButtonElement>(rowOf(target, title), '.song-row-body');
	}

	it('counts takes, not gens, on a song row', async () => {
		const target = await renderSongs();
		expect(rowOf(target, 'Tide').querySelector('.song-row-meta')?.textContent?.trim()).toBe(
			'2 takes'
		);
	});

	it('plays a tapped song in place: the album page stays and the editor stays shut (#1354 rule 22)', async () => {
		const target = await renderSongs();

		boxOf(target, 'Tide').click();

		expect(playAlbumSong).toHaveBeenCalledExactlyOnceWith('a-local', 's-tide');
		expect(selectSong).not.toHaveBeenCalled();
		expect(getByRoleHeading(target, 'Night Drive')).not.toBeNull();
	});

	it.each([
		['unloaded', 1, [], 'player'],
		['loaded with archived takes', 1, [generation({ is_archived: true })], 'editor'],
		['loaded with empty-path takes', 1, [generation({ mp3_path: '' })], 'editor'],
		['loaded with a playable take', 1, [generation()], 'player'],
		['without generations', 0, [], 'editor']
	] as const)(
		'defect:#1386: a song %s acts immediately without loading takes first',
		async (_, count, takes, destination) => {
			const target = await renderSongs();
			songList.update((songs) =>
				songs.map((item) =>
					item.id === 's-ebb' ? { ...item, generation_count: count, generations: [...takes] } : item
				)
			);
			await tick();

			boxOf(target, 'Ebb').click();

			if (destination === 'editor') {
				expect(selectSong).toHaveBeenCalledExactlyOnceWith('s-ebb');
				expect(playAlbumSong).not.toHaveBeenCalled();
			} else {
				expect(playAlbumSong).toHaveBeenCalledExactlyOnceWith('a-local', 's-ebb');
				expect(selectSong).not.toHaveBeenCalled();
			}
			expect(ensureGenerationsLoaded).not.toHaveBeenCalled();
		}
	);

	it('opens a song with no take yet in the song editor on a tap (#1354 rule 23)', async () => {
		const target = await renderSongs();

		boxOf(target, 'Fresh').click();

		expect(selectSong).toHaveBeenCalledExactlyOnceWith('s-fresh');
		expect(playAlbumSong).not.toHaveBeenCalled();
	});

	it.each(['Tide', 'Fresh'])(
		'opens %s in the song editor from its ✎, without playing it',
		async (title) => {
			const target = await renderSongs();

			getByRoleButton(rowOf(target, title), songEditorOpenLabel(title)).click();
			await tick();

			expect(selectSong).toHaveBeenCalledExactlyOnceWith(`s-${title.toLowerCase()}`);
			expect(playAlbumSong).not.toHaveBeenCalled();
		}
	);

	it('is one target from edge to edge, 44 px high on a coarse pointer', async () => {
		injectHitboxStyles();
		const row = rowOf(await renderSongs(), 'Tide');
		injectComponentStyles(songRowSource, 'SongRow.svelte', row);
		setPointer('coarse');

		const { paddingTop, paddingRight, paddingBottom, paddingLeft } = getComputedStyle(row);
		expect([paddingTop, paddingRight, paddingBottom, paddingLeft].map((side) => px(side))).toEqual([
			0, 0, 0, 0
		]);
		expect(minHeightPx(requireElement(row, '.song-row-body'), 'album row')).toBe(
			HITBOX_FREQUENT_PX
		);
	});

	it('carries no play glyph of its own: the box and its ✎ are its only buttons', async () => {
		const target = await renderSongs();

		expect(
			[...rowOf(target, 'Tide').querySelectorAll('button')].map((button) => accessibleName(button))
		).toEqual([expect.stringMatching(/^Tide\s+2 takes$/), songEditorOpenLabel('Tide')]);
	});

	it.each(['playing', 'paused'] as const)(
		'marks the row the transport holds while %s, and only that row',
		async (status) => {
			audioPlayer.current = {
				songId: 's-tide',
				generation: generation({ song_id: 's-tide' })
			} as unknown as typeof audioPlayer.current;
			audioPlayer.status = status;

			const target = await renderSongs();

			expect(
				findElementByRoleAndName(rowOf(target, 'Tide'), 'img', PLAYING_MARK_LABEL)
			).not.toBeNull();
			expect(rowOf(target, 'Tide').classList.contains('current')).toBe(true);
			expect(findElementByRoleAndName(rowOf(target, 'Ebb'), 'img', PLAYING_MARK_LABEL)).toBeNull();
			expect(rowOf(target, 'Ebb').classList.contains('current')).toBe(false);
		}
	);
});

describe('AlbumDetailView new song', () => {
	const NEW_SONG_CARD = newSongCardLabel('Night Drive');

	function newSongRow(target: HTMLElement): HTMLButtonElement | null {
		return (
			Array.from(target.querySelectorAll('button')).find(
				(button) => accessibleName(button) === NEW_SONG_ROW_LABEL
			) ?? null
		);
	}

	function newSongCard(target: HTMLElement): HTMLFormElement | null {
		return target.querySelector<HTMLFormElement>(`form[aria-label="${NEW_SONG_CARD}"]`);
	}

	async function openNewSongCard(target: HTMLElement): Promise<HTMLFormElement> {
		newSongRow(target)?.click();
		await tick();
		const card = newSongCard(target);
		if (!card) throw new Error('Expected the new song card to open');
		return card;
	}

	function listItems(target: HTMLElement): Element[] {
		return Array.from(requireElement(target, '.item-list').children);
	}

	it('ends a filled track list with a quiet + New song row', async () => {
		const target = await renderDetail();

		const items = listItems(target);
		expect(items).toHaveLength(2);
		expect(items[0].querySelector('.song-row-title')?.textContent?.trim()).toBe('Local Only');
		expect(items[1].contains(newSongRow(target))).toBe(true);
	});

	it('says No songs yet. above the + New song row in an empty album', async () => {
		songList.set([]);
		const target = await renderDetail();

		expect(listItems(target).map((item) => item.textContent?.trim())).toEqual([
			ALBUM_NO_SONGS,
			NEW_SONG_ROW_LABEL
		]);
	});

	it('turns the row into the New song in <album> card in its place', async () => {
		const target = await renderDetail();

		await openNewSongCard(target);

		expect(newSongRow(target)).toBeNull();
		expect(listItems(target).at(-1)?.getAttribute('aria-label')).toBe(NEW_SONG_CARD);
	});

	it('creates the song in this album and opens it, folding the card away', async () => {
		createSong.mockResolvedValue(song({ id: 's-tide', album_id: 'a-local', title: 'Tidewater' }));
		const target = await renderDetail();
		const card = await openNewSongCard(target);

		type(field(card, 'Title'), 'Tidewater');
		createButton(card).click();
		await createSettled(createSong);

		expect(createSong).toHaveBeenCalledWith({ title: 'Tidewater', album_id: 'a-local' });
		await vi.waitFor(() => expect(selectSong).toHaveBeenCalledWith('s-tide'));
		expect(newSongCard(target)).toBeNull();
	});

	it('× folds the card back into the row, holding the focus, and creates nothing', async () => {
		const target = await renderDetail();
		const card = await openNewSongCard(target);
		type(field(card, 'Title'), 'Tidewater');

		card.querySelector<HTMLButtonElement>(`[aria-label="${NEW_SONG_CLOSE_LABEL}"]`)?.click();
		await tick();

		expect(newSongCard(target)).toBeNull();
		expect(document.activeElement).toBe(newSongRow(target));
		expect(createSong).not.toHaveBeenCalled();
	});

	describeBackClosesOverlay({
		name: 'the new song card',
		render: renderDetail,
		open: async (target) => {
			await openNewSongCard(target);
		},
		isShown: (target) => newSongCard(target) !== null,
		afterBack: () => {
			expect(accessibleName(document.activeElement ?? document.body)).toBe(NEW_SONG_ROW_LABEL);
			expect(createSong).not.toHaveBeenCalled();
		},
		closeWays: [
			{
				way: '×',
				close: (target) =>
					target.querySelector<HTMLButtonElement>(`[aria-label="${NEW_SONG_CLOSE_LABEL}"]`)?.click()
			}
		]
	});
});
