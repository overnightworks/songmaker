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
				status: 'Checked by the agent service at each turn',
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
	it('says task, provider, route, model and who checks, as words in the five columns', () => {
		const target = renderRow();

		expect(cellTexts(target)).toEqual([
			'Co-Writer',
			'Provider Claude',
			'Route Agent service',
			'Model opus',
			'Status Checked by the agent service at each turn'
		]);
	});

	it('offers nothing to choose or save', () => {
		const target = renderRow();

		expect(target.querySelector('select, input, button, [role="group"]')).toBeNull();
		expect(target.textContent).not.toContain('Saved');
	});

	it('shows a readiness light for no one: no check mark and no ring', () => {
		const target = renderRow();

		expect(target.querySelector('.mark')).toBeNull();
	});

	it('greys the note line under the row', () => {
		const target = renderRow({ note: 'Grok, Codex: not selectable yet' });

		expect(target.querySelector('.tt-sub .note')?.textContent).toBe(
			'Grok, Codex: not selectable yet'
		);
	});

	it('draws no note line when it has none', () => {
		expect(renderRow().querySelector('.note')).toBeNull();
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
