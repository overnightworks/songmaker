import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { makeGeneration } from '$lib/test-utils/factories';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import PlayerBar from './PlayerBar.svelte';

class SilentAudio {
	paused = true;
	currentTime = 0;
	duration = 20;
	readyState = 1;
	src = '';
	buffered = { length: 0, end: () => 0 };
	addEventListener() {}
	load() {}
	play() {
		return Promise.resolve();
	}
	pause() {}
	removeAttribute() {}
}

let component: ReturnType<typeof mount> | undefined;

beforeEach(() => {
	vi.stubGlobal(
		'Audio',
		vi.fn(function () {
			return new SilentAudio();
		})
	);
	vi.stubGlobal(
		'matchMedia',
		vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
	);
	vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
});

afterEach(async () => {
	if (component) await unmount(component);
	component = undefined;
	audioPlayer.destroy();
	document.body.replaceChildren();
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

describe('1906_P5 PlayerBar', () => {
	it('1906_P5: the mini-player bar carries no AI notice while a take is loaded', async () => {
		audioPlayer.load(
			{
				generation: makeGeneration({ mp3_path: 'take.mp3' }),
				songId: 's1',
				songTitle: 'Opening Move',
				artist: 'Artist',
				albumTitle: 'Album',
				lyrics: null
			},
			{ autoplay: false }
		);
		const target = document.createElement('div');
		document.body.append(target);
		component = mount(PlayerBar, { target });
		await tick();

		expect(target.querySelector('.track-title')).toHaveTextContent('Opening Move');
		expect(target.querySelector('.ai-notice')).toBeNull();
		expect(target).not.toHaveTextContent('KI-generiert');
	});
});
