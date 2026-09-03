import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { GenerationItem, SongItem } from '$lib/api/types';

// rescoringTakeIds stays real so the pending state is driven the way the app
// drives it: by the scoring job sitting in the jobs store.
vi.mock('$lib/stores/takeActions', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/stores/takeActions')>()),
	setPick: vi.fn().mockResolvedValue(undefined),
	setKeep: vi.fn().mockResolvedValue(undefined),
	rate: vi.fn().mockResolvedValue(undefined),
	pinSeed: vi.fn(),
	rescore: vi.fn().mockResolvedValue(undefined)
}));
vi.mock('$lib/stores/navigation', () => ({
	revealPlayingSong: vi.fn().mockResolvedValue(undefined)
}));

import { get } from 'svelte/store';
import { TAKE_RESCORE_LABEL, TAKE_RESCORING_LABEL } from '$lib/constants';
import { NOW_PLAYING_RESCORE_ACTION_LABEL } from '$lib/constants/now-playing';
import { activeJobs } from '$lib/stores/jobs';
import { pinSeed, rate, rescore, setKeep, setPick } from '$lib/stores/takeActions';
import { revealPlayingSong } from '$lib/stores/navigation';
import { nowPlayingOpen, nowPlayingSurface } from '$lib/stores/player';
import { pendingSource } from '$lib/stores/recipe';
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
		audio_duration_sec: null,
		created_at: '',
		...overrides
	};
}

function song(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's1',
		slug: 'tide',
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
	nowPlayingSurface.set('closed');
	pendingSource.set(null);
	activeJobs.set([]);
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
	it("names the take's version, number, duration and model in the heading", async () => {
		await render({
			generation: generation({
				version_number: 3,
				generation_number: 3,
				model_mode: 'xl-sft',
				audio_duration_sec: 195
			})
		});
		expect(target.querySelector('.take-heading')?.textContent).toBe('v3 · take 3 · 3:15 · xl-sft');
	});

	it('shows its own measured length, not the "auto" (0) duration it was requested with', async () => {
		await render({
			generation: generation({
				version_number: 4,
				generation_number: 4,
				model_mode: 'xl-turbo',
				generation_params: { audio_duration: 0 },
				audio_duration_sec: 188
			})
		});
		expect(target.querySelector('.take-heading')?.textContent).toBe(
			'v4 · take 4 · 3:08 · xl-turbo'
		);
	});

	it('names no duration at all for a take whose length has not been measured', async () => {
		await render({
			generation: generation({
				version_number: 1,
				generation_number: 1,
				model_mode: 'sft',
				audio_duration_sec: null
			})
		});
		const heading = target.querySelector('.take-heading')?.textContent ?? '';
		expect(heading).toBe('v1 · take 1 · sft');
		expect(heading).not.toContain('0:00');
	});

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

	it('highlights only the sung word that differs from the lyrics word at that position', async () => {
		await render({
			lyrics: 'die Luft schmeckt weit',
			generation: generation({ whisper_text: 'die Luft schmeckt breit' })
		});
		const tokens = Array.from(target.querySelectorAll('.dev-token'));
		expect(tokens.map((el) => el.textContent)).toEqual(['die', 'Luft', 'schmeckt', 'breit']);
		const changed = target.querySelector('.dev-token.changed');
		expect(changed?.textContent).toBe('breit');
		expect(changed?.getAttribute('title')).toBe('Lyrics: weit');
		expect(target.querySelectorAll('.dev-token.changed, .dev-token.missing')).toHaveLength(1);
	});

	it('does not flag a punctuation-only difference as a deviation', async () => {
		await render({
			lyrics: 'Rahmen, Luft.',
			generation: generation({ whisper_text: 'rahmen luft' })
		});
		expect(target.textContent).toContain('Sung text matches the lyrics');
	});

	it('does not flag a case-only difference as a deviation', async () => {
		await render({
			lyrics: 'Die Luft Schmeckt',
			generation: generation({ whisper_text: 'die luft schmeckt' })
		});
		expect(target.textContent).toContain('Sung text matches the lyrics');
	});

	it('marks a sung word absent from the lyrics as added, with its own tooltip', async () => {
		await render({
			lyrics: 'die Luft schmeckt',
			generation: generation({ whisper_text: 'die frische Luft schmeckt' })
		});
		const added = target.querySelector('.dev-token.added');
		expect(added?.textContent).toBe('frische');
		expect(added?.getAttribute('title')).toBe('Not in lyrics');
		expect(added?.getAttribute('aria-label')).toBe('frische (Not in lyrics)');
		expect(target.querySelector('.dev-token.changed')).toBeNull();
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

	it('asks for a re-score while the take has no lyric cues', async () => {
		// #141/9: without cues the lyrics cannot follow the audio, and the panel
		// says why instead of leaving the listener to guess.
		await render({ generation: generation({ whisper_cues: null }) });
		expect(target.textContent).toContain(NOW_PLAYING_RESCORE_ACTION_LABEL);
	});

	it('re-scores the take from the hint, once', async () => {
		await render({ generation: generation({ whisper_cues: null }) });
		const hint = target.querySelector<HTMLButtonElement>('.rescore-hint');
		if (!hint) throw new Error('Expected the re-score hint button');
		expect(hint.textContent?.trim()).toBe(NOW_PLAYING_RESCORE_ACTION_LABEL);

		hint.click();
		await tick();

		expect(rescore).toHaveBeenCalledTimes(1);
		expect(rescore).toHaveBeenCalledWith('s1', 'g1');
	});

	it('reports the take as re-scoring while its scoring job runs', async () => {
		activeJobs.set([
			{
				job: {
					id: 'j1',
					type: 'score',
					status: 'running',
					progress: 0.2,
					error: null,
					error_type: null,
					started_at: null,
					completed_at: null
				},
				songId: 's1',
				genId: 'g1'
			}
		]);
		await render({ generation: generation({ whisper_cues: null }) });
		const hint = target.querySelector<HTMLButtonElement>('.rescore-hint');
		if (!hint) throw new Error('Expected the re-score hint button');

		expect(hint.textContent?.trim()).toBe(TAKE_RESCORING_LABEL);
		expect(hint.disabled).toBe(true);

		hint.click();
		await tick();
		expect(rescore).not.toHaveBeenCalled();
	});

	it('offers Re-score even when the take already has cues', async () => {
		// A take scored before word timestamps carries segment-only cues, whose
		// lines light together — re-scoring is exactly what buys per-line timing,
		// so the entry cannot hang off the missing-cues hint.
		await render({
			generation: generation({
				whisper_cues: [{ start: 0, end: 1.5, text: 'la la' }]
			})
		});
		const entry = target.querySelector<HTMLButtonElement>('.rescore');
		if (!entry) throw new Error('Expected the Re-score entry');
		expect(entry.textContent?.trim()).toBe(TAKE_RESCORE_LABEL);
		expect(target.querySelector('.rescore-hint')).toBeNull();

		entry.click();
		await tick();

		expect(rescore).toHaveBeenCalledTimes(1);
		expect(rescore).toHaveBeenCalledWith('s1', 'g1');
	});

	it('reports the Re-score entry as re-scoring while its scoring job runs', async () => {
		activeJobs.set([
			{
				job: {
					id: 'j1',
					type: 'score',
					status: 'running',
					progress: 0.2,
					error: null,
					error_type: null,
					started_at: null,
					completed_at: null
				},
				songId: 's1',
				genId: 'g1'
			}
		]);
		await render({
			generation: generation({
				whisper_cues: [{ start: 0, end: 1.5, text: 'la la' }]
			})
		});
		const entry = target.querySelector<HTMLButtonElement>('.rescore');
		if (!entry) throw new Error('Expected the Re-score entry');

		expect(entry.textContent?.trim()).toBe(TAKE_RESCORING_LABEL);
		expect(entry.disabled).toBe(true);

		entry.click();
		await tick();
		expect(rescore).not.toHaveBeenCalled();
	});

	it('drops the re-score hint once the take has cues', async () => {
		await render({
			generation: generation({
				whisper_cues: [{ start: 0, end: 1.5, text: 'la la' }]
			})
		});
		expect(target.textContent).not.toContain(NOW_PLAYING_RESCORE_ACTION_LABEL);
	});

	it.each(['.badge-btn', '.pin-seed', '.take-source-action', '.rescore-hint', '.rescore'])(
		'opts %s into the frequent hitbox',
		async (selector) => {
			// Sizing itself is pinned once for the shared mechanism in
			// frequent-hitbox.test.ts; here the contract is that these controls opt in.
			await render({});
			const controls = Array.from(target.querySelectorAll<HTMLElement>(selector));
			expect(controls.length).toBeGreaterThan(0);
			for (const control of controls) expect(control.dataset.hitbox).toBe('frequent');
		}
	);

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

	it('saves rating notes alongside the rating through takeActions', async () => {
		await render({ generation: generation({ scores: { user_rating: 50 } }) });
		const notes = target.querySelector<HTMLTextAreaElement>('.rating-notes');
		if (!notes) throw new Error('Expected a notes textarea');
		notes.value = 'Loved the bridge';
		notes.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();

		const save = target.querySelector<HTMLButtonElement>('.rating-save');
		save?.click();
		await tick();
		expect(rate).toHaveBeenCalledWith('s1', 'g1', 50, 'Loved the bridge');
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

	it.each([
		['Repaint', 'repaint'],
		['Cover', 'cover']
	] as const)(
		'%s sets the recipe source, closes Now Playing, and navigates to the song',
		async (label, mode) => {
			nowPlayingSurface.set('full');
			const gen = generation();
			const withSong = song();
			await render({ generation: gen, song: withSong });

			Array.from(target.querySelectorAll<HTMLButtonElement>('.take-source-action'))
				.find((button) => button.textContent?.trim() === label)
				?.click();
			await tick();

			expect(get(pendingSource)).toEqual({ generation: gen, mode });
			expect(get(nowPlayingOpen)).toBe(false);
			expect(revealPlayingSong).toHaveBeenCalledWith(withSong, gen.id);
		}
	);
});

describe('NowPlayingTake recipe section', () => {
	function recipeRows(root: ParentNode): Array<[string, string]> {
		return Array.from(root.querySelectorAll('.recipe-row')).map((row) => [
			row.querySelector('dt')?.textContent ?? '',
			row.querySelector('dd')?.textContent ?? ''
		]);
	}

	it('groups everything the take carries under its own labelled section', async () => {
		await render({
			generation: generation({
				model_mode: 'xl-sft',
				seed: 48113,
				generation_params: {
					inference_steps: 50,
					guidance_scale: 7.5,
					bpm: 128,
					audio_duration: 195,
					key_scale: 'Am'
				}
			}),
			song: song({ vocal_language: 'en' })
		});

		const groupLabels = Array.from(target.querySelectorAll('.recipe-group-label')).map(
			(el) => el.textContent
		);
		expect(groupLabels).toEqual(['Model & Sampling', 'Reproducibility', 'Version']);
		expect(recipeRows(target)).toEqual([
			['Model', 'xl-sft'],
			['Inference Steps', '50'],
			['Guidance Scale', '7.5'],
			['Seed', '48113'],
			['BPM', '128'],
			['Duration', '3:15'],
			['Key', 'Am'],
			['Language', 'en']
		]);
	});

	it('names a param the registry does not know under Other', async () => {
		await render({
			generation: generation({
				model_mode: '',
				seed: null,
				generation_params: { repaint_wav_crossfade_sec: 0.25 }
			}),
			song: song({ vocal_language: '' })
		});
		expect(
			Array.from(target.querySelectorAll('.recipe-group-label')).map((el) => el.textContent)
		).toEqual(['Other']);
		expect(recipeRows(target)).toEqual([['Repaint Wav Crossfade Sec', '0.25']]);
	});

	it('shows no recipe section for a take that carries nothing to show', async () => {
		await render({
			generation: generation({ model_mode: '', seed: null }),
			song: song({ vocal_language: '' })
		});
		expect(target.querySelector('.recipe-section')).toBeNull();
	});

	it('starts collapsed — the listener opens it, it does not open on them', async () => {
		await render({ generation: generation({ model_mode: 'xl-sft' }) });
		const details = target.querySelector<HTMLDetailsElement>('.recipe-section');
		expect(details?.open).toBe(false);
	});
});
