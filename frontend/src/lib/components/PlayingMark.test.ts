import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';

import { PLAYING_MARK_LABEL } from '$lib/constants';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import { clearComponentStyles, injectComponentStyles } from '$lib/test-utils/component-styles';
import { findElementByRoleAndName } from './shell/rail-test-fixtures';
import PlayingMark from './PlayingMark.svelte';
import playingMarkSource from './PlayingMark.svelte?raw';

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
	clearComponentStyles();
	audioPlayer.status = 'idle';
});

function requireMark(target: HTMLElement): Element {
	const mark = findElementByRoleAndName(target, 'img', PLAYING_MARK_LABEL);
	if (!mark) throw new Error('Expected the playing mark');
	return mark;
}

function barsMove(mark: Element): boolean[] {
	injectComponentStyles(playingMarkSource, 'PlayingMark.svelte', mark);
	return Array.from(mark.children, (bar) => getComputedStyle(bar).animation !== 'none');
}

describe('PlayingMark', () => {
	it.each<[string, boolean, PlayerStatus, boolean]>([
		['shows on the current row while its sound plays', true, 'playing', true],
		['keeps showing on the current row while it is paused', true, 'paused', true],
		['hides on the current row while it is still loading', true, 'loading', false],
		['hides on any other row even while sound plays', false, 'playing', false]
	])('%s', async (_name, current, status, shown) => {
		audioPlayer.status = status;

		const target = await render(current);

		expect(findElementByRoleAndName(target, 'img', PLAYING_MARK_LABEL) !== null).toBe(shown);
	});

	it('moves while its take sounds', async () => {
		audioPlayer.status = 'playing';

		const mark = requireMark(await render(true));

		expect(barsMove(mark)).toEqual([true, true, true]);
	});

	it('stands still while its take is paused', async () => {
		audioPlayer.status = 'paused';

		const mark = requireMark(await render(true));

		expect(barsMove(mark)).toEqual([false, false, false]);
	});
});
