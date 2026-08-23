import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import type { AlbumItem, GenerationItem, SongItem } from '$lib/api/types';
import type { PlaybackInfo } from '$lib/services/playbackTypes';
import {
	NOW_PLAYING_CLOSE,
	NOW_PLAYING_GO_TO_SONG,
	NOW_PLAYING_LABEL,
	NOW_PLAYING_NO_LYRICS,
	NOW_PLAYING_TAKE_PREFIX
} from '$lib/constants';
import {
	albumList,
	libraryQueueSkipped,
	nowPlayingDockable,
	nowPlayingPanel,
	nowPlayingSurface,
	queueContext,
	setShuffle,
	shuffleEnabled,
	songList
} from '$lib/stores/player';
import * as playerStore from '$lib/stores/player';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import { setLibraryTakePool } from '$lib/stores/playbackSettings';
import { selectedPlaylistDetail } from '$lib/stores/playlists';
import NowPlaying from './NowPlaying.svelte';

function generation(overrides: Partial<GenerationItem> = {}): GenerationItem {
	return {
		id: 'g1',
		song_id: 's1',
		version_id: 'v1',
		version_number: 1,
		generation_number: 2,
		mp3_path: 'a.mp3',
		wav_path: null,
		seed: 1,
		status: 'completed',
		is_archived: false,
		is_picked: false,
		is_kept: false,
		is_shared: false,
		model_mode: 'sft',
		whisper_text: null,
		whisper_cues: null,
		version_lyrics: 'old verse',
		scores: null,
		generation_params: null,
		created_at: '',
		...overrides
	};
}

function song(overrides: Partial<SongItem> = {}): SongItem {
	const gen = generation();
	return {
		id: 's1',
		title: 'Tide',
		album_id: 'a1',
		album_title: 'Nachtstrom',
		artist: 'Artist',
		track_number: 1,
		vocal_language: 'en',
		lyrics: 'old verse',
		prompt: 'dreamy',
		version_count: 1,
		generation_count: 1,
		is_shared: false,
		created_at: '',
		generations: [gen],
		...overrides
	};
}

function info(overrides: Partial<PlaybackInfo> = {}): PlaybackInfo {
	return {
		generation: generation(),
		songId: 's1',
		songTitle: 'Tide',
		artist: 'Artist',
		albumTitle: 'Nachtstrom',
		lyrics: 'old verse',
		...overrides
	};
}

function album(overrides: Partial<AlbumItem> = {}): AlbumItem {
	return {
		id: 'a1',
		title: 'Nachtstrom',
		artist: 'Artist',
		subtitle: '',
		year: '',
		colors: {},
		song_count: 1,
		picked_count: 0,
		is_shared: false,
		created_at: '',
		...overrides
	};
}

let mounted: ReturnType<typeof mount> | undefined;
let target: HTMLDivElement;

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	vi.restoreAllMocks();
	document.body.replaceChildren();
	document.documentElement.dataset.pointer = '';
	audioPlayer.current = null;
	nowPlayingSurface.set('closed');
	nowPlayingDockable.set(false);
	songList.set([]);
	albumList.set([]);
	queueContext.set({ type: 'library' });
	selectedPlaylistDetail.set(null);
	setShuffle(false);
	setLibraryTakePool('picks');
	libraryQueueSkipped.set([]);
	nowPlayingPanel.set('queue');
});

// The surface reads what is playing and what the queue allows from the player
// store, so a test arranges playback rather than handing it callbacks.
async function renderSurface(playback: PlaybackInfo) {
	audioPlayer.current = playback;
	nowPlayingSurface.set('full');
	target = document.createElement('div');
	document.body.append(target);
	mounted = mount(NowPlaying, { target, props: { info: playback } });
	await tick();
}

describe('NowPlaying', () => {
	it('shows the playing take and its version lyrics, not a later draft', async () => {
		songList.set([song()]);
		await renderSurface(info({ lyrics: 'old verse' }));
		expect(target.textContent).toContain(NOW_PLAYING_LABEL);
		expect(target.textContent).toContain('Tide');
		expect(target.textContent).toContain('Nachtstrom · Artist');
		expect(target.textContent).toContain(`${NOW_PLAYING_TAKE_PREFIX} 2`);
		expect(target.textContent).toContain('old verse');
		expect(target.textContent).not.toContain('latest draft');
	});

	it('shows a named empty state when the take has no lyrics', async () => {
		await renderSurface(info({ lyrics: null }));
		expect(target.textContent).toContain(NOW_PLAYING_NO_LYRICS);
		expect(target.querySelector('.lyrics')).toBeNull();
	});

	it('follows the lyrics with the resolved take once whisper_cues are loaded (#45)', async () => {
		const gen = generation({
			version_lyrics: 'old verse',
			whisper_cues: [{ start: 0, end: 1, text: 'old verse' }]
		});
		songList.set([song({ generations: [gen] })]);
		await renderSurface(info({ lyrics: 'old verse', generation: gen }));

		expect(target.querySelectorAll('.lyrics-line')).toHaveLength(1);
	});

	it('stays static for a thin library-pool item until its song resolves whisper_cues', async () => {
		// info.generation mirrors what a library-pool click builds before
		// ensureGenerationsLoaded resolves it against songList — whisper_cues
		// stubbed null, songList not yet carrying the real generation.
		await renderSurface(info({ lyrics: 'old verse' }));

		expect(target.querySelector('.lyrics-line')).toBeNull();
		expect(target.querySelector('.lyrics')?.textContent).toContain('old verse');
	});

	it('closes on the close button', async () => {
		await renderSurface(info());

		target.querySelector<HTMLButtonElement>(`button[aria-label="${NOW_PLAYING_CLOSE}"]`)?.click();

		expect(get(nowPlayingSurface)).toBe('closed');
	});

	it('closes on Escape where no docked panel fits', async () => {
		await renderSurface(info());

		window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));

		expect(get(nowPlayingSurface)).toBe('closed');
	});

	it('steps back to the docked panel on Escape where one fits', async () => {
		nowPlayingDockable.set(true);
		await renderSurface(info());

		window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));

		expect(get(nowPlayingSurface)).toBe('docked');
	});

	it('goes to the playing song and leaves Now Playing behind', async () => {
		const navigate = vi.spyOn(playerStore, 'navigateToPlaying').mockResolvedValue();
		await renderSurface(info());

		const go = Array.from(target.querySelectorAll('button')).find(
			(button) => button.textContent === NOW_PLAYING_GO_TO_SONG
		);
		go?.click();

		expect(navigate).toHaveBeenCalledOnce();
		expect(get(nowPlayingSurface)).toBe('closed');
	});

	it('offers Previous and Next only as far as the playing queue reaches', async () => {
		const next = vi.spyOn(playerStore, 'playNextSong').mockResolvedValue();
		albumList.set([album()]);
		songList.set([song()]);
		queueContext.set({ type: 'album', albumId: 'a1' });
		await renderSurface(info());
		expect(
			target.querySelector<HTMLButtonElement>('button[aria-label="Next song"]')?.disabled
		).toBe(true);

		songList.set([song(), song({ id: 's2', title: 'Second' })]);
		await tick();

		const nextButton = target.querySelector<HTMLButtonElement>('button[aria-label="Next song"]');
		expect(nextButton?.disabled).toBe(false);
		nextButton?.click();
		expect(next).toHaveBeenCalledOnce();
	});

	it('toggles shuffle from the overlay, scoped to the current queue', async () => {
		setShuffle(false);
		queueContext.set({ type: 'album', albumId: 'a1' });
		await renderSurface(info());
		const shuffleBtn = target.querySelector<HTMLButtonElement>('[aria-pressed]');
		expect(shuffleBtn?.getAttribute('aria-label')).toBe('Shuffle this album');
		shuffleBtn?.click();
		await tick();
		expect(get(shuffleEnabled)).toBe(true);
		expect(shuffleBtn?.getAttribute('aria-pressed')).toBe('true');
		expect(shuffleBtn?.getAttribute('aria-label')).toBe('Disable shuffle (this album)');
	});

	it('shows queue skip feedback while playing the library queue', async () => {
		queueContext.set({ type: 'library' });
		libraryQueueSkipped.set([{ generation_id: 'g2', song_id: 's2', reason: 'missing_file' }]);
		await renderSurface(info());
		expect(target.querySelector('.queue-feedback')?.textContent).toContain('1');
	});

	it('shows the pool trio only for a library queue context', async () => {
		queueContext.set({ type: 'library' });
		await renderSurface(info());
		expect(target.querySelectorAll('.pool-pill')).toHaveLength(3);
	});

	it('hides the trio and names the album for an album queue context', async () => {
		albumList.set([album()]);
		queueContext.set({ type: 'album', albumId: 'a1' });
		await renderSurface(info());
		expect(target.querySelectorAll('.pool-pill')).toHaveLength(0);
		expect(target.querySelector('.queue-heading')?.textContent).toBe('Queue · Nachtstrom');
	});

	it('names the playlist the queue was built from, not the one the listener has open', async () => {
		selectedPlaylistDetail.set({
			id: 'p2',
			title: 'Morning Ride',
			entry_count: 0,
			is_shared: false,
			created_at: '',
			entries: []
		});
		queueContext.set({
			type: 'playlist',
			playlist: { id: 'p1', title: 'Night Drive' },
			entries: [],
			index: 0
		});
		await renderSurface(info());
		expect(target.querySelectorAll('.pool-pill')).toHaveLength(0);
		expect(target.querySelector('.queue-heading')?.textContent).toBe('Queue · Night Drive');
	});

	it('toggles between Queue and This take', async () => {
		songList.set([song()]);
		await renderSurface(info());
		const tabs = target.querySelectorAll<HTMLButtonElement>('[role="tab"]');
		expect(tabs).toHaveLength(2);
		expect(tabs[0]?.getAttribute('aria-selected')).toBe('true');
		expect(target.querySelector('.np-queue')).not.toBeNull();

		tabs[1]?.click();
		await tick();
		expect(tabs[1]?.getAttribute('aria-selected')).toBe('true');
		expect(target.querySelector('.np-queue')).toBeNull();
		expect(target.querySelector('.np-take')).not.toBeNull();
	});

	it('opens straight to the judging panel when a take row requested it', async () => {
		songList.set([song()]);
		nowPlayingPanel.set('take');
		await renderSurface(info());
		const tabs = target.querySelectorAll<HTMLButtonElement>('[role="tab"]');
		expect(tabs[1]?.getAttribute('aria-selected')).toBe('true');
		expect(target.querySelector('.np-take')).not.toBeNull();
		expect(target.querySelector('.np-queue')).toBeNull();
	});

	it('wires the panel tabs to their panel via aria-controls/role=tabpanel', async () => {
		songList.set([song()]);
		await renderSurface(info());
		const tabs = target.querySelectorAll<HTMLButtonElement>('[role="tab"]');
		const panel = target.querySelector('[role="tabpanel"]');
		expect(panel).not.toBeNull();
		for (const tab of tabs) {
			expect(tab.getAttribute('aria-controls')).toBe(panel?.id);
		}
		expect(panel?.getAttribute('aria-labelledby')).toBe(tabs[0]?.id);
	});

	it('moves the panel tab selection and focus with the arrow keys', async () => {
		songList.set([song()]);
		await renderSurface(info());
		const tabs = target.querySelectorAll<HTMLButtonElement>('[role="tab"]');
		tabs[0]?.focus();

		tabs[0]?.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
		await tick();
		expect(tabs[1]?.getAttribute('aria-selected')).toBe('true');
		expect(document.activeElement).toBe(tabs[1]);

		tabs[1]?.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
		await tick();
		expect(tabs[0]?.getAttribute('aria-selected')).toBe('true');
		expect(document.activeElement).toBe(tabs[0]);
	});

	it('the take panel stays absent while the generation is not yet loaded', async () => {
		songList.set([]);
		await renderSurface(info());
		const tabs = target.querySelectorAll<HTMLButtonElement>('[role="tab"]');
		tabs[1]?.click();
		await tick();
		expect(target.querySelector('.np-take')).toBeNull();
	});

	it('renders current-only, no up next, for a classic queue whose native takes have not built yet', async () => {
		queueContext.set({ type: 'library' });
		await renderSurface(info());
		const rows = target.querySelectorAll('.queue-row');
		expect(rows).toHaveLength(1);
		expect(rows[0]?.textContent).toContain('Tide');
		expect(target.textContent).not.toContain('Up next');
	});

	it('stacks into a single column and opens the panel as a sheet on a narrow/coarse layout', async () => {
		document.documentElement.dataset.pointer = 'coarse';
		await renderSurface(info());
		expect(target.querySelector('.np-right-col')).toBeNull();
		expect(target.querySelector('.mobile-sheet')).toBeNull();

		target.querySelector<HTMLButtonElement>('.mobile-panel-trigger')?.click();
		await tick();
		expect(target.querySelector('.mobile-sheet')).not.toBeNull();

		target.querySelector<HTMLButtonElement>('.mobile-sheet-backdrop')?.click();
		await tick();
		expect(target.querySelector('.mobile-sheet')).toBeNull();
	});

	it('labels the stacked trigger Queue and keeps the sheet closed when the queue panel is requested', async () => {
		document.documentElement.dataset.pointer = 'coarse';
		await renderSurface(info());
		expect(target.querySelector('.mobile-sheet')).toBeNull();
		expect(target.querySelector('.mobile-panel-trigger')?.textContent).toContain('Queue');
	});

	it('seeds the sheet open from a take-row request on a stacked layout, never labelling the trigger Queue', async () => {
		document.documentElement.dataset.pointer = 'coarse';
		songList.set([song()]);
		nowPlayingPanel.set('take');
		await renderSurface(info());

		expect(target.querySelector('.mobile-sheet')).not.toBeNull();
		expect(target.querySelector('.np-take')).not.toBeNull();
		const triggerText = target.querySelector('.mobile-panel-trigger')?.textContent ?? '';
		expect(triggerText).toContain('This take');
		expect(triggerText).not.toContain('Queue');
	});

	it('moves focus into the mobile sheet when it opens', async () => {
		document.documentElement.dataset.pointer = 'coarse';
		songList.set([song()]);
		await renderSurface(info());

		target.querySelector<HTMLButtonElement>('.mobile-panel-trigger')?.click();
		await tick();
		await tick();

		const sheet = target.querySelector('.mobile-sheet');
		expect(sheet?.contains(document.activeElement)).toBe(true);
	});

	it('scopes the mobile sheet focus trap to the sheet, not the whole surface, on Escape', async () => {
		document.documentElement.dataset.pointer = 'coarse';
		await renderSurface(info());

		target.querySelector<HTMLButtonElement>('.mobile-panel-trigger')?.click();
		await tick();
		expect(target.querySelector('.mobile-sheet')).not.toBeNull();

		window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
		await tick();
		expect(target.querySelector('.mobile-sheet')).toBeNull();
		expect(get(nowPlayingSurface)).toBe('full');
	});
});
