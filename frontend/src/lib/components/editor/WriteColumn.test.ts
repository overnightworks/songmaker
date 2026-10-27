import { makeGeneration as generation, makeSong as song } from '$lib/test-utils/factories';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import { editLyrics, loadSongData } from '$lib/stores/editor';
import { EDITOR_VIEW_COWRITER_LABEL } from '$lib/constants';
import type { SongItem } from '$lib/api/types';
import WriteColumn from './WriteColumn.svelte';

function draftSongDefaults(): Partial<SongItem> {
	return {
		slug: 'test',
		title: 'Test',
		lyrics: 'verse one',
		prompt: 'rock',
		generations: [generation()],
		created_at: ''
	};
}

const mounted: Array<ReturnType<typeof mount>> = [];

beforeEach(() => {
	loadSongData(song(draftSongDefaults()));
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
});

async function render() {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(WriteColumn, { target, props: { song: song(draftSongDefaults()) } }));
	await tick();
	await Promise.resolve();
	await tick();
	return { target };
}

describe('WriteColumn write mode', () => {
	it('edits Style and Lyrics against the shared editor draft', async () => {
		const { target } = await render();
		const lyrics = target.querySelector<HTMLTextAreaElement>('.lyrics-area');
		if (!lyrics) throw new Error('Expected a lyrics textarea');
		expect(lyrics.value).toBe('verse one');
		lyrics.value = 'verse two';
		lyrics.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();
		expect(get(editLyrics)).toBe('verse two');
	});

	it('leaves the co-writer to its own tab', async () => {
		const { target } = await render();
		const buttonTexts = Array.from(target.querySelectorAll('button'), (b) => b.textContent);
		expect(buttonTexts.some((text) => text?.includes(EDITOR_VIEW_COWRITER_LABEL))).toBe(false);
	});

	it('leaves takes to the Takes tab', async () => {
		const { target } = await render();
		expect(target.querySelector('.take-row')).toBeNull();
	});
});
