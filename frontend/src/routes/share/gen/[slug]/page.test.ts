import { mount, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$app/state', () => ({ page: { params: { slug: 'shared-gen' } } }));

import Page from './+page.svelte';

class FakeAudio {
	paused = true;
	currentTime = 0;
	duration = 20;
	readyState = 1;
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
	audio = new FakeAudio();
	vi.stubGlobal('fetch', mockFetch);
	vi.stubGlobal(
		'Audio',
		vi.fn(() => audio)
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

describe('shared generation (take) page', () => {
	it('renders a one-track collection for a shared take without exposing the internal take number', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			status: 200,
			json: async () => ({
				title: 'Solo Track',
				artist: 'Artist',
				album_title: 'Album',
				generation_number: 3,
				seed: 42,
				audio_url: '/audio/take3.mp3'
			})
		});
		const target = document.createElement('div');
		document.body.appendChild(target);
		component = mount(Page, { target });

		await vi.waitFor(() => expect(target.querySelectorAll('.track-row')).toHaveLength(1));
		expect(target.textContent).toContain('Artist · Album');
		expect(target.textContent).not.toContain('take 3');

		target.querySelector<HTMLButtonElement>('.track-row')?.click();
		await vi.waitFor(() => expect(target.querySelector('.player-bar')).not.toBeNull());
		expect(audio.src).toBe('/audio/take3.mp3');
	});

	it('shows the error status when the fetch fails', async () => {
		mockFetch.mockResolvedValueOnce({ ok: false, status: 500 });
		const target = document.createElement('div');
		document.body.appendChild(target);
		component = mount(Page, { target });

		await vi.waitFor(() => {
			expect(target.querySelector('h1')?.textContent).toBe('Could not load this generation');
		});
	});
});
