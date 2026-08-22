import { mount, tick, unmount } from 'svelte';
import { get } from 'svelte/store';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { VersionGenerationParams } from '$lib/api/types';
import { COMPACT_LAYOUT_MEDIA } from '$lib/constants';
import { toasts } from '$lib/stores/toast';

import ParamControls from './ParamControls.svelte';

let mounted: ReturnType<typeof mount> | undefined;

function stubMatchMedia(matches: boolean): void {
	vi.stubGlobal(
		'matchMedia',
		vi.fn(() => ({
			matches,
			media: COMPACT_LAYOUT_MEDIA,
			onchange: null,
			addEventListener: vi.fn(),
			removeEventListener: vi.fn(),
			addListener: vi.fn(),
			removeListener: vi.fn(),
			dispatchEvent: vi.fn()
		}))
	);
}

const LOADED_PLACEHOLDERS: Required<VersionGenerationParams> = {
	inference_steps: 27,
	guidance_scale: 7.5,
	shift: 3,
	thinking: true,
	lm_temperature: 0.85,
	lm_top_k: 50,
	lm_top_p: 0.9,
	lm_cfg_scale: 2,
	lm_negative_prompt: '',
	infer_method: 'ode',
	batch_size: 1,
	reference_audio_path: '',
	repaint_mode: 'balanced',
	repaint_strength: 0.5,
	lm_repetition_penalty: 1.1,
	use_cot_caption: true,
	use_cot_language: true,
	use_adg: false,
	cfg_interval_start: 0,
	cfg_interval_end: 1,
	sampler_mode: 'euler',
	velocity_norm_threshold: 10,
	velocity_ema_factor: 0.1,
	latent_shift: 0,
	latent_rescale: 1,
	audio_cover_strength: 0.5,
	user_lora_id: ''
};

async function renderControls(
	compact: boolean,
	placeholders: VersionGenerationParams = {}
): Promise<HTMLElement> {
	stubMatchMedia(compact);
	if (compact) document.documentElement.dataset.pointer = 'coarse';
	else delete document.documentElement.dataset.pointer;
	const target = document.createElement('div');
	target.style.width = '320px';
	document.body.append(target);
	mounted = mount(ParamControls, {
		target,
		props: {
			values: {},
			placeholders: placeholders as Required<VersionGenerationParams>,
			onchange: vi.fn()
		}
	});
	await tick();
	await Promise.resolve();
	await tick();
	return target;
}

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	document.head.querySelectorAll('[data-compact-ui]').forEach((el) => el.remove());
	delete document.documentElement.dataset.pointer;
	vi.unstubAllGlobals();
	toasts.set([]);
});

describe('ParamControls compact layout', () => {
	it('stacks generation fields to one column at 320px', async () => {
		const target = await renderControls(true);
		const grid = target.querySelector('.settings-grid');
		if (!(grid instanceof HTMLElement)) throw new Error('Expected settings grid');
		expect(target.querySelector('.param-controls')?.classList.contains('compact')).toBe(true);
		expect(getComputedStyle(grid).gridTemplateColumns).toBe('minmax(0, 1fr)');
		expect(target.scrollWidth).toBeLessThanOrEqual(target.clientWidth);
	});

	it('does not apply the compact one-column override on a wide fine pointer', async () => {
		const target = await renderControls(false);
		const grid = target.querySelector('.settings-grid');
		if (!(grid instanceof HTMLElement)) throw new Error('Expected settings grid');
		expect(target.querySelector('.param-controls')?.classList.contains('compact')).toBe(false);
		expect(getComputedStyle(grid).gridTemplateColumns).not.toBe('minmax(0, 1fr)');
	});
});

describe('ParamControls placeholders', () => {
	it('shows no "undefined" placeholder text before model defaults load', async () => {
		const target = await renderControls(false);
		const numberInput = target.querySelector('input[type="number"]');
		if (!(numberInput instanceof HTMLInputElement)) throw new Error('Expected a number input');
		expect(numberInput.placeholder).toBe('');
		expect(target.textContent).not.toContain('undefined');
	});

	it('shows the loaded default values as placeholders once defaults load', async () => {
		const target = await renderControls(false, LOADED_PLACEHOLDERS);
		const numberInput = target.querySelector('input[type="number"]');
		if (!(numberInput instanceof HTMLInputElement)) throw new Error('Expected a number input');
		expect(numberInput.placeholder).toBe(String(LOADED_PLACEHOLDERS.inference_steps));

		const select = target.querySelector('select');
		if (!(select instanceof HTMLSelectElement)) throw new Error('Expected a select input');
		expect(select.options[0].textContent).toBe(`default (${LOADED_PLACEHOLDERS.infer_method})`);
		expect(target.textContent).not.toContain('undefined');
	});

	it('contains a missing default after load to that one field, not the whole panel', async () => {
		const { inference_steps: _omitted, ...incompletePlaceholders } = LOADED_PLACEHOLDERS;
		const target = await renderControls(false, incompletePlaceholders);

		const errorText = target.querySelector('.param-error-text');
		expect(errorText?.textContent).toBe('Default missing for inference_steps');
		expect(
			Array.from(target.querySelectorAll('input[type="number"]')).some(
				(input) =>
					(input as HTMLInputElement).placeholder === String(LOADED_PLACEHOLDERS.inference_steps)
			)
		).toBe(false);

		const guidanceInput = Array.from(target.querySelectorAll('input[type="number"]')).find(
			(input) =>
				(input as HTMLInputElement).placeholder === String(LOADED_PLACEHOLDERS.guidance_scale)
		);
		expect(guidanceInput).toBeDefined();

		const select = target.querySelector('select');
		if (!(select instanceof HTMLSelectElement)) throw new Error('Expected a select input');
		expect(select.options[0].textContent).toBe(`default (${LOADED_PLACEHOLDERS.infer_method})`);

		expect(
			get(toasts).some(
				(t) => t.type === 'error' && t.message === 'Default missing for inference_steps'
			)
		).toBe(true);
	});
});
