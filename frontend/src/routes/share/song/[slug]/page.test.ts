import { mount, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { APP_NAME, SEEK_PLAYBACK_LABEL, TRANSPORT_PLAY_LABEL } from '#lib/constants.ts';
import { NOW_PLAYING_PLAY_AGAIN_LABEL } from '#lib/constants/now-playing.ts';
import { SHARE_NO_AUDIO_NOTICE } from '#lib/constants/share.ts';
import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import { getByRoleButton } from '#lib/test-utils/accessible-name.ts';

vi.mock('$app/state', () => ({ page: { params: { slug: 'shared-song' } } }));

import Page from './+page.svelte';

class FakeAudio {
	paused = true;
	currentTime = 0;
	duration = 20;
	readyState = 1;
	buffered = { length: 0, end: () => 0 };
	src = '';
	preload = '';
	crossOrigin: string | null = null;
	private listeners = new Map<string, Array<(event: Event) => void>>();

	addEventListener(name: string, listener: (event: Event) => void) {
		this.listeners.set(name, [...(this.listeners.get(name) ?? []), listener]);
	}
	removeAttribute() {}
	load() {
		this.fire('loadstart');
	}
	play() {
		this.paused = false;
		this.fire('play');
		return Promise.resolve();
	}
	pause() {
		this.paused = true;
		this.fire('pause');
	}
	fire(name: string) {
		for (const listener of this.listeners.get(name) ?? []) listener({ type: name } as Event);
	}
}

const mockFetch = vi.fn();
let component: ReturnType<typeof mount> | undefined;
let audio: FakeAudio;

beforeEach(() => {
	audioPlayer.destroy();
	audio = new FakeAudio();
	vi.stubGlobal('fetch', mockFetch);
	vi.stubGlobal(
		'Audio',
		vi.fn(function () {
			return audio;
		})
	);
	vi.stubGlobal(
		'matchMedia',
		vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
	);
	vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
});

afterEach(async () => {
	if (component) await unmount(component);
	component = undefined;
	document.body.replaceChildren();
	mockFetch.mockReset();
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

const SONG_DURATION_SEC = 187;

function sharedSongPayload(media: Record<string, unknown> = {}) {
	return {
		title: 'Solo Track',
		artist: 'Artist',
		album_title: 'Album',
		audio_url: '/audio/solo.mp3',
		generation_id: 'g1',
		audio_duration: SONG_DURATION_SEC,
		lyrics: 'One line to sing',
		whisper_cues: null,
		cover: null,
		album_cover: null,
		...media
	};
}

async function openSharedSong(response: Record<string, unknown>): Promise<HTMLElement> {
	mockFetch.mockResolvedValueOnce(response);
	const target = document.createElement('div');
	document.body.appendChild(target);
	component = mount(Page, { target });
	await vi.waitFor(() => expect(target.querySelector('.share-status.loading')).toBeNull());
	return target;
}

function sharedSong(media: Record<string, unknown> = {}): Record<string, unknown> {
	return { ok: true, status: 200, json: async () => sharedSongPayload(media) };
}

function seekLine(target: HTMLElement): HTMLInputElement {
	const line = target.querySelector<HTMLInputElement>(`input[aria-label="${SEEK_PLAYBACK_LABEL}"]`);
	if (!line) throw new Error('Expected the seek line');
	return line;
}

describe('shared song page', () => {
	it('925_M2_W1: asks the server for the song at its own share address', async () => {
		await openSharedSong(sharedSong());

		expect(mockFetch.mock.calls[0][0]).toBe('/shared/song/shared-song');
	});

	it('opens as the player and plays the song from its own Play', async () => {
		const target = await openSharedSong(sharedSong());

		expect(target.querySelector('h1')?.textContent).toBe('Solo Track');
		expect(target.querySelectorAll('.track-row')).toHaveLength(0);
		getByRoleButton(target, TRANSPORT_PLAY_LABEL).click();

		await vi.waitFor(() => expect(audio.src).toBe('/audio/solo.mp3'));
		expect(document.querySelector('.player-bar')).toBeNull();
	});

	it('offers Play again at the end and keeps the slider there', async () => {
		const target = await openSharedSong(sharedSong());
		getByRoleButton(target, TRANSPORT_PLAY_LABEL).click();
		await vi.waitFor(() => expect(audio.src).toBe('/audio/solo.mp3'));
		audio.fire('playing');

		audio.fire('ended');

		const playAgain = await vi.waitFor(() =>
			getByRoleButton(target, `↻ ${NOW_PLAYING_PLAY_AGAIN_LABEL}`)
		);
		expect(Number(seekLine(target).value)).toBe(SONG_DURATION_SEC);
		expect(target.querySelector('.progress-times')?.textContent).toMatch(/3:07\s*3:07/);

		audio.paused = true;
		playAgain.click();

		await vi.waitFor(() => expect(target.querySelector('.play-again')).toBeNull());
	});

	it('shows an honest empty state when the song has no audio', async () => {
		const target = await openSharedSong(sharedSong({ audio_url: null, generation_id: null }));

		expect(target.textContent).toContain(SHARE_NO_AUDIO_NOTICE);
		expect(getByRoleButton(target, TRANSPORT_PLAY_LABEL).disabled).toBe(true);
	});

	it('says in one line that a link is no longer shared, with a way back and no player', async () => {
		const target = await openSharedSong({ ok: false, status: 404 });

		expect(target.querySelector('h1')?.textContent).toBe('Song not found');
		expect(target.textContent).toContain('This share link is invalid or was removed.');
		const wayBack = target.querySelector<HTMLAnchorElement>('.share-status a');
		expect([wayBack?.textContent, wayBack?.getAttribute('href')]).toEqual([
			`Open ${APP_NAME}`,
			'/login'
		]);
		expect(target.querySelector('.now-playing')).toBeNull();
	});
});
