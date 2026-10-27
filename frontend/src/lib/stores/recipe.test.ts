import { RECIPE_SOURCE_DURATION_DEFAULT_SECONDS } from '$lib/constants';
import { makeGeneration as generation } from '$lib/test-utils/factories';
import { beforeEach, describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import { toasts } from '$lib/stores/toast';
import type { GenerationItem } from '$lib/api/types';
import {
	clearSource,
	coverStrength,
	applyTakeUse,
	clearSeed,
	pendingTakeUse,
	recipeChips,
	recipeModel,
	recipeOpen,
	sourceTakeDurationSeconds,
	repaintEnd,
	repaintMode,
	repaintStart,
	resetRecipeSourceForSong,
	seedFromTake,
	seedRecipeModel,
	setSourceFromGeneration,
	sourceGeneration,
	sourceMode,
	takesPerGenerate,
	useSeed
} from './recipe';

function requestedRecipeDefaults(): Partial<GenerationItem> {
	return {
		generation_params: {
			inference_steps: 8,
			guidance_scale: 1.5,
			task_type: 'text2music',
			seed: 7
		}
	};
}

describe('recipeChips', () => {
	it('C1: projects the eight labeled chips from editor and recipe state', () => {
		const chips = recipeChips({
			model: 'turbo',
			takes: 2,
			bpm: 108,
			audioDuration: 195,
			keyScale: 'A major',
			voiceLabel: 'None',
			genParams: null
		});
		expect(chips.map((c) => c.key)).toEqual([
			'model',
			'takes',
			'bpm',
			'duration',
			'key',
			'voice',
			'lm',
			'dit'
		]);
		expect(chips.find((c) => c.key === 'model')?.value).toBe('TURBO');
		expect(chips.find((c) => c.key === 'takes')?.value).toBe('×2');
		expect(chips.find((c) => c.key === 'bpm')?.value).toBe('108');
		expect(chips.find((c) => c.key === 'duration')?.value).toBe('195 s');
	});

	it('C1: shows Auto for zero BPM/duration', () => {
		const chips = recipeChips({
			model: null,
			takes: 1,
			bpm: 0,
			audioDuration: 0,
			keyScale: '',
			voiceLabel: 'None',
			genParams: null
		});
		expect(chips.find((c) => c.key === 'bpm')?.value).toBe('Auto');
		expect(chips.find((c) => c.key === 'duration')?.value).toBe('Auto');
		expect(chips.find((c) => c.key === 'key')?.value).toBe('—');
		expect(chips.find((c) => c.key === 'model')?.value).toBe('—');
	});

	it('marks LM and DIT Custom only when a param in that group is overridden', () => {
		const base = {
			model: 'turbo',
			takes: 1,
			bpm: 120,
			audioDuration: 180,
			keyScale: 'Am',
			voiceLabel: 'None',
			sourceGeneration: null,
			sourceMode: 'repaint' as const,
			repaintMode: 'conservative' as const
		};
		expect(recipeChips({ ...base, genParams: null }).find((c) => c.key === 'lm')?.value).toBe(
			'Default'
		);
		expect(
			recipeChips({ ...base, genParams: { lm_temperature: 0.8 } }).find((c) => c.key === 'lm')
				?.value
		).toBe('Custom');
		expect(
			recipeChips({ ...base, genParams: { inference_steps: 40 } }).find((c) => c.key === 'dit')
				?.value
		).toBe('Custom');
		expect(
			recipeChips({ ...base, genParams: { lm_temperature: 0.8 } }).find((c) => c.key === 'dit')
				?.value
		).toBe('Default');
	});

	it('marks a chip changed only when the draft value differs from the last-saved version', () => {
		const base = {
			model: 'turbo',
			takes: 1,
			bpm: 120,
			audioDuration: 180,
			keyScale: 'Am',
			voiceLabel: 'None',
			genParams: null,
			sourceGeneration: null,
			sourceMode: 'repaint' as const,
			repaintMode: 'conservative' as const,
			savedBpm: 120,
			savedAudioDuration: 180,
			savedKeyScale: 'Am',
			savedGenParams: null
		};
		expect(recipeChips(base).find((c) => c.key === 'bpm')?.changed).toBe(false);
		expect(recipeChips({ ...base, bpm: 140 }).find((c) => c.key === 'bpm')?.changed).toBe(true);
		expect(recipeChips({ ...base, keyScale: 'C' }).find((c) => c.key === 'key')?.changed).toBe(
			true
		);
		expect(
			recipeChips({ ...base, genParams: { lm_temperature: 0.8 } }).find((c) => c.key === 'lm')
				?.changed
		).toBe(true);
		expect(
			recipeChips({ ...base, genParams: { lm_temperature: 0.8 } }).find((c) => c.key === 'dit')
				?.changed
		).toBe(false);
		expect(recipeChips({ ...base, model: 'base' }).find((c) => c.key === 'model')?.changed).toBe(
			false
		);
	});
});

describe('recipe session state', () => {
	beforeEach(() => {
		recipeModel.set(null);
		takesPerGenerate.set(1);
		recipeOpen.set(false);
		sourceGeneration.set(null);
		pendingTakeUse.set(null);
		seedFromTake.set(null);
	});

	it('seeds the model only once, from the first active model', () => {
		seedRecipeModel(['fast', 'turbo']);
		expect(get(recipeModel)).toBe('fast');
		seedRecipeModel(['turbo']);
		expect(get(recipeModel)).toBe('fast');
	});

	it('setSourceFromGeneration leaves the Recipe panel closed and resets a repaint range', () => {
		const gen = generation(requestedRecipeDefaults());
		repaintStart.set(0.3);
		repaintEnd.set(0.6);
		setSourceFromGeneration(gen, 'repaint');
		expect(get(sourceGeneration)).toBe(gen);
		expect(get(sourceMode)).toBe('repaint');
		expect([get(repaintStart), get(repaintEnd)]).toEqual([0, 1]);
		expect(get(recipeOpen)).toBe(false);
	});

	it('clearSource removes the picked take', () => {
		setSourceFromGeneration(generation(requestedRecipeDefaults()), 'cover');
		clearSource();
		expect(get(sourceGeneration)).toBeNull();
	});

	it('resetRecipeSourceForSong clears the source and closes the recipe view but keeps the model', () => {
		recipeModel.set('turbo');
		takesPerGenerate.set(3);
		setSourceFromGeneration(generation(requestedRecipeDefaults()), 'repaint');
		resetRecipeSourceForSong();
		expect(get(sourceGeneration)).toBeNull();
		expect(get(repaintMode)).toBe('conservative');
		expect(get(coverStrength)).toBe(0.7);
		expect(get(recipeOpen)).toBe(false);
		expect(get(seedFromTake)).toBeNull();
		expect(get(recipeModel)).toBe('turbo');
		expect(get(takesPerGenerate)).toBe(3);
	});
});

describe('seed from a take (C1, #1928 acceptance 1)', () => {
	beforeEach(() => {
		seedFromTake.set(null);
		toasts.set([]);
		sourceGeneration.set(null);
		sourceMode.set('repaint');
	});

	it('is set from the take, says so in a toast and is replaced by the next one', () => {
		useSeed(generation({ seed: 4127730, generation_number: 11 }));
		expect(get(toasts)).toEqual([
			expect.objectContaining({ message: 'Seed from take 11', type: 'success' })
		]);
		expect(get(seedFromTake)).toEqual({ seed: 4127730, takeNumber: 11 });
		useSeed(generation({ seed: 9, generation_number: 7 }));
		expect(get(seedFromTake)).toEqual({ seed: 9, takeNumber: 7 });
	});

	it('is left unchanged by a take without a seed', () => {
		useSeed(generation({ seed: 5, generation_number: 2 }));
		useSeed(generation({ seed: null, generation_number: 3 }));
		expect(get(seedFromTake)).toEqual({ seed: 5, takeNumber: 2 });
	});

	it('is cleared by clearSeed', () => {
		useSeed(generation({ seed: 5, generation_number: 2 }));
		clearSeed();
		expect(get(seedFromTake)).toBeNull();
	});

	it('is applied by a handed-over take and leaves the repaint source alone', () => {
		applyTakeUse({ generation: generation({ seed: 5, generation_number: 2 }), use: 'seed' });
		expect(get(seedFromTake)).toEqual({ seed: 5, takeNumber: 2 });
		expect(get(sourceGeneration)).toBeNull();
	});

	it.each([
		{ use: 'seed', opensTaskCard: false },
		{ use: 'repaint', opensTaskCard: true },
		{ use: 'cover', opensTaskCard: true }
	] as const)(
		'C1: a $use hand-over reports opening a task card: $opensTaskCard',
		({ use, opensTaskCard }) => {
			expect(applyTakeUse({ generation: generation({ seed: 5 }), use })).toBe(opensTaskCard);
		}
	);
});

describe('sourceTakeDurationSeconds', () => {
	it.each([
		{
			name: 'the measured length when the requested Duration is auto (0)',
			requested: 0,
			measured: 123.4,
			expected: 123.4
		},
		{
			name: 'the measured length when it differs from the request',
			requested: 180,
			measured: 95.2,
			expected: 95.2
		},
		{
			name: 'the named default when the length was never measured',
			requested: 0,
			measured: null,
			expected: RECIPE_SOURCE_DURATION_DEFAULT_SECONDS
		}
	])('gives $name', ({ requested, measured, expected }) => {
		const take = generation({
			generation_params: { audio_duration: requested },
			audio_duration_sec: measured
		});
		expect(sourceTakeDurationSeconds(take)).toBe(expected);
	});
});
