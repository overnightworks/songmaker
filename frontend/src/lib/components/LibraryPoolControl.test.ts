import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { detailTab } from '$lib/stores/navigation';
import { queueContext } from '$lib/stores/player';
import LibraryPoolControl from './LibraryPoolControl.svelte';

vi.mock('$app/state', () => ({
	page: { url: new URL('https://songmaker.test/') }
}));

let mounted: ReturnType<typeof mount> | undefined;

function requireElement<T extends Element>(root: ParentNode, selector: string): T {
	const element = root.querySelector<T>(selector);
	if (!element) throw new Error(`Expected ${selector} to be rendered`);
	return element;
}

async function renderNarrow(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(LibraryPoolControl, { target });
	await tick();
	return target;
}

async function openSheet(target: HTMLElement): Promise<HTMLDivElement> {
	requireElement<HTMLButtonElement>(target, '.pool-current').click();
	await tick();
	await Promise.resolve();
	return requireElement<HTMLDivElement>(document, '.pool-sheet');
}

beforeEach(() => {
	vi.stubGlobal(
		'matchMedia',
		vi.fn(() => ({
			matches: true,
			media: '(max-width: 640px)',
			onchange: null,
			addEventListener: vi.fn(),
			removeEventListener: vi.fn(),
			addListener: vi.fn(),
			removeListener: vi.fn(),
			dispatchEvent: vi.fn()
		}))
	);
	queueContext.set({ type: 'library' });
	detailTab.set('generations');
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.innerHTML = '';
	vi.unstubAllGlobals();
});

describe('LibraryPoolControl mobile dialog', () => {
	it('moves focus into the active choice and traps Tab in both directions', async () => {
		const target = await renderNarrow();
		const sheet = await openSheet(target);
		const buttons = Array.from(sheet.querySelectorAll<HTMLButtonElement>('.sheet-btn'));
		const first = buttons[0];
		const last = buttons.at(-1);
		if (!first || !last) throw new Error('Expected pool choices in the mobile sheet');

		expect(document.activeElement).toBe(sheet.querySelector('[aria-checked="true"]'));

		last.focus();
		window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
		expect(document.activeElement).toBe(first);

		first.focus();
		window.dispatchEvent(
			new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true })
		);
		expect(document.activeElement).toBe(last);
	});

	it('closes on Escape and restores focus to the trigger', async () => {
		const target = await renderNarrow();
		const trigger = requireElement<HTMLButtonElement>(target, '.pool-current');
		await openSheet(target);

		window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
		await tick();
		await Promise.resolve();

		expect(document.querySelector('.pool-sheet')).toBeNull();
		expect(document.activeElement).toBe(trigger);
	});

	it('closes on an outside tap and on a studio-tab change', async () => {
		const target = await renderNarrow();
		const trigger = requireElement<HTMLButtonElement>(target, '.pool-current');
		await openSheet(target);

		requireElement<HTMLButtonElement>(document, '.sheet-backdrop').click();
		await tick();
		await Promise.resolve();
		expect(document.querySelector('.pool-sheet')).toBeNull();
		expect(document.activeElement).toBe(trigger);

		await openSheet(target);
		detailTab.set('edit');
		await tick();
		await Promise.resolve();
		expect(document.querySelector('.pool-sheet')).toBeNull();
		expect(document.activeElement).toBe(trigger);
	});

	it('keeps the pool explanation in the compact sheet instead of adding a second control', async () => {
		const target = await renderNarrow();
		expect(target.querySelector('.pool-info')).toBeNull();

		const sheet = await openSheet(target);
		expect(sheet.querySelector('.sheet-help')?.textContent).toContain('Mix: Picks und Keeps');
	});
});
