import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import SharedFooter from './SharedFooter.svelte';
import sharedFooterSource from './SharedFooter.svelte?raw';

let mounted: ReturnType<typeof mount> | undefined;

function requireElement<T extends Element>(root: ParentNode, selector: string): T {
	const element = root.querySelector<T>(selector);
	if (!element) throw new Error(`Expected ${selector} to be rendered`);
	return element;
}

async function render(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(SharedFooter, { target });
	await tick();
	return target;
}

async function openLegal(target: HTMLElement): Promise<void> {
	requireElement<HTMLButtonElement>(target, '.link-btn').click();
	await tick();
	await tick();
}

function pressTab(shiftKey = false): void {
	window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey, bubbles: true }));
}

function pressEscape(): void {
	window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
}

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

describe('SharedFooter legal overlay', () => {
	it('moves focus into the overlay and keeps it there while tabbing', async () => {
		const target = await render();
		await openLegal(target);

		const modal = requireElement<HTMLElement>(target, '.legal-modal');
		const focusable = modal.querySelectorAll<HTMLElement>('a[href], button:not(:disabled)');
		expect(focusable.length).toBeGreaterThan(0);
		expect(modal.contains(document.activeElement)).toBe(true);

		const last = focusable[focusable.length - 1];
		last.focus();
		pressTab();
		expect(document.activeElement).toBe(focusable[0]);

		focusable[0].focus();
		pressTab(true);
		expect(document.activeElement).toBe(last);
	});

	it('closes only the overlay on Escape, not the page behind it', async () => {
		const target = await render();
		await openLegal(target);
		expect(target.querySelector('.legal-overlay')).not.toBeNull();

		pressEscape();
		await tick();

		expect(target.querySelector('.legal-overlay')).toBeNull();
		expect(target.querySelector('.powered')).not.toBeNull();
	});
});

describe('SharedFooter separators', () => {
	it('renders every link as its own item with the dot drawn by CSS, not inline text', async () => {
		const target = await render();
		const items = Array.from(target.querySelectorAll('.footer-item'));
		expect(items).toHaveLength(4);
		for (const item of items) {
			expect(item.textContent).not.toContain('·');
		}
	});

	it('draws the separator only before items after the first, so wrapping never strands a dot', () => {
		const escaped = '.footer-item:not(:first-child)::before'.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
		const match = new RegExp(`${escaped}\\s*{([^}]*)}`).exec(sharedFooterSource);
		expect(match).not.toBeNull();
		expect(match?.[1]).toContain("content: '·'");
	});
});
