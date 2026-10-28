import { createRawSnippet, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';

import ModelsServiceRow from './ModelsServiceRow.svelte';

const mounted: ReturnType<typeof mount>[] = [];

afterEach(() => {
	for (const component of mounted.splice(0)) unmount(component);
	document.body.innerHTML = '';
});

function renderRow(props: Record<string, unknown> = {}): HTMLElement {
	const target = document.createElement('div');
	document.body.appendChild(target);
	mounted.push(
		mount(ModelsServiceRow, {
			target,
			props: {
				task: 'Co-Writer',
				provider: 'Claude',
				route: 'Agent service',
				model: 'opus',
				...props
			}
		})
	);
	return target;
}

function cellTexts(target: HTMLElement): string[] {
	return [...target.querySelectorAll('.cell')].map((cell) =>
		(cell.textContent ?? '').replace(/\s+/g, ' ').trim()
	);
}

describe('C16 ModelsServiceRow', () => {
	it('says task, provider, route, model and as words in the four columns', () => {
		const target = renderRow();

		expect(cellTexts(target)).toEqual([
			'Co-Writer',
			'Provider Claude',
			'Route Agent service',
			'Model opus'
		]);
	});

	it('offers nothing to choose or save', () => {
		const target = renderRow();

		expect(target.querySelector('select, input, button, [role="group"]')).toBeNull();
		expect(target.textContent).not.toContain('Saved');
	});

	it('keeps its advanced part closed under an Advanced summary', () => {
		const advanced = createRawSnippet(() => ({ render: () => '<span id="budget">24000</span>' }));
		const target = renderRow({ advanced });

		const details = target.querySelector('details');
		expect(details?.querySelector('summary')?.textContent).toBe('Advanced');
		expect(details?.open).toBe(false);
		expect(details?.querySelector('#budget')?.textContent).toBe('24000');
	});
});
