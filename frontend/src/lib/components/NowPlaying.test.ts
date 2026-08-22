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
	queueContext,
	setShuffle,
	shuffleEnabled,
	songList
} from '$lib/stores/player';
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
	document.body.replaceChildren();
	document.documentElement.dataset.pointer = '';
	songList.set([]);
	albumList.set([]);
	queueContext.set({ type: 'library' });
	selectedPlaylistDetail.set(null);
	setShuffle(false);
	setLibraryTakePool('picks');
	libraryQueueSkipped.set([]);
});

async function renderSurface(
	playback: PlaybackInfo,
	handlers: {
		onclose?: ReturnType<typeof vi.fn>;
		onGoToSong?: ReturnType<typeof vi.fn>;
		canPrev?: boolean;
		canNext?: boolean;
		onprev?: ReturnType<typeof vi.fn>;
		onnext?: ReturnType<typeof vi.fn>;
	} = {}
) {
	target = document.createElement('div');
	document.body.append(target);
	const onclose = handlers.onclose ?? vi.fn();
	const onGoToSong = handlers.onGoToSong ?? vi.fn();
	mounted = mount(NowPlaying, {
		target,
		props: {
			info: playback,
			onclose,
			onGoToSong,
			canPrev: handlers.canPrev,
			canNext: handlers.canNext,
			onprev: handlers.onprev,
			onnext: handlers.onnext
		}
	});
	await tick();
	return { onclose, onGoToSong };
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

	it('closes on Escape and the close button', async () => {
		const handlers = await renderSurface(info());
		window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
		expect(handlers.onclose).toHaveBeenCalledOnce();

		target.querySelector<HTMLButtonElement>(`button[aria-label="${NOW_PLAYING_CLOSE}"]`)?.click();
		expect(handlers.onclose).toHaveBeenCalledTimes(2);
	});

	it('goes to the playing song', async () => {
		const handlers = await renderSurface(info());
		const go = Array.from(target.querySelectorAll('button')).find(
			(button) => button.textContent === NOW_PLAYING_GO_TO_SONG
		);
		go?.click();
		expect(handlers.onGoToSong).toHaveBeenCalledOnce();
	});

	it('wires Previous and Next to the given handlers, respecting can-navigate flags', async () => {
		const onprev = vi.fn();
		const onnext = vi.fn();
		await renderSurface(info(), { canPrev: false, canNext: true, onprev, onnext });

		const previous = target.querySelector<HTMLButtonElement>('button[aria-label="Previous song"]');
		const next = target.querySelector<HTMLButtonElement>('button[aria-label="Next song"]');
		expect(previous?.disabled).toBe(true);
		expect(next?.disabled).toBe(false);
		next?.click();
		expect(onnext).toHaveBeenCalledOnce();
		expect(onprev).not.toHaveBeenCalled();
	});

	it('omits Previous and Next when no handlers are given', async () => {
		await renderSurface(info());
		expect(target.querySelector('button[aria-label="Previous song"]')).toBeNull();
		expect(target.querySelector('button[aria-label="Next song"]')).toBeNull();
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

	it('hides the trio and names the playlist for a playlist queue context', async () => {
		selectedPlaylistDetail.set({
			id: 'p1',
			title: 'Night Drive',
			entry_count: 0,
			is_shared: false,
			created_at: '',
			entries: []
		});
		queueContext.set({ type: 'playlist', entries: [], index: 0 });
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
		const handlers = await renderSurface(info());

		target.querySelector<HTMLButtonElement>('.mobile-panel-trigger')?.click();
		await tick();
		expect(target.querySelector('.mobile-sheet')).not.toBeNull();

		window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
		await tick();
		expect(target.querySelector('.mobile-sheet')).toBeNull();
		expect(handlers.onclose).not.toHaveBeenCalled();
	});
});
