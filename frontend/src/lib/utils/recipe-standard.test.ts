import { describe, expect, it } from 'vitest';
import {
	DIT_BOOL_FIELDS,
	DIT_NUMBER_FIELDS,
	DIT_SELECT_FIELDS,
	LM_BOOL_FIELDS,
	LM_NUMBER_FIELDS,
	LM_TEXT_FIELDS
} from '$lib/constants/acestep-param-fields';
import { RECIPE_TAKES_STANDARD } from '$lib/constants/recipe';
import {
	changedRecipeFields,
	changedRecipeTabs,
	chooseEnginePreset,
	engineParams,
	isEngineParamKey,
	matchingEnginePreset,
	recipeDiffersFromStandard,
	resetRecipeField,
	resetRecipeTab,
	type RecipeStandard,
	type RecipeValues
} from './recipe-standard';

const standard: RecipeStandard = {
	model: 'xl-turbo',
	engineDefaults: { lm_temperature: 0.85, inference_steps: 8, thinking: true, shift: 3 }
};

function values(overrides: Partial<RecipeValues> = {}): RecipeValues {
	return {
		bpm: 0,
		audioDuration: 0,
		keyScale: '',
		genParams: null,
		model: 'xl-turbo',
		takes: RECIPE_TAKES_STANDARD,
		...overrides
	};
}

describe('changedRecipeFields', () => {
	it('finds nothing changed on a fresh recipe', () => {
		expect(changedRecipeFields(values(), standard)).toEqual(new Set());
	});

	it.each([
		['bpm', { bpm: 145 }],
		['duration', { audioDuration: 120 }],
		['key', { keyScale: 'C major' }],
		['voice', { genParams: { user_lora_id: 'mara' } }],
		['reference', { genParams: { reference_audio_path: 'refs/a.wav' } }],
		['model', { model: 'sft' }],
		['takes', { takes: 3 }],
		['lm_temperature', { genParams: { lm_temperature: 0.5 } }],
		['thinking', { genParams: { thinking: false } }]
	] as const)('marks %s when it differs from the standard', (field, change) => {
		expect(changedRecipeFields(values(change), standard)).toContain(field);
	});

	it('does not mark an engine field typed equal to the default it shows in grey', () => {
		const typedDefault = values({ genParams: { lm_temperature: 0.85, thinking: true } });
		expect(changedRecipeFields(typedDefault, standard)).toEqual(new Set());
	});

	it('does not mark the model before one is chosen', () => {
		expect(changedRecipeFields(values({ model: null }), standard)).toEqual(new Set());
	});

	it('marks the preset row once any engine field changed', () => {
		const fields = changedRecipeFields(values({ genParams: { shift: 5 } }), standard);
		expect(fields).toEqual(new Set(['shift', 'preset']));
	});
});

describe('changedRecipeTabs', () => {
	it('rolls every changed field up to its tab', () => {
		const changed = values({
			bpm: 145,
			takes: 3,
			genParams: { lm_temperature: 0.5, user_lora_id: 'mara' }
		});
		expect(changedRecipeTabs(changed, standard)).toEqual(new Set(['song', 'generate', 'engine']));
	});

	it('leaves the tabs of unchanged fields alone', () => {
		expect(changedRecipeTabs(values({ bpm: 145 }), standard)).toEqual(new Set(['song']));
	});
});

describe('recipeDiffersFromStandard', () => {
	it('is false at the standard and true as soon as one field differs', () => {
		expect(recipeDiffersFromStandard(values(), standard)).toBe(false);
		expect(recipeDiffersFromStandard(values({ takes: 2 }), standard)).toBe(true);
	});
});

describe('resetRecipeField', () => {
	it('puts a scalar back to its standard and touches no other field', () => {
		const start = values({ bpm: 145, keyScale: 'C', model: 'sft', takes: 3 });
		expect(resetRecipeField(start, 'bpm', standard)).toEqual({ ...start, bpm: 0 });
		expect(resetRecipeField({ ...start, audioDuration: 180 }, 'duration', standard)).toEqual(start);
		expect(resetRecipeField(start, 'model', standard)).toEqual({ ...start, model: 'xl-turbo' });
		expect(resetRecipeField(start, 'takes', standard)).toEqual({ ...start, takes: 1 });
	});

	it('empties one engine field and keeps the rest of the params', () => {
		const start = values({ genParams: { lm_temperature: 0.5, shift: 5, user_lora_id: 'mara' } });
		expect(resetRecipeField(start, 'lm_temperature', standard).genParams).toEqual({
			shift: 5,
			user_lora_id: 'mara'
		});
	});

	it('leaves no params object behind when the last field goes', () => {
		const start = values({ genParams: { shift: 5 } });
		expect(resetRecipeField(start, 'shift', standard).genParams).toBeNull();
	});

	it('removes the voice or the reference alone', () => {
		const start = values({ genParams: { user_lora_id: 'mara', reference_audio_path: 'a.wav' } });
		expect(resetRecipeField(start, 'voice', standard).genParams).toEqual({
			reference_audio_path: 'a.wav'
		});
		expect(resetRecipeField(start, 'reference', standard).genParams).toEqual({
			user_lora_id: 'mara'
		});
	});

	it('resets the preset row by emptying every engine field but keeping voice and reference', () => {
		const start = values({
			genParams: { shift: 5, lm_temperature: 0.5, user_lora_id: 'mara', reference_audio_path: 'a' }
		});
		expect(resetRecipeField(start, 'preset', standard).genParams).toEqual({
			user_lora_id: 'mara',
			reference_audio_path: 'a'
		});
	});
});

describe('resetRecipeTab', () => {
	const start = values({
		bpm: 145,
		audioDuration: 90,
		keyScale: 'C',
		model: 'sft',
		takes: 3,
		genParams: { user_lora_id: 'mara', reference_audio_path: 'a', shift: 5 }
	});

	it('resets every Song field and nothing of Generate or Engine', () => {
		expect(resetRecipeTab(start, 'song', standard)).toEqual({
			...start,
			bpm: 0,
			audioDuration: 0,
			keyScale: '',
			genParams: { shift: 5 }
		});
	});

	it('resets Model and Takes and nothing else', () => {
		expect(resetRecipeTab(start, 'generate', standard)).toEqual({
			...start,
			model: 'xl-turbo',
			takes: 1
		});
	});

	it('resets the engine fields and keeps Voice and Reference', () => {
		expect(resetRecipeTab(start, 'engine', standard)).toEqual({
			...start,
			genParams: { user_lora_id: 'mara', reference_audio_path: 'a' }
		});
	});
});

describe('chooseEnginePreset', () => {
	const start = values({
		genParams: { user_lora_id: 'mara', reference_audio_path: 'a', shift: 5, thinking: false }
	});

	it('replaces the engine fields and keeps Voice and Reference', () => {
		const chosen = chooseEnginePreset(start, { lm_temperature: 0.4, user_lora_id: 'other' });
		expect(chosen.genParams).toEqual({
			user_lora_id: 'mara',
			reference_audio_path: 'a',
			lm_temperature: 0.4
		});
	});

	it('choosing Default empties the engine fields and keeps Voice and Reference', () => {
		expect(chooseEnginePreset(start, null).genParams).toEqual({
			user_lora_id: 'mara',
			reference_audio_path: 'a'
		});
	});

	it('leaves no params object when nothing is kept', () => {
		expect(chooseEnginePreset(values({ genParams: { shift: 5 } }), null).genParams).toBeNull();
	});
});

describe('engineParams', () => {
	it('keeps the engine fields and leaves Voice and Reference out of a preset', () => {
		const start = values({
			genParams: { user_lora_id: 'mara', reference_audio_path: 'a', shift: 5, thinking: false }
		});
		expect(engineParams(start)).toEqual({ shift: 5, thinking: false });
	});
});

describe('matchingEnginePreset', () => {
	const presets = [
		{ id: 'other-model', model_mode: 'other', params: { inference_steps: 4 } },
		{ id: 'match', model_mode: 'acestep', params: { inference_steps: 4 } }
	];

	it('finds the preset of the recipe model whose engine fields are the draft', () => {
		const draft = values({ model: 'acestep', genParams: { inference_steps: 4 } });
		expect(matchingEnginePreset(draft, presets)?.id).toBe('match');
	});

	it('finds none when the draft matches no preset', () => {
		const draft = values({ model: 'acestep', genParams: { inference_steps: 9 } });
		expect(matchingEnginePreset(draft, presets)).toBeUndefined();
	});
});

describe('every engine field the editor exposes', () => {
	const registryKeys = [
		...DIT_NUMBER_FIELDS,
		...DIT_SELECT_FIELDS,
		...DIT_BOOL_FIELDS,
		...LM_NUMBER_FIELDS,
		...LM_TEXT_FIELDS,
		...LM_BOOL_FIELDS
	].map((field) => field.key);

	it.each(registryKeys)('%s is marked when it differs from its standard', (key) => {
		if (!isEngineParamKey(key)) throw new Error(key);
		const changed = changedRecipeFields(values({ genParams: { [key]: 'differs' } }), {
			model: 'xl-turbo',
			engineDefaults: {}
		});
		expect(changed.has(key)).toBe(true);
	});
});
