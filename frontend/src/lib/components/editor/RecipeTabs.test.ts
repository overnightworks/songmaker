import { mount, tick, unmount, type ComponentProps } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createPreset, fetchActiveModels, fetchGenerationDefaults } from '#lib/api/client.ts';
import { goto } from '$app/navigation';
import { ApiError, NetworkError } from '#lib/api/fetch.ts';
import type { PresetItem } from '#lib/api/types.ts';
import {
	activeModels,
	activeModelsError,
	activeModelsLoading,
	builtinDefaults,
	generationDefaultsError,
	presets
} from '#lib/stores/presets.ts';
import { discardDraft, loadSongData, setDraftLyrics } from '#lib/stores/editor.ts';
import { pendingDirtyNavigation } from '#lib/stores/navigation.ts';
import { recipeModel } from '#lib/stores/recipe.ts';
import { makeSong } from '#lib/test-utils/factories.ts';
import { get } from 'svelte/store';
import { loras } from '#lib/stores/loras.ts';
import { getByRoleButton } from '#lib/test-utils/accessible-name.ts';
import type { RecipeStandard, RecipeValues } from '#lib/utils/recipe-standard.ts';
import { reactiveProps } from '../../../tests/reactive-fixtures.svelte';
import { words } from '#lib/words/en.ts';
import RecipeTabs from './RecipeTabs.svelte';

vi.mock('#lib/api/client.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/client.ts')>()),
	fetchActiveModels: vi.fn().mockResolvedValue([{ id: 'turbo', is_active: true }]),
	fetchGenerationDefaults: vi.fn().mockResolvedValue({}),
	fetchVersions: vi.fn().mockResolvedValue([]),
	createPreset: vi.fn()
}));
vi.mock('#lib/api/loras.ts', () => ({ listLoras: vi.fn().mockResolvedValue([]) }));

const modelStandard: RecipeStandard = {
	model: 'turbo',
	engineDefaults: { lm_temperature: 0.85, inference_steps: 8 }
};
const warmPreset = {
	id: 'warm',
	name: 'Warm',
	model_mode: 'turbo',
	is_shared: false,
	params: { inference_steps: 12, user_lora_id: 'ignored' }
} as unknown as PresetItem;

let mounted: ReturnType<typeof mount>;
let props: ComponentProps<typeof RecipeTabs>;
const onchange = vi.fn();
const onclose = vi.fn();

function atStandard(overrides: Partial<RecipeValues> = {}): RecipeValues {
	return {
		bpm: 0,
		audioDuration: 0,
		keyScale: '',
		genParams: null,
		reference: null,
		model: 'turbo',
		takes: 1,
		...overrides
	};
}

async function renderTabs(values: RecipeValues = atStandard()): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	props = reactiveProps({ values, standard: modelStandard, onchange, onclose });
	onchange.mockImplementation((next: RecipeValues) => (props.values = next));
	mounted = mount(RecipeTabs, { target, props });
	await tick();
	return target;
}

async function clickSettled(button: HTMLElement): Promise<void> {
	button.click();
	await tick();
	await Promise.resolve();
	await tick();
}

const tabButtons = (target: HTMLElement) =>
	Array.from(target.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
const recipeTabNamed = (target: HTMLElement, name: string) =>
	tabButtons(target).find((el) => el.textContent?.includes(name)) as HTMLButtonElement;
const resetButton = (target: HTMLElement, field: string) =>
	target.querySelector<HTMLButtonElement>(`[data-field-reset="${field}"]`);

beforeEach(() => {
	vi.clearAllMocks();
	activeModels.set([{ id: 'turbo', is_active: true }]);
	activeModelsLoading.set(false);
	activeModelsError.set(null);
	generationDefaultsError.set(false);
	builtinDefaults.set({});
	presets.set([warmPreset]);
	loras.set([]);
	recipeModel.set('turbo');
});

afterEach(async () => {
	await unmount(mounted);
	document.body.replaceChildren();
	discardDraft();
	pendingDirtyNavigation.set(null);
});

describe('RecipeTabs', () => {
	it('shows the tabs Song, Generate and Engine as names only, opened on Song', async () => {
		const target = await renderTabs(atStandard({ bpm: 0 }));
		expect(tabButtons(target).map((el) => el.textContent?.trim())).toEqual([
			words['recipe.tabSong'],
			words['recipe.tabGenerate'],
			words['recipe.tabEngine']
		]);
		expect(recipeTabNamed(target, words['recipe.tabSong']).getAttribute('aria-selected')).toBe(
			'true'
		);
		expect(target.querySelector('[data-field="bpm"]')).not.toBeNull();
	});

	it('marks no field, tab or reset at the standard', async () => {
		const target = await renderTabs();
		expect(
			target.querySelector('[data-field-changed], [data-tab-changed], [data-field-reset]')
		).toBeNull();
	});

	it('returns a changed Duration to Auto', async () => {
		const target = await renderTabs(atStandard({ audioDuration: 180 }));
		expect(resetButton(target, 'duration')?.title).toBe(words['recipe.resetAuto']);
		await clickSettled(resetButton(target, 'duration') as HTMLElement);
		expect(props.values).toEqual(atStandard());
	});

	it('marks a changed field and its tab, and resets only that field', async () => {
		const target = await renderTabs(atStandard({ bpm: 145, keyScale: 'C' }));
		expect(
			recipeTabNamed(target, words['recipe.tabSong']).querySelector('[data-tab-changed]')
		).not.toBeNull();
		expect(
			recipeTabNamed(target, words['recipe.tabEngine']).querySelector('[data-tab-changed]')
		).toBeNull();
		expect(resetButton(target, 'bpm')?.title).toBe(words['recipe.resetAuto']);
		expect(resetButton(target, 'duration')).toBeNull();
		await clickSettled(resetButton(target, 'bpm') as HTMLElement);
		expect(props.values).toEqual(atStandard({ keyScale: 'C' }));
		expect(target.querySelector('[data-field="bpm"] [data-field-changed]')).toBeNull();
		expect(
			recipeTabNamed(target, words['recipe.tabSong']).querySelector('[data-tab-changed]')
		).not.toBeNull();
	});

	it('Song Reset all touches no other tab', async () => {
		const target = await renderTabs(
			atStandard({ bpm: 145, takes: 3, genParams: { lm_temperature: 0.5 } })
		);
		await clickSettled(getByRoleButton(target, words['recipe.resetAll']));
		expect(props.values).toEqual(atStandard({ takes: 3, genParams: { lm_temperature: 0.5 } }));
	});

	it('Generate shows Reset all but not the saved-with-the-version line', async () => {
		const target = await renderTabs(atStandard({ model: 'sft', takes: 3 }));
		await clickSettled(recipeTabNamed(target, words['recipe.tabGenerate']));
		expect(target.textContent).not.toContain(words['recipe.savedWithVersion']);
		await clickSettled(getByRoleButton(target, words['recipe.resetAll']));
		expect(props.values).toEqual(atStandard());
	});

	it('sets Takes per Generate from the five choices 1 2 3 5 10', async () => {
		const target = await renderTabs();
		await clickSettled(recipeTabNamed(target, words['recipe.tabGenerate']));
		const choices = Array.from(target.querySelectorAll<HTMLButtonElement>('.seg button'));
		expect(choices.map((choice) => choice.textContent)).toEqual(['1', '2', '3', '5', '10']);
		await clickSettled(choices[3]);
		expect(props.values.takes).toBe(5);
		expect(resetButton(target, 'takes')?.title).toBe(words['recipe.resetTakes']);
	});

	it('Engine Reset all keeps Voice and Reference', async () => {
		const target = await renderTabs(
			atStandard({
				genParams: { user_lora_id: 'mara', lm_temperature: 0.5 },
				reference: { id: 'r1', filename: 'a.wav' }
			})
		);
		await clickSettled(recipeTabNamed(target, words['recipe.tabEngine']));
		expect(target.textContent).toContain(words['recipe.savedWithVersion']);
		await clickSettled(getByRoleButton(target, words['recipe.resetAll']));
		expect(props.values.genParams).toEqual({ user_lora_id: 'mara' });
		expect(props.values.reference).toEqual({ id: 'r1', filename: 'a.wav' });
	});

	it('shows an engine field equal to its grey default as unchanged', async () => {
		const target = await renderTabs(atStandard({ genParams: { lm_temperature: 0.85 } }));
		await clickSettled(recipeTabNamed(target, words['recipe.tabEngine']));
		expect(target.querySelector('[data-field-changed]')).toBeNull();
	});

	it('a preset choice replaces the engine fields and keeps Voice', async () => {
		const target = await renderTabs(
			atStandard({ genParams: { user_lora_id: 'mara', lm_temperature: 0.5 } })
		);
		await clickSettled(recipeTabNamed(target, words['recipe.tabEngine']));
		const select = target.querySelector<HTMLSelectElement>(
			`select[aria-label="${words['recipe.preset']}"]`
		) as HTMLSelectElement;
		select.value = 'warm';
		select.dispatchEvent(new Event('change', { bubbles: true }));
		await tick();
		expect(props.values.genParams).toEqual({ user_lora_id: 'mara', inference_steps: 12 });
	});

	it('a hand-edited engine field reads Custom on the Preset row and its undo returns the engine to Default', async () => {
		const target = await renderTabs(
			atStandard({ genParams: { user_lora_id: 'mara', lm_temperature: 0.5 } })
		);
		await clickSettled(recipeTabNamed(target, words['recipe.tabEngine']));
		const select = target.querySelector<HTMLSelectElement>(
			`select[aria-label="${words['recipe.preset']}"]`
		) as HTMLSelectElement;
		const row = target.querySelector('[data-field="preset"]') as HTMLElement;
		expect(select.selectedOptions[0].textContent).toBe(words['recipe.presetCustom']);
		expect(row.querySelector('[data-field-changed]')).not.toBeNull();
		const undo = resetButton(target, 'preset') as HTMLButtonElement;
		expect(undo.title).toBe(words['recipe.resetPreset']);
		await clickSettled(undo);
		expect(props.values.genParams).toEqual({ user_lora_id: 'mara' });
		expect(select.selectedOptions[0].textContent).toBe(words['recipe.presetDefault']);
	});

	it('the Preset row names the chosen preset while a Voice is set', async () => {
		const target = await renderTabs(
			atStandard({ genParams: { user_lora_id: 'mara', inference_steps: 12 } })
		);
		await clickSettled(recipeTabNamed(target, words['recipe.tabEngine']));
		const select = target.querySelector<HTMLSelectElement>(
			`select[aria-label="${words['recipe.preset']}"]`
		) as HTMLSelectElement;
		expect(select.value).toBe('warm');
	});

	it('closes from the end of the tab row', async () => {
		const target = await renderTabs();
		await clickSettled(getByRoleButton(target, words['recipe.close']));
		expect(onclose).toHaveBeenCalledTimes(1);
	});

	it('names a panel in aria-controls only on the selected tab', async () => {
		const target = await renderTabs();
		const controls = tabButtons(target).map((el) => el.getAttribute('aria-controls'));
		expect(controls).toEqual(['recipe-panel', null, null]);
		expect(target.querySelector('#recipe-panel')).not.toBeNull();
	});

	it('moves between tabs with the arrows, Home and End', async () => {
		const target = await renderTabs();
		const press = async (key: string) => {
			const current = target.querySelector<HTMLButtonElement>('[role="tab"][tabindex="0"]');
			current?.dispatchEvent(
				new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true })
			);
			await tick();
		};
		await press('ArrowRight');
		expect(recipeTabNamed(target, words['recipe.tabGenerate']).getAttribute('aria-selected')).toBe(
			'true'
		);
		await press('End');
		expect(recipeTabNamed(target, words['recipe.tabEngine']).getAttribute('aria-selected')).toBe(
			'true'
		);
		await press('ArrowRight');
		expect(recipeTabNamed(target, words['recipe.tabSong']).getAttribute('aria-selected')).toBe(
			'true'
		);
		await press('ArrowLeft');
		expect(recipeTabNamed(target, words['recipe.tabEngine']).getAttribute('aria-selected')).toBe(
			'true'
		);
		await press('Home');
		expect(recipeTabNamed(target, words['recipe.tabSong']).getAttribute('aria-selected')).toBe(
			'true'
		);
	});

	it('shows the models load failure in the Model row with Retry', async () => {
		activeModelsError.set('Failed to load models');
		const target = await renderTabs();
		await clickSettled(recipeTabNamed(target, words['recipe.tabGenerate']));
		expect(target.querySelector('[role="alert"]')?.textContent).toBe('Failed to load models');
		vi.mocked(fetchActiveModels).mockResolvedValueOnce([{ id: 'turbo', is_active: true }]);
		await clickSettled(getByRoleButton(target, words['recipe.retry']));
		await vi.waitFor(() => expect(target.querySelector('[role="alert"]')).toBeNull());
	});

	it('shows Loading with the Model select disabled while the models load', async () => {
		activeModels.set([]);
		activeModelsLoading.set(true);
		const target = await renderTabs(atStandard({ model: null }));
		await clickSettled(recipeTabNamed(target, words['recipe.tabGenerate']));
		const select = target.querySelector<HTMLSelectElement>(
			`select[aria-label="${words['recipe.model']}"]`
		) as HTMLSelectElement;
		expect(select.selectedOptions[0].textContent).toBe(words['recipe.modelLoading']);
		expect(select.disabled).toBe(true);
	});

	it('shows None with the Model select disabled when no model is active', async () => {
		activeModels.set([]);
		const target = await renderTabs(atStandard({ model: null }));
		await clickSettled(recipeTabNamed(target, words['recipe.tabGenerate']));
		const select = target.querySelector<HTMLSelectElement>(
			`select[aria-label="${words['recipe.model']}"]`
		) as HTMLSelectElement;
		expect(select.selectedOptions[0].textContent).toBe(words['recipe.none']);
		expect(select.disabled).toBe(true);
	});

	it('shows the model as loaded once the models are in', async () => {
		const target = await renderTabs();
		await clickSettled(recipeTabNamed(target, words['recipe.tabGenerate']));
		expect(target.textContent).toContain(words['recipe.modelLoaded']);
	});

	it('shows the defaults failure on the Engine tab with Retry', async () => {
		generationDefaultsError.set(true);
		const target = await renderTabs();
		await clickSettled(recipeTabNamed(target, words['recipe.tabEngine']));
		expect(target.querySelector('[role="alert"]')?.textContent).toBe(words['recipe.defaultsError']);
		await clickSettled(getByRoleButton(target, words['recipe.retry']));
		await vi.waitFor(() => expect(target.querySelector('[role="alert"]')).toBeNull());
		expect(fetchGenerationDefaults).toHaveBeenCalled();
	});

	it.each([
		{
			failure: 'with no network answer',
			error: new NetworkError('/api/presets', new TypeError('Failed to fetch')),
			shown: words['recipe.presetSaveError']
		},
		{
			failure: 'refused by the server',
			error: new ApiError(409, 'That preset name is taken', '/api/presets'),
			shown: 'That preset name is taken'
		}
	])(
		'says $shown on the Preset row when saving a preset fails $failure and keeps the draft',
		async ({ error, shown }) => {
			vi.mocked(createPreset).mockRejectedValueOnce(error);
			const start = atStandard({ genParams: { lm_temperature: 0.5 } });
			const target = await renderTabs(start);
			await clickSettled(recipeTabNamed(target, words['recipe.tabEngine']));
			await clickSettled(getByRoleButton(target, words['recipe.saveAsPreset']));
			const name = target.querySelector<HTMLInputElement>(
				`input[aria-label="${words['recipe.presetNamePlaceholder']}"]`
			) as HTMLInputElement;
			name.value = 'Night drive';
			name.dispatchEvent(new Event('input', { bubbles: true }));
			await clickSettled(getByRoleButton(target, words['recipe.presetSave']));
			await vi.waitFor(() =>
				expect(
					Array.from(target.querySelectorAll('[role="alert"]')).map((el) => el.textContent)
				).toEqual([shown])
			);
			expect(props.values).toEqual(start);
		}
	);

	it('holds Manage presets for the unsaved-changes dialog while the song has a dirty draft', async () => {
		loadSongData(makeSong({ slug: 'test', lyrics: 'hello' }));
		setDraftLyrics('unsaved edit');
		const target = await renderTabs();
		await clickSettled(recipeTabNamed(target, words['recipe.tabEngine']));
		const manage = Array.from(target.querySelectorAll<HTMLAnchorElement>('a')).find(
			(link) => link.textContent === words['recipe.managePresets']
		) as HTMLAnchorElement;
		manage.click();
		await tick();
		expect(get(pendingDirtyNavigation)).not.toBeNull();
		expect(vi.mocked(goto)).not.toHaveBeenCalled();
	});

	it('shows Default, with no dot and no undo, for an empty engine beside a preset saved with empty engine fields', async () => {
		presets.set([{ ...warmPreset, id: 'bare', name: 'Bare', params: {} } as PresetItem]);
		const target = await renderTabs(atStandard({ genParams: { lm_temperature: 0.5 } }));
		await clickSettled(recipeTabNamed(target, words['recipe.tabEngine']));
		const select = target.querySelector<HTMLSelectElement>(
			`select[aria-label="${words['recipe.preset']}"]`
		) as HTMLSelectElement;
		await clickSettled(resetButton(target, 'preset') as HTMLElement);
		expect(select.selectedOptions[0].textContent).toBe(words['recipe.presetDefault']);
		expect(target.querySelector('[data-field="preset"] [data-field-changed]')).toBeNull();
		expect(resetButton(target, 'preset')).toBeNull();
		props.values = atStandard({ genParams: { lm_temperature: 0.5 } });
		await tick();
		expect(select.selectedOptions[0].textContent).toBe(words['recipe.presetCustom']);
		const resetAll = getByRoleButton(target, words['recipe.resetAll']) as HTMLButtonElement;
		expect(resetAll.disabled).toBe(false);
		await clickSettled(resetAll);
		expect(props.values.genParams).toBeNull();
		expect(select.selectedOptions[0].textContent).toBe(words['recipe.presetDefault']);
	});

	it('removes the reference with its reset and keeps the voice', async () => {
		const target = await renderTabs(
			atStandard({
				genParams: { user_lora_id: 'mara' },
				reference: { id: 'r1', filename: 'a.wav' }
			})
		);
		await clickSettled(resetButton(target, 'reference') as HTMLElement);
		expect(props.values.genParams).toEqual({ user_lora_id: 'mara' });
		expect(props.values.reference).toBeNull();
	});

	it('offers no Repaint, Off or Source', async () => {
		const target = await renderTabs();
		for (const name of [
			words['recipe.tabSong'],
			words['recipe.tabGenerate'],
			words['recipe.tabEngine']
		]) {
			await clickSettled(recipeTabNamed(target, name));
			expect(target.textContent).not.toMatch(/Repaint|Source|\bOff\b/);
		}
	});
});
