import { RECIPE_SOURCE_DURATION_DEFAULT_SECONDS } from '#lib/constants.ts';
import { makeGeneration as generation } from '#lib/test-utils/factories.ts';
import { beforeEach, describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import { toasts } from '#lib/stores/toast.ts';
import type { GenerationItem } from '#lib/api/types.ts';
import {
	clearSource,
	coverStrength,
	applyTakeUse,
	clearSeed,
	pendingTakeUse,
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

	it('setSourceFromGeneration leaves the Recipe closed and resets a repaint range', () => {
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

	it('resetRecipeSourceForSong clears the source and closes the recipe view but keeps the model (#1927)', () => {
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
