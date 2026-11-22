import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MINI_PLAYER_WITHOUT_COVER_MEDIA } from '#lib/constants/media.ts';
import { queueContext } from '#lib/stores/queue.ts';
import PlayerBar from './PlayerBar.svelte';

let component: ReturnType<typeof mount> | undefined;

afterEach(async () => {
	if (component) await unmount(component);
	component = undefined;
	document.body.replaceChildren();
	vi.unstubAllGlobals();
});

describe('idle PlayerBar', () => {
	it.each([
		{ layout: 'phone', phone: true, covers: 0 },
		{ layout: 'desktop', phone: false, covers: 1 }
	])('gives the $layout title the room an empty cover would take', async ({ phone, covers }) => {
		vi.stubGlobal(
			'matchMedia',
			vi.fn((query: string) => ({
				matches: query === MINI_PLAYER_WITHOUT_COVER_MEDIA ? false : phone,
				addEventListener: vi.fn(),
				removeEventListener: vi.fn()
			}))
		);
		vi.stubGlobal('Audio', vi.fn());
		queueContext.set({ type: 'library' });
		const target = document.body.appendChild(document.createElement('div'));
		component = mount(PlayerBar, { target });
		await tick();

		expect(target.querySelectorAll('.track-cover')).toHaveLength(covers);
	});
});
