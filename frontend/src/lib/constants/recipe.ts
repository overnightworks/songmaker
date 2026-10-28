import type { RecipeField, RecipeTab } from '$lib/utils/recipe-standard';

/** The Takes-per-Generate value the page starts with: the recipe's standard for that field. */
export const RECIPE_TAKES_STANDARD = 1;
export const RECIPE_TAKES_OPTIONS = [1, 2, 3, 5, 10] as const;

export const RECIPE_BPM_MAX = 999;
export const RECIPE_DURATION_MAX_SECONDS = 600;
export const RECIPE_MAX_INFERENCE_STEPS_DEFAULT = 200;

export const RECIPE_RESET_GLYPH = '↺';
export const RECIPE_ENGINE_RESET_TITLE = "Back to the model's default";
export const RECIPE_RESET_ALL_LABEL = 'Reset all';
export const RECIPE_CLOSE_LABEL = 'Close the recipe';
export const RECIPE_TABS_LABEL = 'Recipe sections';
export const RECIPE_SAVED_WITH_VERSION = 'Saved with the version';
export const RECIPE_ENGINE_EMPTY_HINT = "Empty field = the model's default";

export const RECIPE_TAB_LABELS: Record<RecipeTab, string> = {
	song: 'Song',
	generate: 'Generate',
	engine: 'Engine'
};

export const RECIPE_BPM_LABEL = 'BPM';
export const RECIPE_DURATION_LABEL = 'Duration (s)';
export const RECIPE_KEY_LABEL = 'Key';
export const RECIPE_AUTO_LABEL = 'Auto';
export const RECIPE_EMPTY_LABEL = '—';
export const RECIPE_REFERENCE_LABEL = 'Reference track';
export const RECIPE_REFERENCE_UPLOAD = 'Upload audio';
export const RECIPE_REFERENCE_UPLOADING = 'Uploading…';
export const RECIPE_REFERENCE_UPLOAD_ERROR = 'Upload failed';
export const RECIPE_MODEL_LABEL = 'Model';
export const RECIPE_MODEL_LOADING = 'Loading…';
export const RECIPE_MODEL_LOADED = 'Loaded';
export const RECIPE_TAKES_LABEL = 'Takes per Generate';
export const RECIPE_RETRY_LABEL = 'Retry';
export const RECIPE_DEFAULTS_ERROR = 'Failed to load generation defaults';
export const RECIPE_PRESET_LABEL = 'Preset';
export const RECIPE_PRESET_DEFAULT_OPTION = 'Default';
export const RECIPE_PRESET_CUSTOM_OPTION = 'Custom';
export const RECIPE_PRESET_NAME_PLACEHOLDER = 'Preset name';
export const RECIPE_PRESET_SAVE_ERROR = 'Failed to save preset';
export const RECIPE_SAVE_AS_PRESET_LABEL = 'Save as preset';
export const RECIPE_MANAGE_PRESETS_LABEL = 'Manage in Settings → Generation';

/** What each row's ↺ says it returns to. */
export const RECIPE_FIELD_RESET_TITLES: Partial<Record<RecipeField, string>> = {
	bpm: 'Back to Auto',
	duration: 'Back to Auto',
	key: 'Back to empty',
	voice: 'Back to None',
	reference: 'Remove the reference',
	model: 'Back to the first model',
	takes: 'Back to ×1',
	preset: 'Back to Default'
};
export const RECIPE_CHANGED_LABEL = 'changed';
