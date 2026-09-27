import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { detailTab, type DetailTab } from '$lib/stores/navigation';

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
import detailTabsSource from './DetailTabs.svelte?raw';
import { watchTypingOnPhone } from '$lib/stores/ui';
import { clearComponentStyles, injectComponentStyles } from '$lib/test-utils/component-styles';
import { openOnScreenKeyboard } from '$lib/test-utils/on-screen-keyboard';

const mounted: Array<ReturnType<typeof mount>> = [];

beforeEach(() => {
	detailTab.set('edit');
	action.set({ kind: 'idle', mode: 'generate' });
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	detailTab.set('edit');
	clearComponentStyles();
});

async function render(takeCount = 4) {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(DetailTabs, { target, props: { takeCount } }));
	await tick();
	return Array.from(target.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
}

function tabNamed(tabs: HTMLButtonElement[], tab: DetailTab): HTMLButtonElement {
	const found = tabs.find((button) => button.dataset.tab === tab);
	if (!found) throw new Error(`Expected the ${tab} tab`);
	return found;
}

describe('DetailTabs', () => {
	it.each([0, 4, 123])(
		'shows Edit, Co-writer and Takes with %i takes and follows navigation state',
		async (count) => {
			const tabs = await render(count);
			expect(tabs.map((tab) => tab.textContent?.trim())).toEqual([
				'Edit',
				'Co-writer',
				`Takes (${count})`
			]);
			expect(tabs[0].getAttribute('aria-selected')).toBe('true');
			tabs[1].click();
			await tick();
			expect(get(detailTab)).toBe('cowriter');
			expect(tabs[1].getAttribute('aria-selected')).toBe('true');
			detailTab.set('takes');
			await tick();
			expect(tabs[2].getAttribute('aria-selected')).toBe('true');
		}
	);

	it.each([
		['ArrowRight', 'edit', 'cowriter'],
		['ArrowRight', 'cowriter', 'takes'],
		['ArrowRight', 'takes', 'edit'],
		['ArrowLeft', 'edit', 'takes'],
		['ArrowLeft', 'takes', 'cowriter'],
		['ArrowLeft', 'cowriter', 'edit'],
		['Home', 'takes', 'edit'],
		['End', 'edit', 'takes']
	] as const)('selects and focuses the tab for %s from %s', async (key, from, to) => {
		detailTab.set(from);
		const tabs = await render();
		const current = tabNamed(tabs, from);
		const next = tabNamed(tabs, to);
		current.focus();
		current.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
		await tick();
		expect(get(detailTab)).toBe(to);
		expect(document.activeElement).toBe(next);
		expect(next.tabIndex).toBe(0);
		expect(current.tabIndex).toBe(-1);
	});

	it.each([
		[
			'queued',
			{ kind: 'queued', jobId: 'job1', label: 'Queued #3', reason: null, reconnecting: false },
			true
		],
		[
			'generating',
			{
				kind: 'generating',
				jobId: 'job1',
				phase: 'Rendering',
				takeCounter: 'Take 1 of 2',
				progress: 36,
				readout: '36%',
				ended: false,
				reconnecting: false
			},
			true
		],
		[
			'submitting',
			{
				kind: 'generating',
				jobId: null,
				phase: 'Generating...',
				takeCounter: null,
				progress: 0,
				readout: '0%',
				ended: false,
				reconnecting: false
			},
			true
		],
		['idle', { kind: 'idle', mode: 'generate' }, false],
		['disabled', { kind: 'disabled', mode: 'generate', reason: 'No models' }, false],
		['failed', { kind: 'failed', mode: 'generate', cause: 'Worker error' }, false]
	] as const)('carries a ring on Takes exactly while %s', async (_label, state, expectRing) => {
		action.set(state as GenerateState);
		const tabs = await render();
		expect(tabNamed(tabs, 'takes').querySelector('.ring') !== null).toBe(expectRing);
	});

	it.each([
		{ connection: 'live', reconnecting: false, color: 'var(--score-ok)' },
		{ connection: 'reconnecting', reconnecting: true, color: 'var(--text-disabled)' }
	])(
		'draws the running ring $color while the take is $connection',
		async ({ reconnecting, color }) => {
			action.set({
				kind: 'generating',
				jobId: 'job1',
				phase: 'Rendering',
				takeCounter: null,
				progress: 40,
				readout: '40%',
				reconnecting,
				ended: false
			});
			const tabs = await render();
			const ring = tabNamed(tabs, 'takes').querySelector('.ring');
			if (!ring) throw new Error('Expected the running ring');
			injectComponentStyles(detailTabsSource, 'DetailTabs.svelte', ring);
			expect(getComputedStyle(ring).color).toBe(color);
		}
	);

	it('sticks to the top, but scrolls away with the text while typing on the phone keyboard', async () => {
		const closeKeyboard = openOnScreenKeyboard();
		const stopWatching = watchTypingOnPhone(document, true);
		const [write] = await render();
		const tablist = write.parentElement;
		if (!tablist) throw new Error('Expected the tab list');
		injectComponentStyles(detailTabsSource, 'DetailTabs.svelte', tablist);
		expect(getComputedStyle(tablist).position).toBe('sticky');

		const lyrics = document.createElement('textarea');
		document.body.append(lyrics);
		lyrics.focus();
		await tick();
		expect(getComputedStyle(tablist).position).not.toBe('sticky');

		lyrics.blur();
		await tick();
		expect(getComputedStyle(tablist).position).toBe('sticky');
		stopWatching();
		closeKeyboard();
	});
});
