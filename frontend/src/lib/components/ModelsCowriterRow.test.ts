import { createRawSnippet, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';

import ModelsCowriterRow from './ModelsCowriterRow.svelte';

const mounted: ReturnType<typeof mount>[] = [];

afterEach(() => {
	for (const component of mounted.splice(0)) unmount(component);
	document.body.innerHTML = '';
});

function renderRow(): HTMLElement {
	const target = document.createElement('div');
	document.body.appendChild(target);
	const advanced = createRawSnippet(() => ({ render: () => '<span>24000</span>' }));
	mounted.push(mount(ModelsCowriterRow, { target, props: { advanced } }));
	return target;
}

function rowText(target: HTMLElement): string {
	return (target.querySelector('.tt-row')?.textContent ?? '').replace(/\s+/g, ' ').trim();
}

describe('A1 the Co-writer row', () => {
	it('names the agent service and no model, no offer status and no note', () => {
		const target = renderRow();

		expect(rowText(target)).toBe(
			'Co-Writer Provider Set by the agent service Route Agent service Model Set by the agent service'
		);
		expect(target.querySelector('.st, .note')).toBeNull();
	});

	it('keeps the history tail under Advanced', () => {
		const target = renderRow();

		expect(target.querySelector('details summary')?.textContent).toBe('Advanced');
		expect(target.querySelector('details')?.textContent).toContain('24000');
	});

	it('offers nothing to choose', () => {
		const target = renderRow();

		expect(target.querySelector('select, input, button, [role="group"]')).toBeNull();
	});
});
