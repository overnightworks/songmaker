import type { TextKey } from '#lib/utils/page-words.ts';
import type { RecipeField, RecipeTab } from '#lib/utils/recipe-standard.ts';

/** The Takes-per-Generate value the page starts with: the recipe's standard for that field. */
export const RECIPE_TAKES_STANDARD = 1;
export const RECIPE_TAKES_OPTIONS = [1, 2, 3, 5, 10] as const;

export const RECIPE_BPM_MAX = 999;
export const RECIPE_DURATION_MAX_SECONDS = 600;
export const RECIPE_MAX_INFERENCE_STEPS_DEFAULT = 200;

export const RECIPE_RESET_GLYPH = '↺';
export const RECIPE_ENGINE_RESET_TITLE = "Back to the model's default";

export const RECIPE_TAB_LABELS: Record<RecipeTab, TextKey> = {
	song: 'recipe.tabSong',
	generate: 'recipe.tabGenerate',
	engine: 'recipe.tabEngine'
};

export const RECIPE_REFERENCE_LABEL = 'Reference track';
export const RECIPE_REFERENCE_UPLOAD = 'Upload audio';
export const RECIPE_REFERENCE_UPLOADING = 'Uploading…';
export const RECIPE_REFERENCE_UPLOAD_ERROR = 'Upload failed';
export const RECIPE_REFERENCE_NONE_LABEL = 'None';
export const RECIPE_REFERENCE_LOADING = 'Loading references…';
export const RECIPE_REFERENCE_LOAD_ERROR = 'Failed to load references';
export const RECIPE_REFERENCE_PLAY_ERROR = "Can't play this recording";
export const RECIPE_REFERENCE_ALL_LABEL = 'All references';

/** The key of what each row's ↺ says it returns to. */
export const RECIPE_FIELD_RESET_TITLES: Partial<Record<RecipeField, TextKey>> = {
	bpm: 'recipe.resetAuto',
	duration: 'recipe.resetAuto',
	key: 'recipe.resetEmpty',
	voice: 'recipe.resetNone',
	reference: 'recipe.resetReference',
	model: 'recipe.resetModel',
	takes: 'recipe.resetTakes',
	preset: 'recipe.resetPreset'
};
export const RECIPE_SOURCE_DURATION_DEFAULT_SECONDS = 180;
/** A frozen duplicate of the catalog key `recipe.panel`, read by NowPlayingTake. */
export const RECIPE_PANEL_LABEL = 'Recipe';
