import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { QueueStreamTrackItem } from '$lib/api/types';
import SharedPlayer from './SharedPlayer.svelte';

class FakeAudio {
	paused = true;
	currentTime = 0;
	duration = 20;
	readyState = 1;
	src = '';
	private listeners = new Map<string, Array<(event: Event) => void>>();
	addEventListener(name: string, listener: (event: Event) => void) {
		this.listeners.set(name, [...(this.listeners.get(name) ?? []), listener]);
	}
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

const tracks: QueueStreamTrackItem[] = [
	{
		key: 'a',
		index: 0,
		entry_id: null,
		generation_id: 'g1',
		song_id: 's1',
		song_title: 'One',
		artist: 'A',
		generation_number: 1,
		mp3_path: 'a.mp3',
		audio_url: '/audio/a.mp3',
		seed: null,
		model_mode: 'sft',
		duration: 10,
		start_offset: 0,
		end_offset: 10
	},
	{
		key: 'b',
		index: 1,
		entry_id: null,
		generation_id: 'g2',
		song_id: 's2',
		song_title: 'Two',
		artist: 'A',
		generation_number: 1,
		mp3_path: 'b.mp3',
		audio_url: '/audio/b.mp3',
		seed: null,
		model_mode: 'sft',
		duration: 10,
		start_offset: 10,
		end_offset: 20
	}
];

let target: HTMLDivElement;
let component: ReturnType<typeof mount> & { loadAndPlay: (url: string, options: unknown) => void };
let audio: FakeAudio;

beforeEach(() => {
	target = document.createElement('div');
	document.body.appendChild(target);
	audio = new FakeAudio();
	vi.stubGlobal(
		'Audio',
		vi.fn(() => audio)
	);
	vi.stubGlobal(
		'matchMedia',
		vi.fn(() => ({ matches: true }))
	);
	vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
});

afterEach(async () => {
	if (component) await unmount(component);
	document.body.replaceChildren();
	vi.unstubAllGlobals();
});

describe('SharedPlayer stream windows', () => {
	it('ends a windowed stream once without calling the route callback and resets on reload', async () => {
		const onended = vi.fn();
		component = mount(SharedPlayer, {
			target,
			props: {
				audioUrl: '/stream.mp3',
				title: 'One',
				streamTracks: tracks,
				streamWindowed: true,
				startIndex: 1,
				autoplay: true,
				onended,
				onnext: vi.fn()
			}
		}) as typeof component;
		await tick();
		audio.fire('ended');
		audio.fire('ended');
		await tick();
		expect(onended).not.toHaveBeenCalled();
		expect(target.textContent).toContain('Weitere Takes nicht geladen');
		expect(target.querySelector('button[aria-label="Next"]')?.hasAttribute('disabled')).toBe(true);
		await audio.play();
		await tick();
		expect(target.textContent).not.toContain('Weitere Takes nicht geladen');
		audio.fire('ended');
		await tick();
		expect(onended).not.toHaveBeenCalled();
		expect(target.textContent).toContain('Weitere Takes nicht geladen');

		component.loadAndPlay('/stream.mp3', {
			startIndex: 0,
			streamTracks: tracks,
			streamWindowed: false
		});
		await tick();
		expect(target.textContent).not.toContain('Weitere Takes nicht geladen');
		audio.fire('ended');
		expect(onended).toHaveBeenCalledOnce();
	});
});
