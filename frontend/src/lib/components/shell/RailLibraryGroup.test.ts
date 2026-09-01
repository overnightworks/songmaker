import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { GenerationItem, SongItem } from '$lib/api/types';
import { openCollection } from '$lib/stores/collection';
import { resetLibraryContextForTests } from '$lib/stores/libraryContext';
import { albumList, allAlbumsLoad, songList } from '$lib/stores/libraryData';
import { closeNowPlaying, selectedSongId, setShuffle } from '$lib/stores/player';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import type { AlbumItem } from '$lib/api/types';

vi.mock('$app/navigation', () => ({ goto: vi.fn().mockResolvedValue(undefined) }));
vi.mock('$app/paths', () => ({ resolve: vi.fn((path: string) => path) }));
vi.mock('$lib/api/library', () => ({
	searchLibrary: vi.fn().mockResolvedValue({ items: [], next_cursor: null, has_more: false })
}));
vi.mock('$lib/api/albums', () => ({
	fetchAlbum: vi.fn(),
	fetchAlbums: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50, has_more: false })
}));
vi.mock('$lib/api/songs', () => ({
	fetchSong: vi.fn(),
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false })
}));
const fetchAlbums = vi
	.fn()
	.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50, has_more: false });
const fetchSongs = vi
	.fn()
	.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false });
vi.mock('$lib/api/client', () => ({
	fetchAlbums: (...args: unknown[]) => fetchAlbums(...args),
	fetchAlbum: vi.fn(),
	fetchSong: vi.fn(),
	fetchSongs: (...args: unknown[]) => fetchSongs(...args),
	fetchPlaylists: vi.fn().mockResolvedValue([]),
	fetchPlaylist: vi.fn(),
	// Exercised by loadSongContext's hydrateGenerationFailure fire-and-forget
	// call whenever a test drives a real selectSong through a track click.
	fetchLastFailedGeneration: vi.fn().mockResolvedValue({ job: null })
}));

import RailLibraryGroup from './RailLibraryGroup.svelte';

let mounted: ReturnType<typeof mount> | undefined;

function requireElement<T extends Element>(root: ParentNode, selector: string): T {
	const element = root.querySelector<T>(selector);
	if (!element) throw new Error(`Expected ${selector} to be rendered`);
	return element;
}

function album(overrides: Partial<AlbumItem> = {}): AlbumItem {
	return {
		id: 'a1',
		title: 'Nachtstrom',
		artist: 'Artist',
		subtitle: '',
		year: '',
		colors: {},
		song_count: 2,
		picked_count: 0,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00',
		is_archived: false,
		...overrides
	};
}

function song(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's1',
		slug: 'tide',
		title: 'Tide',
		album_id: 'a1',
		album_title: 'Nachtstrom',
		artist: 'Artist',
		track_number: 1,
		vocal_language: 'en',
		lyrics: '',
		prompt: '',
		bpm: 120,
		audio_duration: 180,
		key_scale: 'Am',
		generation_params: null,
		version_count: 1,
		generation_count: 1,
		best_scores: null,
		best_rating: null,
		generations: [],
		created_at: '2026-01-01T00:00:00+00:00',
		is_shared: false,
		share_slug: null,
		...overrides
	};
}

function generation(overrides: Partial<GenerationItem> = {}): GenerationItem {
	return {
		id: 'g1',
		song_id: 's1',
		version_id: 'v1',
		version_number: 1,
		generation_number: 1,
		mp3_path: 'g1.mp3',
		wav_path: null,
		seed: 1,
		status: 'completed',
		is_archived: false,
		is_picked: false,
		is_kept: false,
		is_shared: false,
		model_mode: 'turbo',
		whisper_text: null,
		whisper_cues: null,
		version_lyrics: null,
		scores: null,
		generation_params: null,
		audio_duration_sec: null,
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

async function render(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(RailLibraryGroup, { target });
	await tick();
	return target;
}

beforeEach(() => {
	localStorage.clear();
	resetLibraryContextForTests();
	fetchAlbums.mockClear().mockResolvedValue({
		items: [],
		total: 0,
		offset: 0,
		limit: 50,
		has_more: false
	});
	fetchSongs.mockClear().mockResolvedValue({
		items: [],
		total: 0,
		offset: 0,
		limit: 200,
		has_more: false
	});
	allAlbumsLoad.set({ status: 'idle', error: null });
	albumList.set([album()]);
	songList.set([
		song({ id: 's1', title: 'Tide', track_number: 1 }),
		song({ id: 's2', title: 'Ebb', track_number: 2 })
	]);
	selectedSongId.set(null);
	setShuffle(false);
	closeNowPlaying();
	vi.spyOn(audioPlayer, 'load').mockImplementation((playback) => {
		audioPlayer.current = playback;
	});
});

afterEach(async () => {
	audioPlayer.current = null;
	setShuffle(false);
	closeNowPlaying();
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	openCollection.set(null);
	resetLibraryContextForTests();
});

describe('RailLibraryGroup', () => {
	it('shows the LIBRARY group with its icon and the current album count, collapsed with no album open', async () => {
		const target = await render();
		const toggle = requireElement<HTMLButtonElement>(target, 'button.disclose');
		expect(toggle.textContent).toContain('Library');
		expect(target.querySelector('.meta')?.textContent).toBe('1');
		expect(toggle.getAttribute('aria-expanded')).toBe('false');
	});

	it('loads every album on mount regardless of the current route', async () => {
		await render();
		await vi.waitFor(() => expect(fetchAlbums).toHaveBeenCalled());
	});

	it('opens on click and lists every album with its own song count', async () => {
		albumList.set([
			album({ id: 'a1', title: 'Nachtstrom' }),
			album({ id: 'a2', title: 'Anfield', song_count: 5 })
		]);
		const target = await render();
		requireElement<HTMLButtonElement>(target, 'button.disclose').click();
		await tick();
		const albumRows = target.querySelectorAll('.album-label .row-title');
		expect(Array.from(albumRows).map((row) => row.textContent)).toEqual(['Nachtstrom', 'Anfield']);
		const counts = target.querySelectorAll('.album-label .row-meta');
		expect(Array.from(counts).map((row) => row.textContent)).toEqual(['2', '5']);
	});

	it('pre-expands the open album and marks its selected track, in track order', async () => {
		openCollection.set({ kind: 'album', id: 'a1' });
		selectedSongId.set('s2');
		const target = await render();
		const albumToggle = requireElement<HTMLButtonElement>(target, '.album-disclose');
		expect(albumToggle.getAttribute('aria-expanded')).toBe('true');

		const rows = target.querySelectorAll('.row-sub2 .row-title');
		expect(Array.from(rows).map((row) => row.textContent)).toEqual(['Tide', 'Ebb']);
		const active = target.querySelector('.row-sub2.row-active .row-title');
		expect(active?.textContent).toBe('Ebb');
	});

	it('shows a take/pick summary per track', async () => {
		openCollection.set({ kind: 'album', id: 'a1' });
		songList.set([
			song({ id: 's1', title: 'Tide', track_number: 1, generation_count: 0, generations: [] }),
			song({
				id: 's2',
				title: 'Ebb',
				track_number: 2,
				generation_count: 3,
				generations: [generation({ id: 'g1', is_picked: true })]
			})
		]);
		const target = await render();
		const meta = Array.from(target.querySelectorAll('.row-sub2 .row-meta')).map(
			(el) => el.textContent
		);
		expect(meta).toEqual(['—', '3 takes · pick']);
	});

	it('selects a track when its row is clicked', async () => {
		openCollection.set({ kind: 'album', id: 'a1' });
		songList.set([
			song({ id: 's1', title: 'Tide', track_number: 1, generation_count: 0 }),
			song({ id: 's2', title: 'Ebb', track_number: 2, generation_count: 0 })
		]);
		const target = await render();
		const rows = target.querySelectorAll<HTMLButtonElement>('.row-sub2');
		rows[1]?.click();
		await tick();
		await vi.waitFor(() => expect(get(selectedSongId)).toBe('s2'));
	});

	it('toggles a closed album open on click, loading its songs on demand', async () => {
		albumList.set([
			album({ id: 'a1', title: 'Nachtstrom' }),
			album({ id: 'a2', title: 'Anfield' })
		]);
		songList.set([]);
		fetchSongs.mockImplementation((albumId: string) =>
			Promise.resolve({
				items:
					albumId === 'a2'
						? [song({ id: 's9', title: 'Kickoff', album_id: 'a2', track_number: 1 })]
						: [],
				total: 0,
				offset: 0,
				limit: 200,
				has_more: false
			})
		);
		const target = await render();
		const albumToggles = target.querySelectorAll<HTMLButtonElement>('.album-disclose');
		albumToggles[1]?.click();
		await tick();
		expect(albumToggles[1]?.getAttribute('aria-expanded')).toBe('true');
		await vi.waitFor(() => expect(target.textContent).toContain('Kickoff'));
	});

	it('navigates into the album and expands it when its label is clicked', async () => {
		albumList.set([
			album({ id: 'a1', title: 'Nachtstrom' }),
			album({ id: 'a2', title: 'Anfield' })
		]);
		const target = await render();
		const labels = target.querySelectorAll<HTMLButtonElement>('.album-label');
		labels[1]?.click();
		await tick();
		await Promise.resolve();

		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a2' });
		const toggles = target.querySelectorAll<HTMLButtonElement>('.album-disclose');
		expect(toggles[1]?.getAttribute('aria-expanded')).toBe('true');
	});

	it('toggles the row open without navigating when the chevron is clicked', async () => {
		albumList.set([album({ id: 'a1', title: 'Nachtstrom' })]);
		const target = await render();
		const toggle = requireElement<HTMLButtonElement>(target, '.album-disclose');

		toggle.click();
		await tick();
		await Promise.resolve();

		expect(toggle.getAttribute('aria-expanded')).toBe('true');
		expect(get(openCollection)).toBeNull();
	});

	it('does not refetch an album on a second expand once its songs are loaded', async () => {
		albumList.set([
			album({ id: 'a1', title: 'Nachtstrom' }),
			album({ id: 'a2', title: 'Anfield' })
		]);
		songList.set([]);
		fetchSongs.mockImplementation((albumId: string) =>
			Promise.resolve({
				items:
					albumId === 'a2'
						? [song({ id: 's9', title: 'Kickoff', album_id: 'a2', track_number: 1 })]
						: [],
				total: 0,
				offset: 0,
				limit: 200,
				has_more: false
			})
		);
		const target = await render();
		const albumToggles = target.querySelectorAll<HTMLButtonElement>('.album-disclose');
		albumToggles[1]?.click();
		await tick();
		await vi.waitFor(() => expect(target.textContent).toContain('Kickoff'));
		expect(fetchSongs).toHaveBeenCalledTimes(1);

		albumToggles[1]?.click();
		await tick();
		albumToggles[1]?.click();
		await tick();
		expect(fetchSongs).toHaveBeenCalledTimes(1);
	});

	it('refetches a genuinely empty album on every expand -- song_count is not trusted to stay accurate', async () => {
		albumList.set([album({ id: 'a1', title: 'Nachtstrom', song_count: 0 })]);
		songList.set([]);
		const target = await render();
		const albumToggle = requireElement<HTMLButtonElement>(target, '.album-disclose');

		albumToggle.click();
		await tick();
		expect(fetchSongs).toHaveBeenCalledTimes(1);

		albumToggle.click();
		await tick();
		albumToggle.click();
		await tick();
		expect(fetchSongs).toHaveBeenCalledTimes(2);
	});

	it('lets a viewer collapse the open album even while it stays the open collection', async () => {
		openCollection.set({ kind: 'album', id: 'a1' });
		const target = await render();
		const albumToggle = requireElement<HTMLButtonElement>(target, '.album-disclose');
		expect(albumToggle.getAttribute('aria-expanded')).toBe('true');

		albumToggle.click();
		await tick();
		expect(albumToggle.getAttribute('aria-expanded')).toBe('false');
	});
});
