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

export const RECIPE_TAKE_GROUP_MODEL_LABEL = 'Model & Sampling';
export const RECIPE_TAKE_GROUP_REPRODUCIBILITY_LABEL = 'Reproducibility';
export const RECIPE_TAKE_GROUP_VERSION_LABEL = 'Version';
export const RECIPE_TAKE_GROUP_OTHER_LABEL = 'Other';

export interface RecipeEntry {
	label: string;
	value: string;
}

export interface RecipeGroup {
	label: string;
	entries: RecipeEntry[];
}

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
// describe the song, not how the model rendered it.
const VERSION_PARAM_KEYS = new Set(['bpm', 'audio_duration', 'key_scale']);

function formatParamValue(key: string, rawValue: unknown): string | null {
	if (rawValue === null || rawValue === undefined || rawValue === '') return null;
	if (typeof rawValue === 'boolean') return rawValue ? 'On' : 'Off';
	if (key === 'audio_duration' && typeof rawValue === 'number') return formatTime(rawValue);
	return String(rawValue);
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
	const paramEntries = new Map(Object.entries(params));

	const modelEntries: RecipeEntry[] = [];
	if (generation.model_mode) {
		modelEntries.push({ label: 'Model', value: generation.model_mode });
	}
	for (const field of KNOWN_PARAM_FIELDS) {
		const value = formatParamValue(field.key, paramEntries.get(field.key));
		if (value !== null) modelEntries.push({ label: field.label, value });
	}

	const reproducibilityEntries: RecipeEntry[] = [];
	if (generation.seed != null) {
		reproducibilityEntries.push({ label: 'Seed', value: String(generation.seed) });
	}

	const versionEntries: RecipeEntry[] = [];
	for (const key of ['bpm', 'audio_duration', 'key_scale'] as const) {
		const value = formatParamValue(key, paramEntries.get(key));
		if (value !== null) {
			const label = key === 'bpm' ? 'BPM' : key === 'audio_duration' ? 'Duration' : 'Key';
			versionEntries.push({ label, value });
		}
	}
	if (song.vocal_language) {
		versionEntries.push({ label: 'Language', value: song.vocal_language });
	}

	const knownKeys = new Set<string>([
		...KNOWN_PARAM_FIELDS.map((field) => field.key),
		...VERSION_PARAM_KEYS
	]);
	const otherEntries: RecipeEntry[] = [];
	for (const [key, rawValue] of paramEntries) {
		if (knownKeys.has(key)) continue;
		const value = formatParamValue(key, rawValue);
		if (value !== null) otherEntries.push({ label: prettifyParamKey(key), value });
	}

	const groups: RecipeGroup[] = [
		{ label: RECIPE_TAKE_GROUP_MODEL_LABEL, entries: modelEntries },
		{ label: RECIPE_TAKE_GROUP_REPRODUCIBILITY_LABEL, entries: reproducibilityEntries },
		{ label: RECIPE_TAKE_GROUP_VERSION_LABEL, entries: versionEntries },
		{ label: RECIPE_TAKE_GROUP_OTHER_LABEL, entries: otherEntries }
	];

	return groups.filter((group) => group.entries.length > 0);
}
