import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import { detailTab } from '$lib/stores/navigation';
import DetailTabs from './DetailTabs.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

beforeEach(() => detailTab.set('write'));

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
});
