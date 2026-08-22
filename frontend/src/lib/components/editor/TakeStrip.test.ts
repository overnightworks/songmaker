import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { GenerationItem, SongItem } from '$lib/api/types';

vi.mock('$lib/stores/player', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/stores/player')>();
	return {
		...actual,
		playTake: vi.fn(async () => undefined)
	};
});

import { playTake } from '$lib/stores/player';
import TakeStrip from './TakeStrip.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	vi.mocked(playTake).mockClear();
});

function gen(overrides: Partial<GenerationItem> = {}): GenerationItem {
	return {
		id: 'g1',
		song_id: 's1',
		version_id: 'v1',
		version_number: 3,
		generation_number: 3,
		mp3_path: 'g1.mp3',
		wav_path: null,
		seed: 7,
		status: 'completed',
		is_archived: false,
		is_picked: false,
		is_kept: false,
		is_shared: false,
		model_mode: 'turbo',
		whisper_text: null,
		whisper_cues: null,
		version_lyrics: null,
		scores: null,
		generation_params: null,
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

function song(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's1',
		title: 'Test',
		album_id: 'a1',
		album_title: 'Album',
		artist: 'Artist',
		track_number: 1,
		vocal_language: 'en',
		lyrics: '',
		prompt: '',
		bpm: 120,
		audio_duration: 180,
		key_scale: 'Am',
		generation_params: null,
		version_count: 1,
		generation_count: 1,
		best_scores: null,
		best_rating: null,
		generations: [],
		created_at: '2026-01-01T00:00:00+00:00',
		is_shared: false,
		share_slug: null,
		...overrides
	};
}

async function render(generations: GenerationItem[]) {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(TakeStrip, { target, props: { song: song({ generations }) } }));
	await tick();
	return { target };
}

describe('TakeStrip', () => {
	it('renders one chip per take, newest version and take first', async () => {
		const { target } = await render([
			gen({ id: 'g1', version_number: 2, generation_number: 1 }),
			gen({ id: 'g2', version_number: 3, generation_number: 2 }),
			gen({ id: 'g3', version_number: 3, generation_number: 1 })
		]);
		const labels = Array.from(target.querySelectorAll('.take-chip-label')).map(
			(el) => el.textContent
		);
		expect(labels).toEqual(['v3-2', 'v3-1', 'v2-1']);
	});

	it('shows a pick or keep badge', async () => {
		const picked = gen({ id: 'g1', is_picked: true });
		const { target } = await render([picked]);
		expect(target.querySelector('.badge.picked')).not.toBeNull();
	});

	it('plays the take on click instead of opening Now Playing', async () => {
		const picked = gen({ id: 'g1', is_picked: true });
		const { target } = await render([picked]);
		target.querySelector<HTMLButtonElement>('.take-chip')?.click();
		await tick();
		await Promise.resolve();
		expect(playTake).toHaveBeenCalledWith(picked, expect.objectContaining({ id: 's1' }));
	});

	it('renders nothing when there are no takes', async () => {
		const { target } = await render([]);
		expect(target.querySelector('.take-strip')).toBeNull();
	});
});
