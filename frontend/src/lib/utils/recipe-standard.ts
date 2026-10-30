import type { ReferenceResponse, VersionGenerationParams } from '#lib/api/types.ts';
import { RECIPE_TAKES_STANDARD } from '#lib/constants/recipe.ts';
// The one owner of "this recipe field differs from its standard". The
// standard is the model default for every field, never the saved version, so
// saving does not clear a mark. Pure: surfaces read it, nothing else decides.

export type RecipeTab = 'song' | 'generate' | 'engine';

// Written out, not derived from the param-field registry, so the closed
// RecipeField union below resolves without the generated API types.
const ENGINE_PARAM_KEYS = [
	'inference_steps',
	'guidance_scale',
	'shift',
	'cfg_interval_start',
	'cfg_interval_end',
	'velocity_norm_threshold',
	'velocity_ema_factor',
	'latent_shift',
	'latent_rescale',
	'audio_cover_strength',
	'infer_method',
	'sampler_mode',
	'use_adg',
	'lm_temperature',
	'lm_top_k',
	'lm_top_p',
	'lm_cfg_scale',
	'lm_repetition_penalty',
	'batch_size',
	'thinking',
	'use_cot_caption',
	'use_cot_language',
	'lm_negative_prompt'
] as const satisfies readonly (keyof VersionGenerationParams)[];

type EngineParamKey = (typeof ENGINE_PARAM_KEYS)[number];

const ENGINE_PARAM_KEY_NAMES: ReadonlySet<string> = new Set(ENGINE_PARAM_KEYS);

/** Whether a generation parameter key is one the recipe marks and resets. */
export function isEngineParamKey(key: string): key is EngineParamKey {
	return ENGINE_PARAM_KEY_NAMES.has(key);
}

const SONG_FIELDS = ['bpm', 'duration', 'key', 'voice', 'reference'] as const;
const GENERATE_FIELDS = ['model', 'takes'] as const;

/** A recipe field: a named row (SONG_FIELDS, GENERATE_FIELDS), the 'preset' row, or one engine parameter. */
export type RecipeField =
	(typeof SONG_FIELDS)[number] | (typeof GENERATE_FIELDS)[number] | 'preset' | EngineParamKey;

/** The recipe's editable state as the page holds it. */
export interface RecipeValues {
	bpm: number;
	audioDuration: number;
	keyScale: string;
	genParams: VersionGenerationParams | null;
	reference: ReferenceResponse | null;
	model: string | null;
	takes: number;
}

/** What each field returns to: the first active model and the active model's engine defaults. */
export interface RecipeStandard {
	model: string | null;
	engineDefaults: VersionGenerationParams;
}

function isEngineParamChanged(
	params: VersionGenerationParams | null,
	key: EngineParamKey,
	standard: RecipeStandard
): boolean {
	const value = params?.[key];
	return value != null && value !== standard.engineDefaults[key];
}

export function changedRecipeFields(
	values: RecipeValues,
	standard: RecipeStandard
): Set<RecipeField> {
	const changed = new Set<RecipeField>();
	if (values.bpm !== 0) changed.add('bpm');
	if (values.audioDuration !== 0) changed.add('duration');
	if (values.keyScale !== '') changed.add('key');
	if (values.genParams?.user_lora_id) changed.add('voice');
	if (values.reference) changed.add('reference');
	if (values.model !== null && values.model !== standard.model) changed.add('model');
	if (values.takes !== RECIPE_TAKES_STANDARD) changed.add('takes');
	for (const key of ENGINE_PARAM_KEYS) {
		if (isEngineParamChanged(values.genParams, key, standard)) changed.add(key);
	}
	if (ENGINE_PARAM_KEYS.some((key) => changed.has(key))) changed.add('preset');
	return changed;
}

function tabOfField(field: RecipeField): RecipeTab {
	if ((SONG_FIELDS as readonly string[]).includes(field)) return 'song';
	if ((GENERATE_FIELDS as readonly string[]).includes(field)) return 'generate';
	return 'engine';
}

export function changedRecipeTabs(values: RecipeValues, standard: RecipeStandard): Set<RecipeTab> {
	return new Set([...changedRecipeFields(values, standard)].map(tabOfField));
}

export function recipeDiffersFromStandard(values: RecipeValues, standard: RecipeStandard): boolean {
	return changedRecipeFields(values, standard).size > 0;
}

function withParams(
	values: RecipeValues,
	change: (params: VersionGenerationParams) => VersionGenerationParams
): RecipeValues {
	const params = change({ ...values.genParams });
	return { ...values, genParams: Object.keys(params).length > 0 ? params : null };
}

function withoutKeys(
	params: VersionGenerationParams,
	keys: readonly string[]
): VersionGenerationParams {
	return Object.fromEntries(Object.entries(params).filter(([key]) => !keys.includes(key)));
}

function withoutEngineFields(values: RecipeValues): RecipeValues {
	return withParams(values, (params) => withoutKeys(params, ENGINE_PARAM_KEYS));
}

export function resetRecipeField(
	values: RecipeValues,
	field: RecipeField,
	standard: RecipeStandard
): RecipeValues {
	switch (field) {
		case 'bpm':
			return { ...values, bpm: 0 };
		case 'duration':
			return { ...values, audioDuration: 0 };
		case 'key':
			return { ...values, keyScale: '' };
		case 'model':
			return { ...values, model: standard.model };
		case 'takes':
			return { ...values, takes: RECIPE_TAKES_STANDARD };
		case 'voice':
			return withParams(values, (params) => withoutKeys(params, ['user_lora_id']));
		case 'reference':
			return { ...values, reference: null };
		case 'preset':
			return withoutEngineFields(values);
		default:
			return withParams(values, (params) => withoutKeys(params, [field]));
	}
}

const TAB_FIELDS: Record<RecipeTab, readonly RecipeField[]> = {
	song: SONG_FIELDS,
	generate: GENERATE_FIELDS,
	engine: ['preset']
};

export function resetRecipeTab(
	values: RecipeValues,
	tab: RecipeTab,
	standard: RecipeStandard
): RecipeValues {
	return TAB_FIELDS[tab].reduce((reset, field) => resetRecipeField(reset, field, standard), values);
}

/** Choosing a preset (or Default, with null) replaces exactly the engine fields; Voice and Reference stay. */
export function chooseEnginePreset(
	values: RecipeValues,
	presetParams: VersionGenerationParams | null
): RecipeValues {
	return withParams(withoutEngineFields(values), (params) => {
		for (const key of ENGINE_PARAM_KEYS) {
			const value = presetParams?.[key];
			if (value != null) Object.assign(params, { [key]: value });
		}
		return params;
	});
}

function engineFields(params: VersionGenerationParams | null): VersionGenerationParams {
	return Object.fromEntries(
		Object.entries(params ?? {}).filter(([key, value]) => value != null && isEngineParamKey(key))
	);
}

/** The engine fields alone, as a preset stores them. */
export function engineParams(values: RecipeValues): VersionGenerationParams {
	return engineFields(values.genParams);
}

/** The preset of the recipe's model whose engine fields are the recipe's; Voice and Reference do not count. An empty engine is Default, never a preset. */
export function matchingEnginePreset<
	Preset extends { model_mode: string; params: VersionGenerationParams }
>(values: RecipeValues, presets: readonly Preset[]): Preset | undefined {
	const current = Object.entries(engineParams(values));
	if (current.length === 0) return undefined;
	return presets.find((preset) => {
		if (preset.model_mode !== values.model) return false;
		const stored = engineFields(preset.params);
		return (
			Object.keys(stored).length === current.length &&
			current.every(([key, value]) => (stored as Record<string, unknown>)[key] === value)
		);
	});
}
