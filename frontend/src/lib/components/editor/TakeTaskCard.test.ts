import { mount, tick, unmount } from 'svelte';
import { get, writable } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { makeGeneration } from '$lib/test-utils/factories';
import { RECIPE_SOURCE_MODE_HINT } from '$lib/constants';
import type { GenerateState } from '$lib/stores/generateAction';

const runSourceTask = vi.hoisted(() => vi.fn());
const state = vi.hoisted(() => ({ current: null as unknown }));

vi.mock('$lib/stores/generateAction', async () => {
	const { writable: store } = await import('svelte/store');
	const generateAction = store({ kind: 'idle', mode: 'repaint' });
	state.current = generateAction;
	return {
		generateAction,
		runSourceTask,
		isGenerateBusy: (s: { kind: string }) => s.kind === 'queued' || s.kind === 'generating'
	};
});

import {
	clearSource,
	repaintEnd,
	repaintMode,
	repaintStart,
	resetRecipeSourceForSong,
	setSourceFromGeneration,
	sourceGeneration
} from '$lib/stores/recipe';
import TakeTaskCard from './TakeTaskCard.svelte';

let card: ReturnType<typeof mount> | undefined;

async function renderCard(
	mode: 'repaint' | 'cover',
	overrides: Parameters<typeof makeGeneration>[0] = {}
): Promise<HTMLElement> {
	const gen = makeGeneration({
		generation_number: 11,
		version_number: 6,
		audio_duration_sec: 193.4,
		...overrides
	});
	setSourceFromGeneration(gen, mode);
	const target = document.createElement('div');
	document.body.append(target);
	card = mount(TakeTaskCard, { target, props: { gen, landingVersionNumber: 7 } });
	await tick();
	return target;
}

function setGenerateState(next: GenerateState): void {
	(state.current as ReturnType<typeof writable<GenerateState>>).set(next);
}

beforeEach(() => {
	resetRecipeSourceForSong();
	runSourceTask.mockReset();
	setGenerateState({ kind: 'idle', mode: 'repaint' });
});

afterEach(async () => {
	if (card) await unmount(card);
	card = undefined;
	document.body.replaceChildren();
});

const flatText = (target: HTMLElement) => target.textContent?.replace(/\s+/g, ' ') ?? '';
const cardButton = (target: HTMLElement, name: string) =>
	Array.from(target.querySelectorAll('button')).find((b) => b.textContent?.trim() === name);

describe('Repaint card (S4, #1912 acceptance 2)', () => {
	it('shows the head, the range, how much changes and the foot', async () => {
		const target = await renderCard('repaint');
		expect(flatText(target)).toContain('Repaint take 11 · v6 · 3:13');
		expect(target.querySelector('.waveform-picker')).not.toBeNull();
		for (const name of ['Conservative', 'Balanced', 'Aggressive']) {
			expect(cardButton(target, name)).toBeDefined();
		}
		expect(flatText(target)).toContain(RECIPE_SOURCE_MODE_HINT);
		expect(flatText(target)).toContain('New take in v7');
		expect(target.querySelector('input[type="range"]')).toBeNull();
	});

	it('names the button after the handles in whole seconds of the measured length', async () => {
		const target = await renderCard('repaint', { audio_duration_sec: 100 });
		repaintStart.set(0.421);
		repaintEnd.set(0.708);
		await tick();
		expect(cardButton(target, 'Repaint 0:42 – 1:10')).toBeDefined();
	});

	it('offers the strength slider only on Balanced', async () => {
		const target = await renderCard('repaint');
		cardButton(target, 'Balanced')?.click();
		await tick();
		expect(get(repaintMode)).toBe('balanced');
		expect(target.querySelectorAll('input[type="range"]')).toHaveLength(1);
		cardButton(target, 'Aggressive')?.click();
		await tick();
		expect(target.querySelector('input[type="range"]')).toBeNull();
	});
});

describe('Cover card (S4, #1912 acceptance 3)', () => {
	it('shows closeness, noise over 0 to 1, the hint, the foot and the Cover button', async () => {
		const target = await renderCard('cover');
		expect(flatText(target)).toContain('Cover take 11 · v6 · 3:13');
		expect(flatText(target)).toContain('How close to take 11');
		const sliders = target.querySelectorAll<HTMLInputElement>('input[type="range"]');
		expect(sliders).toHaveLength(2);
		expect(sliders[1].max).toBe('1');
		expect(flatText(target)).toContain(RECIPE_SOURCE_MODE_HINT);
		expect(flatText(target)).toContain('New take in v7');
		expect(cardButton(target, 'Cover')).toBeDefined();
		expect(target.querySelector('.waveform-picker')).toBeNull();
	});
});

describe('both cards (S4, #1912 acceptance 5)', () => {
	it.each(['repaint', 'cover'] as const)('the %s button runs the source task', async (mode) => {
		const target = await renderCard(mode);
		target.querySelector<HTMLButtonElement>('.task-foot button')?.click();
		expect(runSourceTask).toHaveBeenCalledTimes(1);
	});

	it.each([
		{ label: 'idle', next: { kind: 'idle', mode: 'repaint' }, disabled: false },
		{
			label: 'failed',
			next: { kind: 'failed', mode: 'repaint', cause: 'x', unavailable: false },
			disabled: false
		},
		{
			label: 'disabled',
			next: { kind: 'disabled', mode: 'repaint', reason: null },
			disabled: true
		},
		{ label: 'queued', next: { kind: 'queued' }, disabled: true }
	] as const)(
		'the button is disabled=$disabled while Generate is $label',
		async ({ next, disabled }) => {
			const target = await renderCard('repaint');
			setGenerateState(next as unknown as GenerateState);
			await tick();
			expect(target.querySelector<HTMLButtonElement>('.task-foot button')?.disabled).toBe(disabled);
		}
	);

	it('closes by removing the source and nothing else', async () => {
		const target = await renderCard('repaint');
		repaintMode.set('aggressive');
		target.querySelector<HTMLButtonElement>('button[title="Close — nothing changes"]')?.click();
		expect(get(sourceGeneration)).toBeNull();
		expect(get(repaintMode)).toBe('aggressive');
		clearSource();
	});
});
