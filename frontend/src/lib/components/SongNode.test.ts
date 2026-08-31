import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { SongItem } from '$lib/api/types';

vi.mock('$lib/stores/navigation', () => ({ selectSong: vi.fn() }));

import { selectSong } from '$lib/stores/navigation';
import SongNode from './SongNode.svelte';

let mounted: ReturnType<typeof mount> | undefined;

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	vi.mocked(selectSong).mockClear();
});

function song(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's1',
		slug: 'sommerlicht',
		title: 'Sommerlicht',
		album_id: 'a1',
		album_title: 'Album',
		artist: 'Artist',
		track_number: 1,
		vocal_language: 'de',
		lyrics: '',
		prompt: '',
		bpm: 108,
		audio_duration: 195,
		key_scale: 'A major',
		generation_params: null,
		version_count: 1,
		generation_count: 2,
		best_scores: null,
		best_rating: null,
		generations: [],
		created_at: '2026-01-01T00:00:00+00:00',
		is_shared: false,
		share_slug: null,
		...overrides
	};
}

async function render(item: SongItem): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(SongNode, { target, props: { song: item } });
	await tick();
	return target;
}

describe('SongNode', () => {
	it.each([
		[0, '0 takes'],
		[1, '1 take'],
		[2, '2 takes']
	])('counts %i as "%s", the word the listener uses', async (count, expected) => {
		const target = await render(song({ generation_count: count }));
		expect(target.querySelector('.song-meta')?.textContent?.trim()).toBe(expected);
	});

	it('opens the song it names, handing over what it already knows', async () => {
		const item = song();
		const target = await render(item);
		target.querySelector<HTMLElement>('.song-row')?.click();
		expect(selectSong).toHaveBeenCalledWith('s1', item);
	});
});
