import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { WhisperCue } from '#lib/api/types.ts';
import { TRANSPORT_PLAY_LABEL } from '#lib/constants.ts';
import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import { getByRoleButton } from '#lib/test-utils/accessible-name.ts';

vi.mock('$app/state', () => ({ page: { params: { slug: 'shared-gen' } } }));

import Page from './+page.svelte';

const FIRST_LINE = 'the lantern hums quietly tonight';
const SECOND_LINE = 'we count the fading city lights';
const TAKE_DURATION_SEC = 187;

// One segment per lyric line, carrying a word every second, as a take scored
// with word timestamps delivers them.
function sungCue(start: number, text: string): WhisperCue {
	const words = text.split(' ').map((word, index) => ({
		start: start + index,
		end: start + index + 1,
		text: word
	}));
	return { start: words[0].start, end: words[words.length - 1].end, text, words };
}

function sharedTakePayload(media: Record<string, unknown> = {}) {
	return {
		title: 'Solo Track',
		artist: 'Artist',
		album_title: 'Album',
		generation_number: 3,
		audio_url: '/audio/take3.mp3',
		generation_id: 'g3',
		audio_duration: TAKE_DURATION_SEC,
		lyrics: null,
		whisper_cues: null,
		...media
	};
}

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

async function openSharedTake(response: Record<string, unknown>): Promise<HTMLElement> {
	mockFetch.mockResolvedValueOnce(response);
	const target = document.createElement('div');
	document.body.appendChild(target);
	component = mount(Page, { target });
	await vi.waitFor(() => expect(target.querySelector('.share-status.loading')).toBeNull());
	return target;
}

function sharedTake(media: Record<string, unknown> = {}): Record<string, unknown> {
	return { ok: true, status: 200, json: async () => sharedTakePayload(media) };
}

describe('shared generation (take) page', () => {
	it('925_M2_W1: asks the server for the take at its own share address', async () => {
		await openSharedTake(sharedTake());

		expect(mockFetch.mock.calls[0][0]).toBe('/shared/gen/shared-gen');
	});

	it('opens as the player for a shared take without exposing the internal take number', async () => {
		const target = await openSharedTake(sharedTake());

		expect(target.querySelector('h1')?.textContent).toBe('Solo Track');
		expect(target.textContent).toContain('Album · Artist');
		expect(target.textContent).not.toContain('take 3');
		// #141/10: the page names a take; only the URL segment stays /share/gen/.
		expect(document.title).toContain('Take 3 — Solo Track');
		expect(document.title).not.toContain('Gen #');

		getByRoleButton(target, TRANSPORT_PLAY_LABEL).click();
		await vi.waitFor(() => expect(audio.src).toBe('/audio/take3.mp3'));
		expect(document.querySelector('.player-bar')).toBeNull();
	});

	it('shows the take duration from the payload, with no stream manifest in play', async () => {
		const target = await openSharedTake(sharedTake());

		expect(target.querySelector('.progress-times')?.textContent).toContain('3:07');
		expect(mockFetch).toHaveBeenCalledTimes(1);
	});

	it('follows the sung words under the player from the cues the payload carries', async () => {
		const target = await openSharedTake(
			sharedTake({
				lyrics: `${FIRST_LINE}\n${SECOND_LINE}`,
				whisper_cues: [sungCue(0, FIRST_LINE), sungCue(6, SECOND_LINE)]
			})
		);
		getByRoleButton(target, TRANSPORT_PLAY_LABEL).click();
		await vi.waitFor(() => expect(target.querySelector('.lyrics-synced')).not.toBeNull());

		audioPlayer.currentTime = 8.5;
		await tick();

		const active = [...target.querySelectorAll('.lyrics-line.active')].map((el) =>
			el.textContent?.trim()
		);
		expect(active).toEqual([SECOND_LINE]);
	});

	it('defect:#1374 says in one line that a take is no longer shared, with a way back and no player', async () => {
		const target = await openSharedTake({ ok: false, status: 404 });

		expect(target.querySelector('h1')?.textContent).toBe('Take not found');
		expect(target.querySelector('.share-status a')?.getAttribute('href')).toBe('/login');
		expect(target.querySelector('.now-playing')).toBeNull();
	});

	it('shows the error status when the fetch fails', async () => {
		const target = await openSharedTake({ ok: false, status: 500 });

		expect(target.querySelector('h1')?.textContent).toBe('Could not load this take');
	});
});
