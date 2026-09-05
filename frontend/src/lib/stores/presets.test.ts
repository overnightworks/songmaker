import { beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import type { PresetItem } from '$lib/api/types';

const api = vi.hoisted(() => ({
	fetchPresets: vi.fn(),
	fetchBuiltinDefaults: vi.fn(),
	fetchActiveModels: vi.fn(),
	fetchDefaultConfig: vi.fn(),
	updateDefaultConfig: vi.fn(),
	createPreset: vi.fn(),
	updatePreset: vi.fn(),
	deletePresetApi: vi.fn(),
	setPresetDefault: vi.fn()
}));

vi.mock('$lib/api/client', () => api);

import {
	activeModelIds,
	activeModels,
	builtinDefaults,
	defaultConfig,
	deletePreset,
	loadActiveModels,
	loadBuiltins,
	loadDefaultConfig,
	loadPresets,
	presets,
	saveDefaultConfig,
	savePreset,
	setDefault,
	sharedPresets,
	unsetDefault,
	updateExistingPreset,
	userPresets
} from './presets';

function preset(id: string, overrides: Partial<PresetItem> = {}): PresetItem {
	return {
		id,
		name: id,
		model_mode: 'acestep',
		params: {},
		is_default: false,
		is_shared: false,
		created_at: '',
		updated_at: '',
		...overrides
	};
}

beforeEach(() => {
	vi.clearAllMocks();
	presets.set([]);
	builtinDefaults.set({});
	defaultConfig.set(null);
	activeModels.set([]);
});

describe('preset store', () => {
	it('adopts each successfully loaded settings value while keeping prior state on unavailable responses', async () => {
		api.fetchPresets.mockResolvedValue([preset('mine'), preset('shared', { is_shared: true })]);
		api.fetchBuiltinDefaults.mockResolvedValue({ acestep: { inference_steps: 8 } });
		api.fetchActiveModels.mockResolvedValue([{ id: 'acestep', is_active: true }]);
		api.fetchDefaultConfig.mockResolvedValue({ config: 'acestep' });

		await Promise.all([loadPresets(), loadBuiltins(), loadActiveModels(), loadDefaultConfig()]);
		expect(get(userPresets).map((item) => item.id)).toEqual(['mine']);
		expect(get(sharedPresets).map((item) => item.id)).toEqual(['shared']);
		expect(get(builtinDefaults)).toEqual({ acestep: { inference_steps: 8 } });
		expect(get(activeModelIds)).toEqual(new Set(['acestep']));
		expect(get(defaultConfig)).toBe('acestep');

		api.fetchPresets.mockRejectedValueOnce(new Error('offline'));
		await loadPresets();
		expect(get(presets).map((item) => item.id)).toEqual(['mine', 'shared']);
	});

	it('applies returned default config and preset mutations to the observable store', async () => {
		api.updateDefaultConfig.mockResolvedValue({ config: null });
		await saveDefaultConfig(null);
		expect(get(defaultConfig)).toBeNull();

		api.createPreset.mockResolvedValue(preset('new'));
		await savePreset('New', 'acestep', { inference_steps: 12 });
		expect(get(presets).map((item) => item.id)).toEqual(['new']);

		api.updatePreset.mockResolvedValue(preset('new', { name: 'Renamed' }));
		await updateExistingPreset('new', { name: 'Renamed' });
		expect(get(presets)[0]?.name).toBe('Renamed');

		api.deletePresetApi.mockResolvedValue(undefined);
		await deletePreset('new');
		expect(get(presets)).toEqual([]);
	});

	it('keeps one default per model mode while leaving other modes untouched', async () => {
		presets.set([
			preset('old-default', { is_default: true }),
			preset('new-default'),
			preset('other-mode-default', { model_mode: 'other', is_default: true })
		]);
		api.setPresetDefault.mockResolvedValue(preset('new-default', { is_default: true }));

		await setDefault('new-default');
		expect(get(presets).map(({ id, is_default }) => ({ id, is_default }))).toEqual([
			{ id: 'old-default', is_default: false },
			{ id: 'new-default', is_default: true },
			{ id: 'other-mode-default', is_default: true }
		]);

		api.updatePreset.mockResolvedValue(preset('new-default', { is_default: false }));
		await unsetDefault('new-default');
		expect(get(presets).find((item) => item.id === 'new-default')?.is_default).toBe(false);
	});
});
