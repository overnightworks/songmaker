import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

vi.mock('$lib/api/client', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/api/client')>();
	return {
		...actual,
		fetchConversations: vi.fn().mockResolvedValue([]),
		fetchConversationMessages: vi.fn().mockResolvedValue({ messages: [] }),
		startNewConversation: vi.fn(),
		deleteConversation: vi.fn(),
		fetchMemory: vi.fn().mockResolvedValue(null),
		fetchCowriterSettings: vi.fn().mockResolvedValue({ provider: 'claude', model: '' }),
		fetchVersions: vi.fn().mockResolvedValue([])
	};
});
import { editLyrics, loadSongData, setDraftLyrics } from '$lib/stores/editor';
import { nowPlayingOpen } from '$lib/stores/player';
import { setQueuePlaybackMode } from '$lib/stores/playbackSettings';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import type { GenerationItem, SongItem } from '$lib/api/types';
import WriteColumn from './WriteColumn.svelte';

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
		title: 'Test',
		album_id: 'a1',
		album_title: 'Album',
		artist: 'Artist',
		track_number: 1,
		vocal_language: 'en',
		lyrics: 'verse one',
		prompt: 'rock',
		bpm: 120,
		audio_duration: 180,
		key_scale: 'Am',
		generation_params: null,
		version_count: 1,
		generation_count: 1,
		best_scores: null,
		best_rating: null,
		generations: [generation()],
		created_at: '',
		is_shared: false,
		share_slug: null,
		...overrides
	};
}

beforeEach(() => {
	loadSongData(song());
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
});

async function render(overrides: Partial<Record<string, unknown>> = {}) {
	const target = document.createElement('div');
	document.body.append(target);
	const props = {
		song: song(),
		allSongs: [song()],
		coWriterOpen: false,
		compact: false,
		onturncompleted: vi.fn(),
		...overrides
	};
	mounted.push(mount(WriteColumn, { target, props }));
	await tick();
	await Promise.resolve();
	await tick();
	return { target, props };
}

describe('WriteColumn write mode', () => {
	it('edits Style and Lyrics against the shared editor draft', async () => {
		const { target } = await render();
		const lyrics = target.querySelector<HTMLTextAreaElement>('.lyrics-area');
		if (!lyrics) throw new Error('Expected a lyrics textarea');
		expect(lyrics.value).toBe('verse one');
		lyrics.value = 'verse two';
		lyrics.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();
		expect(get(editLyrics)).toBe('verse two');
	});
});

describe('WriteColumn Co-Writer mode', () => {
	it('shows Chat and Lyrics together on desktop with a take strip, no mobile sub-tabs', async () => {
		const { target } = await render({ coWriterOpen: true, compact: false });
		expect(target.querySelector('.cowriter-chat')).not.toBeNull();
		expect(target.querySelector('.cowriter-lyrics')).not.toBeNull();
		expect(target.querySelector('.cowriter-takes')).not.toBeNull();
		expect(target.querySelector('.mobile-subtabs')).toBeNull();
	});

	it('splits Chat | Lyrics into tabs and drops the take strip on mobile', async () => {
		setDraftLyrics('verse one');
		const { target } = await render({ coWriterOpen: true, compact: true });
		expect(target.querySelector('.mobile-subtabs')).not.toBeNull();
		expect(target.querySelector('.cowriter-chat')).not.toBeNull();
		expect(target.querySelector('.cowriter-lyrics')).toBeNull();
		expect(target.querySelector('.cowriter-takes')).toBeNull();

		const lyricsTab = Array.from(
			target.querySelectorAll<HTMLButtonElement>('.mobile-subtabs button')
		).find((el) => el.textContent === 'Lyrics');
		lyricsTab?.click();
		await tick();
		expect(target.querySelector('.cowriter-lyrics')).not.toBeNull();
		expect(target.querySelector('.cowriter-chat')).toBeNull();
	});

	it('plays a take from the strip on click without opening Now Playing', async () => {
		// Classic mode makes playTake's audioPlayer.load call synchronous and
		// deterministic — no library-pool API round trip to mock. Asserting on
		// audioPlayer (the real playback boundary) instead of a re-exported
		// player.ts function exercises TakeStrip's actual entry point,
		// playTake, rather than stubbing it out from under the click handler.
		// The spy is scoped and restored locally so it never bleeds into the
		// module-level $lib/api/client mocks the other tests in this file rely
		// on being set once at module load.
		setQueuePlaybackMode('classic');
		const loadSpy = vi.spyOn(audioPlayer, 'load').mockImplementation((info) => {
			audioPlayer.current = info;
		});
		try {
			const gen = generation({ id: 'g9' });
			const targetSong = song({ generations: [gen] });
			const { target } = await render({
				coWriterOpen: true,
				song: targetSong
			});
			target.querySelector<HTMLButtonElement>('.take-chip')?.click();
			await tick();
			await Promise.resolve();
			expect(audioPlayer.load).toHaveBeenCalledWith(
				expect.objectContaining({
					generation: expect.objectContaining({ id: gen.id }),
					songId: targetSong.id
				}),
				expect.objectContaining({ restart: true })
			);
			expect(get(nowPlayingOpen)).toBe(false);
		} finally {
			loadSpy.mockRestore();
			audioPlayer.current = null;
		}
	});
});
