import { makeGeneration as generation, makeSong as song } from '#lib/test-utils/factories.ts';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import { editLyrics, loadSongData } from '#lib/stores/editor.ts';
import type { SongItem } from '#lib/api/types.ts';
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
	it('hosts the closed Recipe line above Style (C4, #1935 acceptance 1)', async () => {
		const { target } = await render();
		const first = target.querySelector('.write-mode')?.firstElementChild;
		expect(first?.classList.contains('recipe-line')).toBe(true);
		expect(first?.nextElementSibling?.querySelector('textarea')).not.toBeNull();
	});

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
});
