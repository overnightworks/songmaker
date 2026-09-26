import { beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import type { PresetItem } from '$lib/api/types';

const api = vi.hoisted(() => ({
	fetchPresets: vi.fn(),
	fetchBuiltinDefaults: vi.fn(),
	fetchActiveModels: vi.fn(),
	fetchDefaultConfig: vi.fn(),
	fetchGenerationDefaults: vi.fn(),
	updateDefaultConfig: vi.fn(),
	createPreset: vi.fn(),
	updatePreset: vi.fn(),
	deletePresetApi: vi.fn(),
	setPresetDefault: vi.fn()
}));

vi.mock('$lib/api/client', () => api);

import { setDraftGenParams } from '$lib/stores/editor';
import { recipeModel } from '$lib/stores/recipe';
import {
	activeModelIds,
	activeModels,
	activeModelsLoading,
	activeModelsError,
	builtinDefaults,
	currentPreset,
	defaultConfig,
	deletePreset,
	effectiveGenerationDefaults,
	generationDefaultsError,
	loadActiveModels,
	loadBuiltins,
	loadDefaultConfig,
	loadGenerationDefaults,
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
	generationDefaultsError.set(false);
	recipeModel.set(null);
	setDraftGenParams(null);
});

describe('preset store', () => {
	it.each([false, true])('clears loading after a model request (failure: %s)', async (fails) => {
		const response = Promise.withResolvers<[]>();
		api.fetchActiveModels.mockReturnValueOnce(response.promise);
		const request = loadActiveModels();
		expect(get(activeModelsLoading)).toBe(true);
		if (fails) response.reject(new Error('offline'));
		else response.resolve([]);
		await request;
		expect(get(activeModelsLoading)).toBe(false);
		expect(get(activeModelsError)).toBe(fails ? 'Failed to load models' : null);
		api.fetchActiveModels.mockResolvedValueOnce([]);
		await loadActiveModels();
		expect(get(activeModelsError)).toBeNull();
	});

	it('remains loading until overlapping model requests finish', async () => {
		const first = Promise.withResolvers<[]>();
		const second = Promise.withResolvers<[]>();
		api.fetchActiveModels.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
		const firstRequest = loadActiveModels();
		const secondRequest = loadActiveModels();
		first.resolve([]);
		await firstRequest;
		expect(get(activeModelsLoading)).toBe(true);
		second.resolve([]);
		await secondRequest;
		expect(get(activeModelsLoading)).toBe(false);
	});

	it('adopts each successfully loaded settings value', async () => {
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
	});

	it.each([
		[
			'presets',
			() => {
				presets.set([preset('saved')]);
			},
			() => {
				api.fetchPresets.mockRejectedValueOnce(new Error('offline'));
				return loadPresets();
			},
			() => get(presets)
		],
		[
			'builtin defaults',
			() => {
				builtinDefaults.set({ acestep: { inference_steps: 8 } });
			},
			() => {
				api.fetchBuiltinDefaults.mockRejectedValueOnce(new Error('offline'));
				return loadBuiltins();
			},
			() => get(builtinDefaults)
		],
		[
			'active models',
			() => {
				activeModels.set([{ id: 'acestep', is_active: true }]);
			},
			() => {
				api.fetchActiveModels.mockRejectedValueOnce(new Error('offline'));
				return loadActiveModels();
			},
			() => get(activeModels)
		],
		[
			'default config',
			() => {
				defaultConfig.set('acestep');
			},
			() => {
				api.fetchDefaultConfig.mockRejectedValueOnce(new Error('offline'));
				return loadDefaultConfig();
			},
			() => get(defaultConfig)
		],
		[
			'generation defaults',
			() => {
				recipeModel.set('acestep');
				api.fetchGenerationDefaults.mockResolvedValueOnce({ acestep: { inference_steps: 4 } });
				return loadGenerationDefaults();
			},
			() => {
				api.fetchGenerationDefaults.mockRejectedValueOnce(new Error('offline'));
				return loadGenerationDefaults();
			},
			() => get(effectiveGenerationDefaults)
		]
	])('keeps prior %s when loading is unavailable', async (_name, arrange, load, read) => {
		await arrange();
		const previousValue = read();
		await load();
		expect(read()).toEqual(previousValue);
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

	it.each([false, true])(
		'reports generation-defaults availability (failure: %s)',
		async (fails) => {
			if (fails) api.fetchGenerationDefaults.mockRejectedValueOnce(new Error('offline'));
			else api.fetchGenerationDefaults.mockResolvedValueOnce({});
			await loadGenerationDefaults();
			expect(get(generationDefaultsError)).toBe(fails);
			api.fetchGenerationDefaults.mockResolvedValueOnce({});
			await loadGenerationDefaults();
			expect(get(generationDefaultsError)).toBe(false);
		}
	);

	it("merges the current model's builtin defaults with its saved generation defaults", async () => {
		builtinDefaults.set({ acestep: { inference_steps: 8, guidance_scale: 5 } });
		api.fetchGenerationDefaults.mockResolvedValueOnce({ acestep: { inference_steps: 4 } });
		recipeModel.set('acestep');

		await loadGenerationDefaults();

		expect(get(effectiveGenerationDefaults)).toEqual({ inference_steps: 4, guidance_scale: 5 });
	});

	it('finds the saved preset whose params match the current draft for the active model', () => {
		presets.set([
			preset('other-model', { model_mode: 'other', params: { inference_steps: 4 } }),
			preset('match', { model_mode: 'acestep', params: { inference_steps: 4 } })
		]);
		recipeModel.set('acestep');

		setDraftGenParams({ inference_steps: 4 });
		expect(get(currentPreset)?.id).toBe('match');

		setDraftGenParams({ inference_steps: 9 });
		expect(get(currentPreset)).toBeUndefined();
	});
});
