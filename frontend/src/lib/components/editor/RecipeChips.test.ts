import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { RecipeChip } from '$lib/stores/recipe';
import RecipeChips from './RecipeChips.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
});

const CHIPS: RecipeChip[] = [
	{
		key: 'model',
		label: 'Model',
		value: 'TURBO',
		title: 'Model used for generation',
		changed: false
	},
	{ key: 'takes', label: 'Takes', value: '×2', title: 'Takes per Generate', changed: false }
];

describe('RecipeChips', () => {
	it('renders one labeled chip per entry with no visible help text, just a tooltip', async () => {
		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(
			mount(RecipeChips, { target, props: { chips: CHIPS, open: false, onclick: vi.fn() } })
		);
		await tick();
		const chips = target.querySelectorAll('.chip');
		expect(chips).toHaveLength(2);
		expect(chips[0].textContent).toContain('Model');
		expect(chips[0].textContent).toContain('TURBO');
		expect(chips[0].getAttribute('title')).toBe('Model used for generation');
		expect(target.querySelector('.chip-hint')).toBeNull();
	});

	it('marks a changed chip with a dot instead of repeating text', async () => {
		const target = document.createElement('div');
		document.body.append(target);
		const changed: RecipeChip[] = [
			{ key: 'bpm', label: 'BPM', value: '140', title: 'Target tempo', changed: true }
		];
		mounted.push(
			mount(RecipeChips, { target, props: { chips: changed, open: false, onclick: vi.fn() } })
		);
		await tick();
		expect(target.querySelector('.chip-changed-dot')).not.toBeNull();
	});

	it('expands the panel on click and reflects the open state', async () => {
		const target = document.createElement('div');
		document.body.append(target);
		const onclick = vi.fn();
		mounted.push(mount(RecipeChips, { target, props: { chips: CHIPS, open: false, onclick } }));
		await tick();
		const trigger = target.querySelector<HTMLButtonElement>('.recipe-chips');
		expect(trigger?.getAttribute('aria-expanded')).toBe('false');
		trigger?.click();
		expect(onclick).toHaveBeenCalledTimes(1);
	});
});
