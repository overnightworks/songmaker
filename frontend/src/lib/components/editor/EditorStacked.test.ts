import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { RecipeChip } from '$lib/stores/recipe';
import EditorStacked from './EditorStacked.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
});

function chip(overrides: Partial<RecipeChip> = {}): RecipeChip {
	return { key: 'model', label: 'Model', value: 'TURBO', title: '', changed: false, ...overrides };
}

const CHIPS: RecipeChip[] = [
	chip({ key: 'model', label: 'Model', value: 'TURBO' }),
	chip({ key: 'takes', label: 'Takes', value: '×2' }),
	chip({ key: 'bpm', label: 'BPM', value: '108' }),
	chip({ key: 'duration', label: 'Duration', value: '195 s' }),
	chip({ key: 'key', label: 'Key', value: 'A major' }),
	chip({ key: 'voice', label: 'Voice', value: 'None' }),
	chip({ key: 'seed', label: 'Seed', value: 'Random' }),
	chip({ key: 'lm', label: 'LM', value: 'Default' }),
	chip({ key: 'dit', label: 'DIT', value: 'Default' }),
	chip({ key: 'repaint', label: 'Repaint', value: 'Off' })
];

async function render(overrides: Partial<{ chips: RecipeChip[]; onexpand: () => void }> = {}) {
	const target = document.createElement('div');
	document.body.append(target);
	const props = { chips: CHIPS, onexpand: vi.fn(), ...overrides };
	mounted.push(mount(EditorStacked, { target, props }));
	await tick();
	return { target, props };
}

describe('EditorStacked', () => {
	it('shows one summary row per group with its key values', async () => {
		const { target } = await render();
		const rows = Array.from(target.querySelectorAll('.stacked-row'));
		expect(rows).toHaveLength(3);
		expect(rows[0].textContent).toContain('Sound');
		expect(rows[0].textContent).toContain('Model TURBO');
		expect(rows[0].textContent).toContain('BPM 108');
		expect(rows[1].textContent).toContain('Text');
		expect(rows[1].textContent).toContain('LM Default');
		expect(rows[2].textContent).toContain('Reproduce');
		expect(rows[2].textContent).toContain('Repaint Off');
	});

	it('expands to the full panel on Edit', async () => {
		const onexpand = vi.fn();
		const { target } = await render({ onexpand });
		target.querySelector<HTMLButtonElement>('.stacked-edit')?.click();
		expect(onexpand).toHaveBeenCalledTimes(1);
	});
});
