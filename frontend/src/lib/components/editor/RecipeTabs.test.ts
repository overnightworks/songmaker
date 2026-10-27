import { mount, tick, unmount, type ComponentProps } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { uploadReferenceAudio } from '$lib/api/client';
import { ApiError } from '$lib/api/fetch';
import type { PresetItem } from '$lib/api/types';
import {
	activeModels,
	activeModelsError,
	activeModelsLoading,
	builtinDefaults,
	generationDefaultsError,
	presets
} from '$lib/stores/presets';
import { recipeModel } from '$lib/stores/recipe';
import { loras } from '$lib/stores/loras';
import { getByRoleButton } from '$lib/test-utils/accessible-name';
import type { RecipeStandard, RecipeValues } from '$lib/utils/recipe-standard';
import { reactiveProps } from '../../../tests/reactive-fixtures.svelte';
import RecipeTabs from './RecipeTabs.svelte';

vi.mock('$lib/api/client', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/client')>()),
	fetchActiveModels: vi.fn().mockResolvedValue([{ id: 'turbo', is_active: true }]),
	fetchGenerationDefaults: vi.fn().mockResolvedValue({}),
	uploadReferenceAudio: vi.fn()
}));
vi.mock('$lib/api/loras', () => ({ listLoras: vi.fn().mockResolvedValue([]) }));

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
});

describe('RecipeTabs', () => {
	it('shows the tabs Song, Generate and Engine as names only, opened on Song', async () => {
		const target = await renderTabs(atStandard({ bpm: 0 }));
		expect(tabButtons(target).map((el) => el.textContent?.trim())).toEqual([
			'Song',
			'Generate',
			'Engine'
		]);
		expect(recipeTabNamed(target, 'Song').getAttribute('aria-selected')).toBe('true');
		expect(target.querySelector('[data-field="bpm"]')).not.toBeNull();
	});

	it('marks no field, tab or reset at the standard', async () => {
		const target = await renderTabs();
		expect(
			target.querySelector('[data-field-changed], [data-tab-changed], [data-field-reset]')
		).toBeNull();
	});

	it('marks a changed field and its tab, and resets only that field', async () => {
		const target = await renderTabs(atStandard({ bpm: 145, keyScale: 'C' }));
		expect(recipeTabNamed(target, 'Song').querySelector('[data-tab-changed]')).not.toBeNull();
		expect(recipeTabNamed(target, 'Engine').querySelector('[data-tab-changed]')).toBeNull();
		expect(resetButton(target, 'bpm')?.title).toBe('Back to Auto');
		expect(resetButton(target, 'duration')).toBeNull();
		await clickSettled(resetButton(target, 'bpm') as HTMLElement);
		expect(props.values).toEqual(atStandard({ keyScale: 'C' }));
		expect(target.querySelector('[data-field="bpm"] [data-field-changed]')).toBeNull();
		expect(recipeTabNamed(target, 'Song').querySelector('[data-tab-changed]')).not.toBeNull();
	});

	it('Song Reset all touches no other tab', async () => {
		const target = await renderTabs(
			atStandard({ bpm: 145, takes: 3, genParams: { lm_temperature: 0.5 } })
		);
		await clickSettled(getByRoleButton(target, 'Reset all'));
		expect(props.values).toEqual(atStandard({ takes: 3, genParams: { lm_temperature: 0.5 } }));
	});

	it('Generate shows Reset all but not the saved-with-the-version line', async () => {
		const target = await renderTabs(atStandard({ model: 'sft', takes: 3 }));
		await clickSettled(recipeTabNamed(target, 'Generate'));
		expect(target.textContent).not.toContain('Saved with the version');
		await clickSettled(getByRoleButton(target, 'Reset all'));
		expect(props.values).toEqual(atStandard());
	});

	it('sets Takes per Generate from the five choices 1 2 3 5 10', async () => {
		const target = await renderTabs();
		await clickSettled(recipeTabNamed(target, 'Generate'));
		const choices = Array.from(target.querySelectorAll<HTMLButtonElement>('.seg button'));
		expect(choices.map((choice) => choice.textContent)).toEqual(['1', '2', '3', '5', '10']);
		await clickSettled(choices[3]);
		expect(props.values.takes).toBe(5);
		expect(resetButton(target, 'takes')?.title).toBe('Back to ×1');
	});

	it('Engine Reset all keeps Voice and Reference', async () => {
		const target = await renderTabs(
			atStandard({
				genParams: { user_lora_id: 'mara', reference_audio_path: 'a.wav', lm_temperature: 0.5 }
			})
		);
		await clickSettled(recipeTabNamed(target, 'Engine'));
		expect(target.textContent).toContain('Saved with the version');
		await clickSettled(getByRoleButton(target, 'Reset all'));
		expect(props.values.genParams).toEqual({ user_lora_id: 'mara', reference_audio_path: 'a.wav' });
	});

	it('shows an engine field equal to its grey default as unchanged', async () => {
		const target = await renderTabs(atStandard({ genParams: { lm_temperature: 0.85 } }));
		await clickSettled(recipeTabNamed(target, 'Engine'));
		expect(target.querySelector('[data-field-changed]')).toBeNull();
	});

	it('a preset choice replaces the engine fields and keeps Voice', async () => {
		const target = await renderTabs(
			atStandard({ genParams: { user_lora_id: 'mara', lm_temperature: 0.5 } })
		);
		await clickSettled(recipeTabNamed(target, 'Engine'));
		const select = target.querySelector<HTMLSelectElement>(
			'select[aria-label="Preset"]'
		) as HTMLSelectElement;
		select.value = 'warm';
		select.dispatchEvent(new Event('change', { bubbles: true }));
		await tick();
		expect(props.values.genParams).toEqual({ user_lora_id: 'mara', inference_steps: 12 });
	});

	it('the Preset row names the chosen preset while a Voice is set', async () => {
		const target = await renderTabs(
			atStandard({ genParams: { user_lora_id: 'mara', inference_steps: 12 } })
		);
		await clickSettled(recipeTabNamed(target, 'Engine'));
		const select = target.querySelector<HTMLSelectElement>(
			'select[aria-label="Preset"]'
		) as HTMLSelectElement;
		expect(select.value).toBe('warm');
	});

	it('closes from the end of the tab row', async () => {
		const target = await renderTabs();
		await clickSettled(getByRoleButton(target, 'Close the recipe'));
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
		expect(recipeTabNamed(target, 'Generate').getAttribute('aria-selected')).toBe('true');
		await press('End');
		expect(recipeTabNamed(target, 'Engine').getAttribute('aria-selected')).toBe('true');
		await press('ArrowRight');
		expect(recipeTabNamed(target, 'Song').getAttribute('aria-selected')).toBe('true');
		await press('ArrowLeft');
		expect(recipeTabNamed(target, 'Engine').getAttribute('aria-selected')).toBe('true');
		await press('Home');
		expect(recipeTabNamed(target, 'Song').getAttribute('aria-selected')).toBe('true');
	});

	it('shows the models load failure in the Model row with Retry', async () => {
		activeModelsError.set('Failed to load models');
		const target = await renderTabs();
		await clickSettled(recipeTabNamed(target, 'Generate'));
		expect(target.querySelector('[role="alert"]')?.textContent).toBe('Failed to load models');
		expect(getByRoleButton(target, 'Retry')).not.toBeNull();
	});

	it('shows the model as loaded once the models are in', async () => {
		const target = await renderTabs();
		await clickSettled(recipeTabNamed(target, 'Generate'));
		expect(target.textContent).toContain('Loaded');
	});

	it('shows the defaults failure on the Engine tab with Retry', async () => {
		generationDefaultsError.set(true);
		const target = await renderTabs();
		await clickSettled(recipeTabNamed(target, 'Engine'));
		expect(target.querySelector('[role="alert"]')?.textContent).toBe(
			'Failed to load generation defaults'
		);
		expect(getByRoleButton(target, 'Retry')).not.toBeNull();
	});

	it('shows a failed reference upload in the Reference row', async () => {
		vi.mocked(uploadReferenceAudio).mockRejectedValueOnce(
			new ApiError(413, 'Too large', '/upload')
		);
		const target = await renderTabs();
		const file = new File(['x'], 'ref.wav', { type: 'audio/wav' });
		const input = target.querySelector<HTMLInputElement>('input[type="file"]') as HTMLInputElement;
		Object.defineProperty(input, 'files', { value: [file] });
		input.dispatchEvent(new Event('change', { bubbles: true }));
		await vi.waitFor(() => expect(target.querySelector('[role="alert"]')).not.toBeNull());
	});

	it('removes the reference with its reset and keeps the voice', async () => {
		const target = await renderTabs(
			atStandard({ genParams: { user_lora_id: 'mara', reference_audio_path: 'a.wav' } })
		);
		await clickSettled(resetButton(target, 'reference') as HTMLElement);
		expect(props.values.genParams).toEqual({ user_lora_id: 'mara' });
	});

	it('offers no Repaint, Off or Source', async () => {
		const target = await renderTabs();
		for (const name of ['Song', 'Generate', 'Engine']) {
			await clickSettled(recipeTabNamed(target, name));
			expect(target.textContent).not.toMatch(/Repaint|Source|\bOff\b/);
		}
	});
});
