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
				status: 'Ready',
				statusTone: 'plain',
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
			'Status Ready'
		]);
	});

	it('offers nothing to choose or save', () => {
		const target = renderRow();

		expect(target.querySelector('select, input, button, [role="group"]')).toBeNull();
		expect(target.textContent).not.toContain('Saved');
	});

	it.each([
		{ statusTone: 'plain', mark: null },
		{ statusTone: 'ok', mark: '✓' },
		{ statusTone: 'off', mark: '○' },
		{ statusTone: 'warn', mark: '!' }
	])('draws the $statusTone status with the mark $mark', ({ statusTone, mark }) => {
		const target = renderRow({ statusTone });

		const status = target.querySelector('.st');
		expect(status?.classList.contains(statusTone)).toBe(true);
		expect(status?.querySelector('.mark')?.textContent ?? null).toBe(mark);
	});

	it('draws a status link after the status words', () => {
		const target = renderRow({
			status: 'Sign in again to check the offer',
			statusLink: { href: '/login/oidc?next=%2Fsettings', text: 'Sign in' }
		});

		const link = target.querySelector<HTMLAnchorElement>('.st a');
		expect(link?.textContent).toBe('Sign in');
		expect(link?.getAttribute('href')).toBe('/login/oidc?next=%2Fsettings');
	});

	it('shows a warning under the model and leaves the status cell empty', () => {
		const target = renderRow({
			status: '',
			modelWarning: 'No longer offered by the agent service'
		});

		expect(cellTexts(target)[3]).toBe('Model opus No longer offered by the agent service');
		expect(target.querySelector('.why.warn')?.textContent).toBe(
			'No longer offered by the agent service'
		);
		expect(cellTexts(target)[4]).toBe('Status');
		expect(target.querySelector('.st')).toBeNull();
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
