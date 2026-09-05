import type { GenerationItem, SongItem } from '$lib/api/types';
import {
	DIT_BOOL_FIELDS,
	DIT_NUMBER_FIELDS,
	DIT_SELECT_FIELDS,
	LM_BOOL_FIELDS,
	LM_NUMBER_FIELDS,
	LM_TEXT_FIELDS
} from '$lib/constants/acestep-param-fields';
import { formatTime } from '$lib/utils/format';

// A read-only account of what a take actually carries — its model, the
// generation_params ParamControls knows how to edit, and the version's own
// bpm/duration/key. Grouped for a listener deciding "why does this take
// sound like this", not for editing (NowPlayingTake, #212).

const RECIPE_TAKE_GROUP_MODEL_LABEL = 'Model & Sampling';
const RECIPE_TAKE_GROUP_REPRODUCIBILITY_LABEL = 'Reproducibility';
const RECIPE_TAKE_GROUP_VERSION_LABEL = 'Version';
const RECIPE_TAKE_GROUP_OTHER_LABEL = 'Other';

export interface RecipeEntry {
	label: string;
	value: string;
}

export interface RecipeGroup {
	label: string;
	entries: RecipeEntry[];
}

type ParamEntries = Map<string, unknown>;

// Every generation_params key ParamControls exposes an editor for, in the
// order ParamControls renders them, next to the exact label it edits it
// under. Reading this instead of a second hand-written list is what keeps a
// take's recipe summary from silently drifting away from what the editor
// actually lets someone change: a param added to ParamControls' registry
// appears here for free, with no touch to this file.
const KNOWN_PARAM_FIELDS = [
	...DIT_NUMBER_FIELDS,
	...DIT_SELECT_FIELDS,
	...DIT_BOOL_FIELDS,
	...LM_NUMBER_FIELDS,
	...LM_BOOL_FIELDS,
	...LM_TEXT_FIELDS
];

// bpm/audio_duration/key_scale live in generation_params (the DiT's actual
// request) but read out under the Version group, not Model & Sampling — they
// describe the song, not how the model rendered it. One list: the loop that
// builds the Version group and the "already accounted for" check below both
// read it, so there's never a second place that has to agree with this one.
const VERSION_PARAM_FIELDS: { key: 'bpm' | 'audio_duration' | 'key_scale'; label: string }[] = [
	{ key: 'bpm', label: 'BPM' },
	{ key: 'audio_duration', label: 'Duration' },
	{ key: 'key_scale', label: 'Key' }
];

// generation_params keys that name something this summary already shows from
// elsewhere on the take, so they'd otherwise duplicate an existing row
// instead of adding information:
//   - acestep_model mirrors generation.model_mode (the Model row) on every
//     take that carries it.
//   - seed is handled explicitly below, next to generation.seed, so it can
//     be compared against the stored seed_value rather than just repeated.
//   - delivered_batch_size is handled explicitly below, next to Batch Size —
//     it isn't an editable knob (ParamControls never lets a user set it), so
//     it doesn't belong in KNOWN_PARAM_FIELDS, but the generic Other fallback
//     would still bury it away from the number it's a reduction of.
const DUPLICATE_PARAM_KEYS = new Set(['acestep_model', 'seed', 'delivered_batch_size']);

function formatParamValue(key: string, rawValue: unknown): string | null {
	if (rawValue === null || rawValue === undefined || rawValue === '') return null;
	if (typeof rawValue === 'boolean') return rawValue ? 'On' : 'Off';
	if (key === 'audio_duration' && typeof rawValue === 'number') return formatTime(rawValue);
	if (typeof rawValue === 'object') return JSON.stringify(rawValue);
	return rawValue.toString();
}

// "cfg_interval_start" -> "Cfg Interval Start" — a generic fallback for a
// generation_params key the registry above doesn't name, so an unrecognized
// param still reads as words instead of disappearing (requirement: nothing a
// take carries is ever hidden).
function prettifyParamKey(key: string): string {
	return key
		.split('_')
		.filter(Boolean)
		.map((word) => word[0].toUpperCase() + word.slice(1))
		.join(' ');
}

export function buildTakeRecipe(generation: GenerationItem, song: SongItem): RecipeGroup[] {
	const params = generation.generation_params ?? {};
	const paramEntries: ParamEntries = new Map(Object.entries(params));
	const groups: RecipeGroup[] = [
		{ label: RECIPE_TAKE_GROUP_MODEL_LABEL, entries: buildModelEntries(generation, paramEntries) },
		{
			label: RECIPE_TAKE_GROUP_REPRODUCIBILITY_LABEL,
			entries: buildReproducibilityEntries(generation, paramEntries)
		},
		{ label: RECIPE_TAKE_GROUP_VERSION_LABEL, entries: buildVersionEntries(song, paramEntries) },
		{ label: RECIPE_TAKE_GROUP_OTHER_LABEL, entries: buildOtherEntries(paramEntries) }
	];

	return groups.filter((group) => group.entries.length > 0);
}

function buildModelEntries(generation: GenerationItem, paramEntries: ParamEntries): RecipeEntry[] {
	const modelEntries: RecipeEntry[] = [];
	if (generation.model_mode) {
		modelEntries.push({ label: 'Model', value: generation.model_mode });
	}
	for (const field of KNOWN_PARAM_FIELDS) {
		const value = formatParamValue(field.key, paramEntries.get(field.key));
		if (value !== null) modelEntries.push({ label: field.label, value });
	}
	// Only present at all when it diverges from the requested Batch Size row
	// above (the backend never persists a match) — a VRAM-guard reduction,
	// issue #211.
	const deliveredBatchSize = formatParamValue(
		'delivered_batch_size',
		paramEntries.get('delivered_batch_size')
	);
	if (deliveredBatchSize !== null) {
		modelEntries.push({ label: 'Delivered Batch Size', value: deliveredBatchSize });
	}
	return modelEntries;
}

function buildReproducibilityEntries(
	generation: GenerationItem,
	paramEntries: ParamEntries
): RecipeEntry[] {
	const reproducibilityEntries: RecipeEntry[] = [];
	if (generation.seed != null) {
		reproducibilityEntries.push({ label: 'Seed', value: String(generation.seed) });
	}
	// The requested seed only earns its own row when it diverges from the
	// stored seed_value above — on a fixed-seed take the two always match, so
	// showing both would just repeat the same number twice.
	const requestedSeed = paramEntries.get('seed');
	if (typeof requestedSeed === 'number' && requestedSeed !== generation.seed) {
		reproducibilityEntries.push({ label: 'Requested Seed', value: String(requestedSeed) });
	}
	return reproducibilityEntries;
}

function buildVersionEntries(song: SongItem, paramEntries: ParamEntries): RecipeEntry[] {
	const versionEntries: RecipeEntry[] = [];
	for (const field of VERSION_PARAM_FIELDS) {
		const value = formatParamValue(field.key, paramEntries.get(field.key));
		if (value !== null) versionEntries.push({ label: field.label, value });
	}
	if (song.vocal_language) {
		versionEntries.push({ label: 'Language', value: song.vocal_language });
	}
	return versionEntries;
}

function buildOtherEntries(paramEntries: ParamEntries): RecipeEntry[] {
	const accountedForKeys = new Set<string>([
		...KNOWN_PARAM_FIELDS.map((field) => field.key),
		...VERSION_PARAM_FIELDS.map((field) => field.key),
		...DUPLICATE_PARAM_KEYS
	]);
	const otherEntries: RecipeEntry[] = [];
	for (const [key, rawValue] of paramEntries) {
		if (accountedForKeys.has(key)) continue;
		const value = formatParamValue(key, rawValue);
		if (value !== null) otherEntries.push({ label: prettifyParamKey(key), value });
	}
	return otherEntries;
}
