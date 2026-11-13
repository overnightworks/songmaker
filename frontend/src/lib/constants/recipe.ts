import type { TextKey } from '#lib/utils/page-words.ts';
import type { RecipeField, RecipeTab } from '#lib/utils/recipe-standard.ts';

/** The Takes-per-Generate value the page starts with: the recipe's standard for that field. */
export const RECIPE_TAKES_STANDARD = 1;
export const RECIPE_TAKES_OPTIONS = [1, 2, 3, 5, 10] as const;

export const RECIPE_BPM_MAX = 999;
export const RECIPE_DURATION_MAX_SECONDS = 600;
export const RECIPE_MAX_INFERENCE_STEPS_DEFAULT = 200;

export const RECIPE_RESET_GLYPH = '↺';

export const RECIPE_TAB_LABELS: Record<RecipeTab, TextKey> = {
	song: 'recipe.tabSong',
	generate: 'recipe.tabGenerate',
	engine: 'recipe.tabEngine'
};

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
