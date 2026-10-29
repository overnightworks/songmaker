import { mount, tick, unmount } from 'svelte';
import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { makeSong } from '$lib/test-utils/factories';
import {
	editAudioDuration,
	editBpm,
	editGenParams,
	discardDraft,
	loadSongData,
	setDraftBpm,
	setDraftGenParams,
	setDraftReference
} from '$lib/stores/editor';
import { recipeModel, recipeOpen, takesPerGenerate } from '$lib/stores/recipe';
import { activeModels, builtinDefaults, loadActiveModels, presets } from '$lib/stores/presets';
import { loras } from '$lib/stores/loras';
import { fetchBuiltinDefaults, fetchGenerationDefaults, fetchPresets } from '$lib/api/client';
import RecipeLine from './RecipeLine.svelte';

vi.mock('$lib/api/client', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/client')>()),
	fetchActiveModels: vi.fn().mockResolvedValue([
		{ id: 'turbo', is_active: true },
		{ id: 'sft', is_active: true }
	]),
	fetchBuiltinDefaults: vi.fn().mockResolvedValue({ turbo: { lm_temperature: 0.85 } }),
	fetchPresets: vi.fn().mockResolvedValue([]),
	fetchGenerationDefaults: vi.fn().mockResolvedValue({}),
	fetchVersions: vi.fn().mockResolvedValue([])
}));
vi.mock('$lib/api/loras', () => ({ listLoras: vi.fn().mockResolvedValue([]) }));

let mounted: ReturnType<typeof mount>;

beforeEach(async () => {
	vi.mocked(fetchBuiltinDefaults).mockClear();
	vi.mocked(fetchPresets).mockClear();
	vi.mocked(fetchGenerationDefaults).mockClear();
	loadSongData(
		makeSong({
			bpm: 0,
			audio_duration: 0,
			key_scale: '',
			generation_params: null
		})
	);
	discardDraft();
	recipeOpen.set(false);
	recipeModel.set('turbo');
	takesPerGenerate.set(1);
	loras.set([]);
	builtinDefaults.set({});
	presets.set([]);
	await loadActiveModels();
});

afterEach(async () => {
	await unmount(mounted);
	document.body.replaceChildren();
});

async function renderLine(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(RecipeLine, { target });
	await tick();
	await tick();
	return target;
}

const closedLine = (target: HTMLElement) =>
	target.querySelector('.recipe-line') as HTMLButtonElement;
const changedDot = (target: HTMLElement) => target.querySelector('[data-recipe-changed]');

describe('RecipeLine', () => {
	it('is one closed line with no value and no dot at the standard', async () => {
		const target = await renderLine();
		expect(closedLine(target).textContent?.replace(/\s+/g, ' ').trim()).toBe('Recipe ›');
		expect(changedDot(target)).toBeNull();
	});

	it.each([
		['BPM', () => setDraftBpm(145)],
		['an engine field', () => setDraftGenParams({ lm_temperature: 0.5 })],
		['a voice', () => setDraftGenParams({ user_lora_id: 'mara' })],
		['the model', () => recipeModel.set('sft')],
		['takes', () => takesPerGenerate.set(3)]
	])('shows the dot when %s differs from the standard', async (_name, change) => {
		const target = await renderLine();
		change();
		await tick();
		expect(changedDot(target)).not.toBeNull();
	});

	it('shows no dot for an engine field typed equal to its default', async () => {
		const target = await renderLine();
		setDraftGenParams({ lm_temperature: 0.85 });
		await vi.waitFor(() => expect(changedDot(target)).toBeNull());
	});

	it('requests the settings lists only once the card opens', async () => {
		const target = await renderLine();
		const requests = () =>
			[fetchBuiltinDefaults, fetchPresets, fetchGenerationDefaults].map(
				(fetcher) => vi.mocked(fetcher).mock.calls.length
			);
		expect(requests()).toEqual([0, 0, 0]);
		closedLine(target).click();
		await tick();
		await tick();
		expect(requests()).toEqual([1, 1, 1]);
	});

	it.each([
		['a voice', () => setDraftGenParams({ user_lora_id: 'mara' })],
		['a reference', () => setDraftReference({ id: 'r1', filename: 'ref.wav' })]
	])('requests no list for a closed line whose draft holds only %s', async (_name, hold) => {
		hold();
		await renderLine();
		await tick();
		await tick();
		for (const fetcher of [fetchBuiltinDefaults, fetchPresets, fetchGenerationDefaults]) {
			expect(vi.mocked(fetcher)).not.toHaveBeenCalled();
		}
	});

	it('opens into the tabs and closes back to the line', async () => {
		const target = await renderLine();
		closedLine(target).click();
		await tick();
		expect(get(recipeOpen)).toBe(true);
		expect(target.querySelectorAll('[role="tab"]')).toHaveLength(3);
		(target.querySelector('.close') as HTMLButtonElement).click();
		await tick();
		expect(closedLine(target)).not.toBeNull();
	});

	it('moves focus to the Song tab on opening and back to the closed line on closing', async () => {
		const target = await renderLine();
		closedLine(target).focus();
		closedLine(target).click();
		await vi.waitFor(() =>
			expect(document.activeElement).toBe(target.querySelector('[data-tab="song"]'))
		);
		(target.querySelector('.close') as HTMLButtonElement).click();
		await vi.waitFor(() => expect(document.activeElement).toBe(closedLine(target)));
	});

	it('edits the draft through its setters and resets one field with its ↺', async () => {
		recipeOpen.set(true);
		const target = await renderLine();
		const input = target.querySelector<HTMLInputElement>(
			'input[aria-label="BPM"]'
		) as HTMLInputElement;
		input.value = '145';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();
		expect(get(editBpm)).toBe(145);
		(target.querySelector('[data-field-reset="bpm"]') as HTMLButtonElement).click();
		await tick();
		expect(get(editBpm)).toBe(0);
		expect(get(editAudioDuration)).toBe(0);
		expect(target.querySelector('[data-field-reset]')).toBeNull();
	});

	it('Engine Reset all keeps the voice in the draft', async () => {
		setDraftGenParams({ user_lora_id: 'mara', lm_temperature: 0.5 });
		recipeOpen.set(true);
		const target = await renderLine();
		(target.querySelector('[data-tab="engine"]') as HTMLButtonElement).click();
		await tick();
		(target.querySelector('.reset-all') as HTMLButtonElement).click();
		await tick();
		expect(get(editGenParams)).toEqual({ user_lora_id: 'mara' });
		expect(get(activeModels)).toHaveLength(2);
	});
});
