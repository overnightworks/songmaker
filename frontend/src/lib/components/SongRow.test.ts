import { mount, tick, unmount, type ComponentProps } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { PLAYING_MARK_LABEL, songEditorOpenLabel } from '#lib/constants.ts';
import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import { accessibleName } from '#lib/test-utils/accessible-name.ts';
import { clearComponentStyles, injectComponentStyles } from '#lib/test-utils/component-styles.ts';
import SongRow from './SongRow.svelte';
import songRowSource from './SongRow.svelte?raw';
import { findElementByRoleAndName } from './shell/rail-test-fixtures';

const mounted: Array<ReturnType<typeof mount>> = [];

async function renderRow(
	props: Partial<ComponentProps<typeof SongRow>> = {}
): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(
		mount(SongRow, {
			target,
			props: { title: 'Quiet Wind', meta: '1 take', current: false, onclick: vi.fn(), ...props }
		})
	);
	await tick();
	const row = target.querySelector<HTMLElement>('.song-row');
	if (!row) throw new Error('Expected the song box to be rendered');
	return row;
}

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	clearComponentStyles();
	audioPlayer.status = 'idle';
});

describe('SongRow', () => {
	it.each([
		{
			surface: 'the app',
			onedit: vi.fn(),
			names: ['Quiet Wind 1 take', songEditorOpenLabel('Quiet Wind')]
		},
		{ surface: 'a share page', onedit: undefined, names: ['Quiet Wind 1 take'] }
	])('gives the box a ✎ only where $surface passes one', async ({ onedit, names }) => {
		const row = await renderRow({ onedit });

		expect(
			[...row.querySelectorAll('button')].map((button) =>
				accessibleName(button).replace(/\s+/g, ' ').trim()
			)
		).toEqual(names);
	});

	it('turns the box violet with the playing mark while its song plays (#1354 rule 22)', async () => {
		audioPlayer.status = 'playing';
		const row = await renderRow({ current: true });
		injectComponentStyles(songRowSource, 'SongRow.svelte', row);

		// jsdom drops a var() border colour, so the title's colour stands for the
		// box's here; the real-browser drive reads the border itself.
		const title = row.querySelector('.song-row-title');
		if (!title) throw new Error('Expected the song title');
		expect(getComputedStyle(title).color).toBe('var(--accent)');
		expect(findElementByRoleAndName(row, 'img', PLAYING_MARK_LABEL)).not.toBeNull();
	});
});
