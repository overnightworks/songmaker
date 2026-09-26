import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { detailTab } from '$lib/stores/navigation';

const action = await vi.hoisted(async () => {
	const { writable } = await import('svelte/store');
	return writable<GenerateState>({ kind: 'idle', mode: 'generate' });
});
vi.mock('$lib/stores/generateAction', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/stores/generateAction')>()),
	generateAction: action
}));

import type { GenerateState } from '$lib/stores/generateAction';
import DetailTabs from './DetailTabs.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

beforeEach(() => {
	detailTab.set('write');
	action.set({ kind: 'idle', mode: 'generate' });
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	detailTab.set('write');
});

async function render(takeCount = 4) {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(DetailTabs, { target, props: { takeCount } }));
	await tick();
	return Array.from(target.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
}

describe('DetailTabs', () => {
	it.each([0, 4, 123])(
		'shows two tabs with %i takes and follows navigation state',
		async (count) => {
			const tabs = await render(count);
			expect(tabs.map((tab) => tab.textContent?.trim())).toEqual(['Write', `Takes (${count})`]);
			expect(tabs[0].getAttribute('aria-selected')).toBe('true');
			tabs[1].click();
			await tick();
			expect(get(detailTab)).toBe('takes');
			expect(tabs[1].getAttribute('aria-selected')).toBe('true');
			detailTab.set('write');
			await tick();
			expect(tabs[0].getAttribute('aria-selected')).toBe('true');
		}
	);

	it.each([
		['ArrowRight', 'write', 'takes'],
		['ArrowLeft', 'write', 'takes'],
		['ArrowRight', 'takes', 'write'],
		['Home', 'takes', 'write'],
		['End', 'write', 'takes']
	] as const)('selects and focuses the tab for %s from %s', async (key, from, to) => {
		detailTab.set(from);
		const tabs = await render();
		const current = tabs[from === 'write' ? 0 : 1];
		const next = tabs[to === 'write' ? 0 : 1];
		current.focus();
		current.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
		await tick();
		expect(get(detailTab)).toBe(to);
		expect(document.activeElement).toBe(next);
		expect(next.tabIndex).toBe(0);
		expect(current.tabIndex).toBe(-1);
	});

	it.each([
		['queued', { kind: 'queued', jobId: 'job1', label: 'Queued #3', reason: null }, true],
		[
			'generating',
			{
				kind: 'generating',
				jobId: 'job1',
				takeCounter: 'Take 1 of 2',
				progress: 36,
				remaining: null
			},
			true
		],
		['idle', { kind: 'idle', mode: 'generate' }, false],
		['disabled', { kind: 'disabled', mode: 'generate', reason: 'No models' }, false],
		['failed', { kind: 'failed', mode: 'generate', cause: 'Worker error' }, false]
	] as const)('carries a ring on Takes exactly while %s', async (_label, state, expectRing) => {
		action.set(state as GenerateState);
		const tabs = await render();
		expect(tabs[1].querySelector('.ring') !== null).toBe(expectRing);
	});
});
