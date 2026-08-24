import { createRawSnippet, mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { AlbumItem, GenerationItem, PlaylistDetailItem, SongItem } from '$lib/api/types';
import {
	albumList,
	selectedAlbumId,
	selectedGenerationId,
	selectedSongId,
	songList
} from '$lib/stores/player';
import { resetCollectionForTests, setOpenCollection } from '$lib/stores/collection';
import { selectedPlaylistDetail } from '$lib/stores/playlists';
import { EDITOR_LYRICS_LABEL, EDITOR_STYLE_PROMPT_LABEL } from '$lib/constants';

vi.mock('$lib/api/library', () => ({
	searchLibrary: vi.fn()
}));
vi.mock('$lib/api/albums', () => ({
	fetchAlbum: vi.fn(),
	fetchAlbums: vi.fn()
}));
vi.mock('$lib/api/songs', () => ({
	fetchSong: vi.fn(),
	fetchSongs: vi.fn()
}));
vi.mock('$lib/api/client', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/api/client')>();
	return {
		...actual,
		fetchVersions: vi.fn().mockResolvedValue([]),
		fetchHealth: vi.fn().mockResolvedValue(null),
		fetchSong: vi.fn(),
		fetchSongs: vi.fn(),
		sharePlaylist: vi.fn(),
		unsharePlaylist: vi.fn(),
		createQueueStreamSnapshot: vi.fn()
	};
});
vi.mock('$lib/api/queue-streams', () => ({
	pinQueueStream: vi.fn(),
	unpinQueueStream: vi.fn()
}));
vi.mock('$lib/services/offline', () => ({
	saveStream: vi.fn(),
	removeStream: vi.fn(),
	offlineStreamUrl: vi.fn(() => '/offline/stream/test'),
	rememberPlaylistOfflineStream: vi.fn(),
	forgetPlaylistOfflineStream: vi.fn(),
	loadSavedOfflinePlaylist: vi.fn().mockResolvedValue(null)
}));
vi.mock('$lib/stores/toast', () => ({
	addToast: vi.fn(),
	addUndoToast: vi.fn()
}));
vi.mock('$app/state', () => ({
	page: { url: new URL('https://songmaker.test/settings') }
}));

import AlbumDetailView from './AlbumDetailView.svelte';
import PlaylistDetailView from './PlaylistDetailView.svelte';
import SongDetailView from './SongDetailView.svelte';
import SettingsLayout from '../../routes/settings/+layout.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

function generation(overrides: Partial<GenerationItem> = {}): GenerationItem {
	return {
		id: 'g1',
		song_id: 's1',
		version_id: 'v1',
		version_number: 1,
		generation_number: 1,
		mp3_path: 'g1.mp3',
		wav_path: null,
		seed: 7,
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
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

function song(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's1',
		title: 'Local Only',
		album_id: 'a-local',
		album_title: 'Local Album',
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
		generations: [generation()],
		created_at: '2026-01-01T00:00:00+00:00',
		is_shared: false,
		share_slug: null,
		...overrides
	};
}

function album(overrides: Partial<AlbumItem> = {}): AlbumItem {
	return {
		id: 'a-local',
		title: 'Local Album',
		artist: 'Artist',
		subtitle: '',
		year: '',
		colors: {},
		song_count: 1,
		picked_count: 0,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00',
		is_archived: false,
		...overrides
	};
}

function playlistDetail(): PlaylistDetailItem {
	return {
		id: 'p1',
		title: 'Night Drive',
		entry_count: 1,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00',
		entries: []
	};
}

async function renderView(
	factory: (target: HTMLElement) => ReturnType<typeof mount>
): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(factory(target));
	await tick();
	await Promise.resolve();
	await tick();
	return target;
}

beforeEach(() => {
	albumList.set([album()]);
	songList.set([song()]);
	selectedAlbumId.set('a-local');
	selectedSongId.set('s1');
	selectedGenerationId.set('g1');
	const playlist = playlistDetail();
	setOpenCollection({ kind: 'playlist', id: playlist.id });
	selectedPlaylistDetail.set(playlist);
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	selectedAlbumId.set(null);
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	selectedPlaylistDetail.set(null);
	resetCollectionForTests();
	albumList.set([]);
	songList.set([]);
});

describe('detail views own no content back', () => {
	it('does not render a second back button in album, song, playlist, or generation views', async () => {
		const albumTarget = await renderView((target) => mount(AlbumDetailView, { target }));
		expect(albumTarget.querySelector('.back-btn')).toBeNull();
		expect(albumTarget.textContent).toContain('Local Album');

		selectedGenerationId.set(null);
		const songTarget = await renderView((target) => mount(SongDetailView, { target }));
		expect(songTarget.querySelector('.back-btn')).toBeNull();
		expect(songTarget.textContent).toContain('Local Only');

		const playlistTarget = await renderView((target) => mount(PlaylistDetailView, { target }));
		expect(playlistTarget.querySelector('.back-btn')).toBeNull();
		expect(playlistTarget.textContent).toContain('Night Drive');

		selectedGenerationId.set('g1');
		const generationTarget = await renderView((target) => mount(SongDetailView, { target }));
		expect(generationTarget.querySelector('.back-btn')).toBeNull();
		expect(generationTarget.textContent?.replace(/\s+/g, ' ')).toContain('Local Only');
		expect(generationTarget.textContent?.replace(/\s+/g, ' ')).toContain('v1 · take 1');
		expect(generationTarget.textContent).toContain(EDITOR_STYLE_PROMPT_LABEL);
		expect(generationTarget.textContent).toContain(EDITOR_LYRICS_LABEL);
		expect(generationTarget.querySelector('.cowriter-chat')).toBeNull();
	});

	it('does not treat a take as a separate back destination', async () => {
		const { goBack, initNavigation, resetNavigationForTests } =
			await import('$lib/stores/navigation');
		resetNavigationForTests();
		history.replaceState(null, '', '/?song=s1&gen=g1');
		const cleanup = initNavigation();
		expect(history.state.index).toBe(0);
		expect(get(selectedSongId)).toBe('s1');
		expect(get(selectedGenerationId)).toBe('g1');
		goBack();
		expect(get(selectedSongId)).toBeNull();
		expect(get(selectedGenerationId)).toBeNull();
		cleanup();
	});

	it('does not render a settings content back beside the shell', async () => {
		const target = document.createElement('div');
		document.body.append(target);
		const children = createRawSnippet(() => ({
			render: () => `<div></div>`
		}));
		mounted.push(mount(SettingsLayout, { target, props: { children } }));
		await tick();
		expect(target.querySelector('.back-link')).toBeNull();
		expect(target.querySelector('.back-btn')).toBeNull();
	});
});

describe('song editor survives list revalidation', () => {
	it('keeps unsaved lyrics when the open song object is replaced', async () => {
		selectedGenerationId.set(null);
		await renderView((target) => mount(SongDetailView, { target }));
		const { setDraftLyrics, editLyrics, isDirty } = await import('$lib/stores/editor');
		setDraftLyrics('unsaved verse');
		expect(get(isDirty)).toBe(true);
		songList.set([
			song({
				lyrics: '',
				generation_count: 2,
				generations: [generation(), generation({ id: 'g2' })]
			})
		]);
		await tick();
		await tick();
		expect(get(editLyrics)).toBe('unsaved verse');
		expect(get(isDirty)).toBe(true);
	});

	it('reloads the editor when a different song is selected', async () => {
		selectedGenerationId.set(null);
		await renderView((target) => mount(SongDetailView, { target }));
		const { setDraftLyrics, editLyrics } = await import('$lib/stores/editor');
		setDraftLyrics('unsaved verse');
		songList.set([
			song(),
			song({ id: 's2', lyrics: 'other lyrics', generation_count: 0, generations: [] })
		]);
		selectedSongId.set('s2');
		await tick();
		await tick();
		expect(get(editLyrics)).toBe('other lyrics');
	});
});
