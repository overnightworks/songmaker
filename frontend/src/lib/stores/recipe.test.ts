import { beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

vi.mock('$lib/stores/editor', () => {
	return {
		applyGenerationSettings: vi.fn(),
		pinnedSeed: { set: vi.fn() }
	};
});

import { applyGenerationSettings, pinnedSeed } from '$lib/stores/editor';
import type { GenerationItem } from '$lib/api/types';
import {
	applyAgainFromGeneration,
	clearSource,
	coWriterOpen,
	coverStrength,
	pendingSource,
	recipeChips,
	recipeModel,
	recipeOpen,
	recipeParamsFromTake,
	repaintMode,
	resetRecipeSourceForSong,
	seedRecipeModel,
	setSourceFromGeneration,
	sourceGeneration,
	sourceMode,
	takesPerGenerate
} from './recipe';

function generation(overrides: Partial<GenerationItem> = {}): GenerationItem {
	return {
		id: 'g1',
		song_id: 's1',
		version_id: 'v1',
		version_number: 1,
		generation_number: 1,
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
		generation_params: {
			inference_steps: 8,
			guidance_scale: 1.5,
			task_type: 'text2music',
			seed: 7
		},
		audio_duration_sec: null,
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

describe('recipeChips', () => {
	it('projects the ten labeled chips from editor and recipe state', () => {
		const chips = recipeChips({
			model: 'turbo',
			takes: 2,
			bpm: 108,
			audioDuration: 195,
			keyScale: 'A major',
			voiceLabel: 'None',
			pinnedSeed: null,
			genParams: null,
			sourceGeneration: null,
			sourceMode: 'repaint',
			repaintMode: 'conservative'
		});
		expect(chips.map((c) => c.key)).toEqual([
			'model',
			'takes',
			'bpm',
			'duration',
			'key',
			'voice',
			'seed',
			'lm',
			'dit',
			'repaint'
		]);
		expect(chips.find((c) => c.key === 'model')?.value).toBe('TURBO');
		expect(chips.find((c) => c.key === 'takes')?.value).toBe('×2');
		expect(chips.find((c) => c.key === 'bpm')?.value).toBe('108');
		expect(chips.find((c) => c.key === 'duration')?.value).toBe('195 s');
		expect(chips.find((c) => c.key === 'seed')?.value).toBe('Random');
		expect(chips.find((c) => c.key === 'repaint')?.value).toBe('Off');
	});

	it('shows Auto for zero BPM/duration and Pinned for a pinned seed', () => {
		const chips = recipeChips({
			model: null,
			takes: 1,
			bpm: 0,
			audioDuration: 0,
			keyScale: '',
			voiceLabel: 'None',
			pinnedSeed: 48113,
			genParams: null,
			sourceGeneration: null,
			sourceMode: 'repaint',
			repaintMode: 'conservative'
		});
		expect(chips.find((c) => c.key === 'bpm')?.value).toBe('Auto');
		expect(chips.find((c) => c.key === 'duration')?.value).toBe('Auto');
		expect(chips.find((c) => c.key === 'key')?.value).toBe('—');
		expect(chips.find((c) => c.key === 'seed')?.value).toBe('Pinned 48113');
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
			pinnedSeed: null,
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

	it('shows the repaint mode when a source is picked, and Cover in cover mode', () => {
		const gen = generation();
		const base = {
			model: 'turbo',
			takes: 1,
			bpm: 120,
			audioDuration: 180,
			keyScale: 'Am',
			voiceLabel: 'None',
			pinnedSeed: null,
			genParams: null,
			repaintMode: 'balanced' as const
		};
		expect(
			recipeChips({ ...base, sourceGeneration: gen, sourceMode: 'repaint' }).find(
				(c) => c.key === 'repaint'
			)?.value
		).toBe('Balanced');
		expect(
			recipeChips({ ...base, sourceGeneration: gen, sourceMode: 'cover' }).find(
				(c) => c.key === 'repaint'
			)?.value
		).toBe('Cover');
	});

	it('marks a chip changed only when the draft value differs from the last-saved version', () => {
		const base = {
			model: 'turbo',
			takes: 1,
			bpm: 120,
			audioDuration: 180,
			keyScale: 'Am',
			voiceLabel: 'None',
			pinnedSeed: null,
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

describe('recipeParamsFromTake', () => {
	it('keeps only recipe-relevant keys', () => {
		const params = recipeParamsFromTake(generation().generation_params);
		expect(params.inference_steps).toBe(8);
		expect(params.guidance_scale).toBe(1.5);
		expect((params as Record<string, unknown>).task_type).toBeUndefined();
		expect((params as Record<string, unknown>).seed).toBeUndefined();
	});

	it('returns an empty object for missing params', () => {
		expect(recipeParamsFromTake(null)).toEqual({});
	});
});

describe('recipe session state', () => {
	beforeEach(() => {
		recipeModel.set(null);
		takesPerGenerate.set(1);
		recipeOpen.set(false);
		coWriterOpen.set(false);
		sourceGeneration.set(null);
		pendingSource.set(null);
		vi.clearAllMocks();
	});

	it('seeds the model only once, from the first active model', () => {
		seedRecipeModel(['fast', 'turbo']);
		expect(get(recipeModel)).toBe('fast');
		seedRecipeModel(['turbo']);
		expect(get(recipeModel)).toBe('fast');
	});

	it('setSourceFromGeneration opens the Recipe panel and resets a repaint range', () => {
		const gen = generation();
		setSourceFromGeneration(gen, 'repaint');
		expect(get(sourceGeneration)).toBe(gen);
		expect(get(sourceMode)).toBe('repaint');
		expect(get(recipeOpen)).toBe(true);
	});

	it('clearSource removes the picked take', () => {
		setSourceFromGeneration(generation(), 'cover');
		clearSource();
		expect(get(sourceGeneration)).toBeNull();
	});

	it('applyAgainFromGeneration stages reusable params and the seed without picking a source', () => {
		applyAgainFromGeneration(generation());
		expect(get(sourceGeneration)).toBeNull();
		expect(applyGenerationSettings).toHaveBeenCalledWith({
			inference_steps: 8,
			guidance_scale: 1.5
		});
		expect(pinnedSeed.set).toHaveBeenCalledWith(7);
		expect(get(recipeOpen)).toBe(true);
	});

	it('resetRecipeSourceForSong clears the source and closes both views but keeps the model', () => {
		recipeModel.set('turbo');
		takesPerGenerate.set(3);
		setSourceFromGeneration(generation(), 'repaint');
		coWriterOpen.set(true);
		resetRecipeSourceForSong();
		expect(get(sourceGeneration)).toBeNull();
		expect(get(repaintMode)).toBe('conservative');
		expect(get(coverStrength)).toBe(0.7);
		expect(get(recipeOpen)).toBe(false);
		expect(get(coWriterOpen)).toBe(false);
		expect(get(recipeModel)).toBe('turbo');
		expect(get(takesPerGenerate)).toBe(3);
	});
});
