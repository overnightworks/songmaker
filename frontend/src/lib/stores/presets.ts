import { writable, derived } from 'svelte/store';
import type { PresetItem, VersionGenerationParams } from '$lib/api/types';
import {
	fetchPresets,
	fetchBuiltinDefaults,
	fetchDefaultConfig,
	updateDefaultConfig as updateDefaultConfigApi,
	createPreset as createPresetApi,
	updatePreset as updatePresetApi,
	deletePresetApi,
	setPresetDefault as setPresetDefaultApi
} from '$lib/api/client';

export const presets = writable<PresetItem[]>([]);
export const builtinDefaults = writable<Record<string, VersionGenerationParams>>({});
export const defaultConfig = writable<string | null>(null);

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
