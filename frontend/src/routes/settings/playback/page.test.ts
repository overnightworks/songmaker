import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';

import PlaybackSettingsPage from './+page.svelte';

let mounted: ReturnType<typeof mount> | undefined;

afterEach(() => {
	if (mounted) unmount(mounted);
	mounted = undefined;
	document.body.innerHTML = '';
});

describe('Settings › Playback', () => {
	it('offers no stream/classic queue choice', async () => {
		const target = document.createElement('div');
		document.body.append(target);
		mounted = mount(PlaybackSettingsPage, { target });
		await tick();

		expect(target.querySelector('h1')?.textContent).toBe('Playback');
		expect(target.querySelector('[role="radiogroup"], [role="radio"], button, input')).toBeNull();
	});
});
