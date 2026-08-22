import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import type { GenerationItem } from '$lib/api/types';
import type { PlaybackInfo } from '$lib/services/playbackTypes';
import {
	NOW_PLAYING_CLOSE,
	NOW_PLAYING_GO_TO_SONG,
	NOW_PLAYING_LABEL,
	NOW_PLAYING_NO_LYRICS,
	NOW_PLAYING_TAKE_PREFIX
} from '$lib/constants';
import { libraryQueueSkipped, queueContext, setShuffle, shuffleEnabled } from '$lib/stores/player';
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

let mounted: ReturnType<typeof mount> | undefined;
let target: HTMLDivElement;

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

async function renderSheet(
	playback: PlaybackInfo,
	handlers = { onclose: vi.fn(), onGoToSong: vi.fn() }
) {
	target = document.createElement('div');
	document.body.append(target);
	mounted = mount(NowPlaying, {
		target,
		props: {
			info: playback,
			onclose: handlers.onclose,
			onGoToSong: handlers.onGoToSong
		}
	});
	await tick();
	return handlers;
}

describe('NowPlaying', () => {
	it('shows the playing take and its version lyrics, not a later draft', async () => {
		await renderSheet(info({ lyrics: 'old verse' }));
		expect(target.textContent).toContain(NOW_PLAYING_LABEL);
		expect(target.textContent).toContain('Tide');
		expect(target.textContent).toContain('Nachtstrom · Artist');
		expect(target.textContent).toContain(`${NOW_PLAYING_TAKE_PREFIX} 2`);
		expect(target.textContent).toContain('old verse');
		expect(target.textContent).not.toContain('latest draft');
	});

	it('shows a named empty state when the take has no lyrics', async () => {
		await renderSheet(info({ lyrics: null }));
		expect(target.textContent).toContain(NOW_PLAYING_NO_LYRICS);
		expect(target.querySelector('.lyrics')).toBeNull();
	});

	it('closes on Escape and outside click', async () => {
		const handlers = await renderSheet(info());
		window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
		expect(handlers.onclose).toHaveBeenCalledOnce();

		target.querySelector<HTMLButtonElement>('.sheet-backdrop')?.click();
		expect(handlers.onclose).toHaveBeenCalledTimes(2);
		target.querySelector<HTMLButtonElement>(`button[aria-label="${NOW_PLAYING_CLOSE}"]`)?.click();
		expect(handlers.onclose).toHaveBeenCalledTimes(3);
	});

	it('goes to the playing song from the sheet', async () => {
		const handlers = await renderSheet(info());
		const go = Array.from(target.querySelectorAll('button')).find(
			(button) => button.textContent === NOW_PLAYING_GO_TO_SONG
		);
		go?.click();
		expect(handlers.onGoToSong).toHaveBeenCalledOnce();
	});

	it('toggles shuffle from the overlay, scoped to the current queue', async () => {
		setShuffle(false);
		queueContext.set({ type: 'album', albumId: 'a1' });
		await renderSheet(info());
		const shuffleBtn = target.querySelector<HTMLButtonElement>('[aria-pressed]');
		expect(shuffleBtn?.getAttribute('aria-label')).toBe('Shuffle this album');
		shuffleBtn?.click();
		await tick();
		expect(get(shuffleEnabled)).toBe(true);
		expect(shuffleBtn?.getAttribute('aria-pressed')).toBe('true');
		expect(shuffleBtn?.getAttribute('aria-label')).toBe('Disable shuffle (this album)');
		setShuffle(false);
		queueContext.set({ type: 'library' });
	});

	it('shows queue skip feedback while playing the library queue', async () => {
		queueContext.set({ type: 'library' });
		libraryQueueSkipped.set([{ generation_id: 'g2', song_id: 's2', reason: 'missing_file' }]);
		await renderSheet(info());
		expect(target.querySelector('.queue-feedback')?.textContent).toContain('1');
		libraryQueueSkipped.set([]);
		queueContext.set({ type: 'library' });
	});
});
