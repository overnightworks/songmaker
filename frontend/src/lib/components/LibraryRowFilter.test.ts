import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';

import LibraryRowFilter from './LibraryRowFilter.harness.svelte';
import { LIBRARY_ROW_FILTER_CLEAR_GLYPH, LIBRARY_ROW_FILTER_CLEAR_LABEL } from '$lib/constants';

const mounted: Array<ReturnType<typeof mount>> = [];

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
});

function render(collectionLabel = 'Albums'): HTMLElement {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(LibraryRowFilter, { target, props: { collectionLabel } }));
	return target;
}

function probeValue(root: HTMLElement): string {
	return root.querySelector('.filter-value-probe')?.textContent ?? '';
}

async function type(root: HTMLElement, text: string): Promise<void> {
	const input = root.querySelector<HTMLInputElement>('input');
	if (!input) throw new Error('Expected the filter input to render');
	input.value = text;
	input.dispatchEvent(new Event('input'));
	await tick();
}

describe('LibraryRowFilter', () => {
	it('reports what is typed back through the bound value', async () => {
		const root = render();
		await type(root, 'Anfield');
		expect(probeValue(root)).toBe('Anfield');
	});

	it('hides the clear button while empty and shows it once there is text', async () => {
		const root = render();
		expect(root.querySelector('button')).toBeNull();

		await type(root, 'a');

		const clearButton = root.querySelector<HTMLButtonElement>('button');
		expect(clearButton?.getAttribute('aria-label')).toBe(LIBRARY_ROW_FILTER_CLEAR_LABEL);
	});

	it('empties the value when the clear button is clicked', async () => {
		const root = render();
		await type(root, 'a');

		root.querySelector<HTMLButtonElement>('button')?.click();
		await tick();

		expect(probeValue(root)).toBe('');
		expect(root.querySelector('button')).toBeNull();
	});

	it('empties the value on Escape', async () => {
		const root = render();
		await type(root, 'a');

		root
			.querySelector('input')
			?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
		await tick();

		expect(probeValue(root)).toBe('');
	});

	it('places the input inside a labelled, lowercase collection-specific placeholder', () => {
		const root = render('Playlists');
		const input = root.querySelector<HTMLInputElement>('input');
		expect(input?.placeholder).toBe('Filter playlists…');
		expect(input?.getAttribute('aria-label')).toBe('Filter playlists by name');
	});

	it('shows the shared clear glyph on the clear button', async () => {
		const root = render();
		await type(root, 'a');
		expect(root.querySelector<HTMLButtonElement>('button')?.textContent?.trim()).toBe(
			LIBRARY_ROW_FILTER_CLEAR_GLYPH
		);
	});

	it('takes the clear button out of the Tab order, so Tab from the field skips it', async () => {
		const root = render();
		await type(root, 'a');
		const clearButton = root.querySelector<HTMLButtonElement>('button');
		expect(clearButton?.tabIndex).toBe(-1);
	});

	it('does not consume Escape on an already-empty field', async () => {
		const root = render();
		const input = root.querySelector<HTMLInputElement>('input');
		if (!input) throw new Error('Expected the filter input to render');

		const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
		input.dispatchEvent(event);
		await tick();

		expect(event.defaultPrevented).toBe(false);
		expect(probeValue(root)).toBe('');
	});

	it("announces Escape as the field's own clear shortcut, since the clear button is now Tab-invisible", () => {
		const root = render();
		const input = root.querySelector<HTMLInputElement>('input');
		expect(input?.getAttribute('aria-keyshortcuts')).toBe('Escape');
	});
});
