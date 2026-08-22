import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { GenerationItem, SongItem } from '$lib/api/types';

vi.mock('$lib/stores/takeActions', () => ({
	setPick: vi.fn().mockResolvedValue(undefined),
	setKeep: vi.fn().mockResolvedValue(undefined),
	rate: vi.fn().mockResolvedValue(undefined),
	pinSeed: vi.fn()
}));

import { pinSeed, rate, setKeep, setPick } from '$lib/stores/takeActions';
import NowPlayingTake from './NowPlayingTake.svelte';

function generation(overrides: Partial<GenerationItem> = {}): GenerationItem {
	return {
		id: 'g1',
		song_id: 's1',
		version_id: 'v1',
		version_number: 3,
		generation_number: 3,
		mp3_path: 'a.mp3',
		wav_path: null,
		seed: 48113,
		status: 'completed',
		is_archived: false,
		is_picked: false,
		is_kept: false,
		is_shared: false,
		model_mode: 'sft',
		whisper_text: null,
		whisper_cues: null,
		version_lyrics: 'la la',
		scores: null,
		generation_params: null,
		created_at: '',
		...overrides
	};
}

function song(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's1',
		title: 'Tide',
		album_id: 'a1',
		album_title: 'Nachtstrom',
		artist: 'Artist',
		track_number: 1,
		vocal_language: 'en',
		lyrics: 'la la',
		prompt: 'dreamy',
		version_count: 1,
		generation_count: 1,
		is_shared: false,
		created_at: '',
		generations: [],
		...overrides
	};
}

let mounted: ReturnType<typeof mount> | undefined;
let target: HTMLDivElement;

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	vi.clearAllMocks();
});

async function render(
	overrides: Partial<{ generation: GenerationItem; song: SongItem; lyrics: string | null }> = {}
) {
	target = document.createElement('div');
	document.body.append(target);
	const lyrics = 'lyrics' in overrides ? (overrides.lyrics ?? null) : 'la la';
	mounted = mount(NowPlayingTake, {
		target,
		props: {
			generation: overrides.generation ?? generation(),
			song: overrides.song ?? song(),
			lyrics
		}
	});
	await tick();
}

describe('NowPlayingTake', () => {
	it('renders scores from the generation', async () => {
		await render({
			generation: generation({
				scores: {
					user_rating: 82,
					text_accuracy: 91,
					dynamics: 74
				}
			})
		});
		expect(target.textContent).toContain('82');
		expect(target.textContent).toContain('91%');
		expect(target.textContent).toContain('74');
	});

	it('shows a named empty state when there are no scores yet', async () => {
		await render({ generation: generation({ scores: null }) });
		expect(target.textContent).toContain('No scores yet');
	});

	it('shows deviation rows only when the sung transcript differs from the lyrics', async () => {
		await render({
			lyrics: 'die Luft schmeckt weit',
			generation: generation({ whisper_text: 'die Luft schmeckt breit' })
		});
		expect(target.textContent).toContain('schmeckt weit');
		expect(target.textContent).toContain('schmeckt breit');
	});

	it('ignores blank lines and [Section] markers, which are never sung', async () => {
		await render({
			lyrics: '[Verse]\ndie Luft schmeckt weit\n\n[Chorus]\nhalt die Haende auf',
			generation: generation({
				whisper_text: 'die Luft schmeckt weit\nhalt die Haende auf'
			})
		});
		expect(target.textContent).toContain('Sung text matches the lyrics');
	});

	it('shows a matches-the-lyrics state when the transcript is identical', async () => {
		await render({
			lyrics: 'die Luft schmeckt weit',
			generation: generation({ whisper_text: 'die Luft schmeckt weit' })
		});
		expect(target.textContent).toContain('Sung text matches the lyrics');
	});

	it('shows an unavailable state with no transcript yet', async () => {
		await render({
			lyrics: 'die Luft schmeckt weit',
			generation: generation({ whisper_text: null })
		});
		expect(target.textContent).toContain('No transcript to compare against yet');
	});

	it('flips pick through takeActions', async () => {
		await render({ generation: generation({ is_picked: false }) });
		target.querySelector<HTMLButtonElement>('button[aria-label="Pick"]')?.click();
		await tick();
		expect(setPick).toHaveBeenCalledWith('s1', 'g1', true);
	});

	it('flips keep through takeActions', async () => {
		await render({ generation: generation({ is_kept: true }) });
		target.querySelector<HTMLButtonElement>('button[aria-label="Unkeep"]')?.click();
		await tick();
		expect(setKeep).toHaveBeenCalledWith('s1', 'g1', false);
	});

	it('saves the rating through takeActions once the slider is dirty', async () => {
		await render({ generation: generation({ scores: { user_rating: 50 } }) });
		const slider = target.querySelector<HTMLInputElement>('.rating-slider');
		if (!slider) throw new Error('Expected rating slider');
		slider.value = '80';
		slider.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();

		const save = target.querySelector<HTMLButtonElement>('.rating-save');
		expect(save).not.toBeNull();
		save?.click();
		await tick();
		expect(rate).toHaveBeenCalledWith('s1', 'g1', 80, '');
	});

	it('pins the seed through takeActions', async () => {
		await render({ generation: generation({ seed: 48113 }) });
		target.querySelector<HTMLButtonElement>('.pin-seed')?.click();
		expect(pinSeed).toHaveBeenCalledWith(48113);
	});

	it('omits the pin seed action when the take has no seed', async () => {
		await render({ generation: generation({ seed: null }) });
		expect(target.querySelector('.pin-seed')).toBeNull();
	});
});
