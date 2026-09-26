import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';

import { RAIL_PLAYING_MARKER_LABEL } from '$lib/constants';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import { findElementByRoleAndName } from './shell/rail-test-fixtures';
import PlayingMark from './PlayingMark.svelte';

type PlayerStatus = typeof audioPlayer.status;

let mounted: ReturnType<typeof mount> | undefined;

async function render(current: boolean): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(PlayingMark, { target, props: { current } });
	await tick();
	return target;
}

afterEach(() => {
	if (mounted) unmount(mounted);
	mounted = undefined;
	document.body.innerHTML = '';
	audioPlayer.status = 'idle';
});

describe('PlayingMark', () => {
	it.each<[string, boolean, PlayerStatus, boolean]>([
		['shows on the current row while its sound plays', true, 'playing', true],
		['hides on the current row while it is paused', true, 'paused', false],
		['hides on the current row while it is still loading', true, 'loading', false],
		['hides on any other row even while sound plays', false, 'playing', false]
	])('%s', async (_name, current, status, shown) => {
		audioPlayer.status = status;

		const target = await render(current);

		expect(findElementByRoleAndName(target, 'img', RAIL_PLAYING_MARKER_LABEL) !== null).toBe(shown);
	});
});
