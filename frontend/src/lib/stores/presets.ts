import { writable, derived } from 'svelte/store';
import { MODELS_LOAD_ERROR } from '$lib/constants';
import type { PresetItem, VersionGenerationParams } from '$lib/api/types';
import type { AvailableModel } from '$lib/api/client';
import {
	fetchPresets,
	fetchBuiltinDefaults,
	fetchActiveModels,
	fetchDefaultConfig,
	fetchGenerationDefaults,
	updateDefaultConfig as updateDefaultConfigApi,
	createPreset as createPresetApi,
	updatePreset as updatePresetApi,
	deletePresetApi,
	setPresetDefault as setPresetDefaultApi
} from '$lib/api/client';
import { editGenParams } from '$lib/stores/editor';
import { recipeModel } from '$lib/stores/recipe';

export const presets = writable<PresetItem[]>([]);
export const builtinDefaults = writable<Record<string, VersionGenerationParams>>({});
export const defaultConfig = writable<string | null>(null);
export const activeModelsLoading = writable(false);
export const activeModelsError = writable<string | null>(null);
export const activeModels = writable<AvailableModel[]>([]);
export const activeModelIds = derived(activeModels, ($m) => new Set($m.map((m) => m.id)));

export const userPresets = derived(presets, ($p) => $p.filter((p) => !p.is_shared));
export const sharedPresets = derived(presets, ($p) => $p.filter((p) => p.is_shared));

export async function loadPresets(): Promise<void> {
	try {
		const data = await fetchPresets();
		presets.set(data);
	} catch {
		/* presets unavailable */
	}
}

export async function loadBuiltins(): Promise<void> {
	try {
		const data = await fetchBuiltinDefaults();
		builtinDefaults.set(data);
	} catch {
		/* builtins unavailable */
	}
}

let activeModelLoads = 0;

export async function loadActiveModels(): Promise<void> {
	activeModelLoads += 1;
	activeModelsLoading.set(true);
	activeModelsError.set(null);
	try {
		const data = await fetchActiveModels();
		activeModels.set(data);
	} catch {
		activeModelsError.set(MODELS_LOAD_ERROR);
	} finally {
		activeModelLoads -= 1;
		activeModelsLoading.set(activeModelLoads > 0);
	}
}

export async function loadDefaultConfig(): Promise<void> {
	try {
		const res = await fetchDefaultConfig();
		defaultConfig.set(res.config);
	} catch {
		/* default config unavailable */
	}
}

export async function saveDefaultConfig(config: string | null): Promise<void> {
	const res = await updateDefaultConfigApi(config);
	defaultConfig.set(res.config);
}

export async function savePreset(
	name: string,
	mode: string,
	params: VersionGenerationParams,
	isDefault: boolean = false
): Promise<void> {
	const preset = await createPresetApi(name, mode, params, isDefault);
	presets.update((list) => [...list, preset]);
}

export async function updateExistingPreset(
	presetId: string,
	data: { name?: string; params?: VersionGenerationParams; is_default?: boolean }
): Promise<void> {
	const updated = await updatePresetApi(presetId, data);
	presets.update((list) => list.map((p) => (p.id === updated.id ? updated : p)));
}

export async function setDefault(presetId: string): Promise<void> {
	const updated = await setPresetDefaultApi(presetId);
	presets.update((list) =>
		list.map((p) => {
			if (p.id === updated.id) return updated;
			if (p.model_mode === updated.model_mode && p.is_default) return { ...p, is_default: false };
			return p;
		})
	);
}

export async function unsetDefault(presetId: string): Promise<void> {
	const updated = await updatePresetApi(presetId, { is_default: false });
	presets.update((list) => list.map((p) => (p.id === updated.id ? updated : p)));
}

export async function deletePreset(presetId: string): Promise<void> {
	await deletePresetApi(presetId);
	presets.update((list) => list.filter((p) => p.id !== presetId));
}

const generationDefaults = writable<Record<string, VersionGenerationParams>>({});
export const generationDefaultsError = writable(false);

export async function loadGenerationDefaults(): Promise<void> {
	generationDefaultsError.set(false);
	try {
		const data = await fetchGenerationDefaults();
		generationDefaults.set(data);
	} catch {
		generationDefaultsError.set(true);
	}
}

export const effectiveGenerationDefaults = derived(
	[builtinDefaults, generationDefaults, recipeModel],
	([$builtinDefaults, $generationDefaults, $recipeModel]) =>
		({
			...($builtinDefaults[$recipeModel ?? ''] ?? {}),
			...($generationDefaults[$recipeModel ?? ''] ?? {})
		}) as Required<VersionGenerationParams>
);

function presetParamsEqual(a: VersionGenerationParams, b: VersionGenerationParams): boolean {
	const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
	for (const key of keys) {
		if ((a as Record<string, unknown>)[key] !== (b as Record<string, unknown>)[key]) return false;
	}
	return true;
}

export const currentPreset = derived(
	[presets, recipeModel, editGenParams],
	([$presets, $recipeModel, $editGenParams]) =>
		$presets.find(
			(p) => p.model_mode === $recipeModel && presetParamsEqual(p.params, $editGenParams ?? {})
		)
);
