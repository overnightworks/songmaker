import { mount, tick, unmount } from 'svelte';
import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getByRoleButton } from '$lib/test-utils/accessible-name';
import { makeGeneration, makeSong } from '$lib/test-utils/factories';
import {
	editBpm,
	editAudioDuration,
	editKeyScale,
	editGenParams,
	pinnedSeed,
	loadSongData,
	setDraftGenParams
} from '$lib/stores/editor';
import {
	recipeModel,
	recipeOpen,
	takesPerGenerate,
	sourceGeneration,
	sourceMode,
	coverStrength,
	coverNoiseStrength,
	repaintMode,
	repaintStrength,
	repaintStart,
	setSourceFromGeneration
} from '$lib/stores/recipe';
import { activeModels, loadActiveModels } from '$lib/stores/presets';
import { loras } from '$lib/stores/loras';
import { fetchActiveModels, fetchGenerationDefaults, uploadReferenceAudio } from '$lib/api/client';
import PhoneRecipeSection from './PhoneRecipeSection.svelte';

vi.mock('$lib/api/client', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/client')>()),
	fetchVersions: vi.fn().mockResolvedValue([]),
	fetchActiveModels: vi.fn().mockResolvedValue([{ id: 'turbo', is_active: true }]),
	fetchBuiltinDefaults: vi.fn().mockResolvedValue({}),
	fetchPresets: vi.fn().mockResolvedValue([
		{
			id: 'warm',
			name: 'Warm',
			model_mode: 'turbo',
			params: { inference_steps: 12 }
		}
	]),
	fetchGenerationDefaults: vi.fn().mockResolvedValue({}),
	uploadReferenceAudio: vi.fn()
}));
vi.mock('$lib/api/loras', () => ({ listLoras: vi.fn().mockResolvedValue([]) }));

let mounted: ReturnType<typeof mount>;

beforeEach(async () => {
	vi.clearAllMocks();
	vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
	loadSongData(
		makeSong({ bpm: 120, audio_duration: 180, key_scale: 'Am', generation_params: null })
	);
	recipeOpen.set(false);
	recipeModel.set('turbo');
	takesPerGenerate.set(1);
	pinnedSeed.set(null);
	sourceGeneration.set(null);
	loras.set([]);
	await loadActiveModels();
});

afterEach(async () => {
	await unmount(mounted);
	document.body.replaceChildren();
	vi.restoreAllMocks();
	vi.unstubAllGlobals();
});

async function render() {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(PhoneRecipeSection, { target });
	await tick();
	await tick();
	return target;
}

async function click(target: HTMLElement, name: string) {
	getByRoleButton(target, name).click();
	await tick();
}

describe('PhoneRecipeSection', () => {
	it('starts with one summary and expands exactly one field at a time inline', async () => {
		const target = await render();
		expect(target.textContent).toContain('TURBO · 180 s · 120 BPM · Am · ×1');
		expect(target.querySelectorAll('button')).toHaveLength(1);
		await click(target, 'Recipe');
		expect(target.querySelector('.recipe-row')?.getAttribute('aria-label')).toBe('Model');
		await click(target, 'BPM');
		expect(target.querySelector('input[aria-label="BPM"]')).not.toBeNull();
		await click(target, 'Key');
		expect(target.querySelector('input[aria-label="BPM"]')).toBeNull();
		expect(target.querySelector('input[aria-label="Key"]')).not.toBeNull();
		await click(target, 'Key');
		expect(target.querySelector('input')).toBeNull();
		await click(target, 'Recipe');
		expect(target.querySelectorAll('button')).toHaveLength(1);
		expect(target.querySelector('[role="dialog"]')).toBeNull();
	});

	it.each([
		['BPM', '96', 'input', () => get(editBpm), 96],
		['Duration', '200', 'input', () => get(editAudioDuration), 200],
		['Key', 'C major', 'input', () => get(editKeyScale), 'C major'],
		['Takes', '3', 'change', () => get(takesPerGenerate), 3],
		['Model', 'sft', 'change', () => get(recipeModel), 'sft']
	] as const)(
		'edits %s through its inline control',
		async (label, value, event, read, expected) => {
			activeModels.set([
				{ id: 'turbo', is_active: true },
				{ id: 'sft', is_active: true }
			]);
			const target = await render();
			await click(target, 'Recipe');
			await click(target, label);
			const control = target.querySelector<HTMLInputElement | HTMLSelectElement>(
				`.field-editor [aria-label="${label}"]`
			) as HTMLInputElement | HTMLSelectElement;
			control.value = value;
			control.dispatchEvent(new Event(event, { bubbles: true }));
			await tick();
			expect(read()).toBe(expected);
		}
	);

	it('shows loading, load failure, retry, empty and ready model states', async () => {
		const response = Promise.withResolvers<[]>();
		vi.mocked(fetchActiveModels).mockReturnValueOnce(response.promise);
		const request = loadActiveModels();
		const target = await render();
		await click(target, 'Recipe');
		expect(getByRoleButton(target, 'Model').textContent).toContain('Loading…');
		await click(target, 'Model');
		expect(target.querySelector<HTMLSelectElement>('select')?.disabled).toBe(true);
		response.reject(new Error('offline'));
		await request;
		await tick();
		expect(target.querySelector('[role="alert"]')?.textContent).toBe('Failed to load models');
		vi.mocked(fetchActiveModels).mockResolvedValueOnce([]);
		await click(target, 'Retry');
		await tick();
		expect(getByRoleButton(target, 'Model').textContent).toContain('None');
		await loadActiveModels();
		await tick();
		expect(getByRoleButton(target, 'Model').textContent).toContain('Loaded');
		expect(target.querySelector('[role="alert"]')).toBeNull();
	});

	it('pins, edits and releases a seed', async () => {
		const target = await render();
		await click(target, 'Recipe');
		await click(target, 'Seed');
		await click(target, 'Pinned');
		const input = target.querySelector<HTMLInputElement>(
			'input[aria-label="Seed"]'
		) as HTMLInputElement;
		input.value = '42';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();
		expect(get(pinnedSeed)).toBe(42);
		expect(getByRoleButton(target, 'Seed').textContent).toContain('Pinned 42');
		await click(target, 'Random');
		expect(get(pinnedSeed)).toBeNull();
		expect(target.querySelector('input')).toBeNull();
	});

	it('uses the voice picker to remove the selected voice inline', async () => {
		setDraftGenParams({ user_lora_id: 'old', inference_steps: 12 });
		const target = await render();
		await click(target, 'Recipe');
		await click(target, 'Voice');
		expect(target.querySelector('.voice-picker')).not.toBeNull();
		(target.querySelector<HTMLButtonElement>('.picker') as HTMLButtonElement).click();
		await tick();
		(target.querySelector<HTMLButtonElement>('[role="option"]') as HTMLButtonElement).click();
		await tick();
		expect(get(editGenParams)).toEqual({ inference_steps: 12 });
		expect(getByRoleButton(target, 'Voice').textContent).toContain('None');
	});

	it('applies a preset and edits its parameters through the existing controls', async () => {
		const target = await render();
		await click(target, 'Recipe');
		await click(target, 'Preset');
		const select = target.querySelector<HTMLSelectElement>('select') as HTMLSelectElement;
		select.value = 'warm';
		select.dispatchEvent(new Event('change', { bubbles: true }));
		await tick();
		expect(get(editGenParams)).toEqual({ inference_steps: 12 });
		await click(target, 'LM / DiT');
		const setting = [...target.querySelectorAll('label')].find((label) =>
			label.textContent?.includes('Inference Steps')
		) as HTMLLabelElement;
		const input = setting.querySelector('input') as HTMLInputElement;
		input.value = '16';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();
		expect(get(editGenParams)?.inference_steps).toBe(16);
		await click(target, 'Preset');
		const customPreset = target.querySelector<HTMLSelectElement>('select') as HTMLSelectElement;
		expect(customPreset.selectedOptions[0].textContent).toBe('Custom');
		customPreset.value = '';
		customPreset.dispatchEvent(new Event('change', { bubbles: true }));
		await tick();
		expect(get(editGenParams)).toBeNull();
	});

	it('reports unavailable generation defaults and reloads them', async () => {
		vi.mocked(fetchGenerationDefaults).mockRejectedValueOnce(new Error('offline'));
		const target = await render();
		await click(target, 'Recipe');
		await click(target, 'LM / DiT');
		expect(target.querySelector('[role="alert"]')?.textContent).toContain(
			'Failed to load generation defaults'
		);
		await click(target, 'Retry');
		await tick();
		expect(target.querySelector('[role="alert"]')).toBeNull();
	});

	it.each([false, true])('handles a reference upload (failure: %s)', async (fails) => {
		const response = Promise.withResolvers<{ path: string; filename: string }>();
		vi.mocked(uploadReferenceAudio).mockReturnValueOnce(response.promise);
		const target = await render();
		await click(target, 'Recipe');
		await click(target, 'Reference');
		const input = target.querySelector<HTMLInputElement>('input[type="file"]') as HTMLInputElement;
		Object.defineProperty(input, 'files', { value: [new File(['audio'], 'reference.wav')] });
		input.dispatchEvent(new Event('change', { bubbles: true }));
		await tick();
		expect(input.disabled).toBe(true);
		if (fails) response.reject(new Error('Upload refused'));
		else response.resolve({ path: '/reference.wav', filename: 'reference.wav' });
		await tick();
		await tick();
		if (fails) {
			expect(target.querySelector('[role="alert"]')?.textContent).toBe('Upload refused');
			expect(input.disabled).toBe(false);
		} else {
			expect(get(editGenParams)?.reference_audio_path).toBe('/reference.wav');
			await click(target, 'Remove');
			expect(get(editGenParams)).toBeNull();
		}
	});

	it('edits repaint mode, strength and waveform range inline', async () => {
		vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Audio unavailable')));
		setSourceFromGeneration(
			makeGeneration({ generation_params: { audio_duration: 180 } }),
			'repaint'
		);
		const target = await render();
		await click(target, 'Repaint');
		const mode = target.querySelector<HTMLSelectElement>(
			'select[aria-label="Repaint"]'
		) as HTMLSelectElement;
		mode.value = 'balanced';
		mode.dispatchEvent(new Event('change', { bubbles: true }));
		await tick();
		const strength = target.querySelector<HTMLInputElement>(
			'input[type="range"]'
		) as HTMLInputElement;
		strength.value = '0.6';
		strength.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();
		expect(get(repaintMode)).toBe('balanced');
		expect(get(repaintStrength)).toBe(0.6);
		const waveform = target.querySelector<HTMLElement>('.waveform-picker') as HTMLElement;
		vi.spyOn(waveform, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 0, 300, 64));
		const start = target.querySelector<HTMLElement>('[aria-label="Repaint start"]') as HTMLElement;
		start.setPointerCapture = vi.fn();
		start.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, clientX: 0 }));
		start.dispatchEvent(new MouseEvent('pointermove', { bubbles: true, clientX: 75 }));
		start.dispatchEvent(new MouseEvent('pointerup', { bubbles: true }));
		await tick();
		expect(get(repaintStart)).toBeCloseTo(0.25);
		expect(start.getAttribute('aria-valuenow')).toBe('25');
	});

	it('edits cover strengths and clears a source picked from a take', async () => {
		setSourceFromGeneration(makeGeneration(), 'cover');
		const target = await render();
		await click(target, 'Cover');
		const inputs = target.querySelectorAll<HTMLInputElement>('input[type="range"]');
		for (const input of inputs) {
			input.value = '0.4';
			input.dispatchEvent(new Event('input', { bubbles: true }));
		}
		await tick();
		expect(get(sourceMode)).toBe('cover');
		expect(get(coverStrength)).toBe(0.4);
		expect(get(coverNoiseStrength)).toBe(0.4);
		await click(target, 'Off');
		expect(get(sourceGeneration)).toBeNull();
	});
});
