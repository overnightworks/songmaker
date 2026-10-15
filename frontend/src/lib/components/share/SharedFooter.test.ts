import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import { getByRoleButton } from '$lib/test-utils/accessible-name';
import { LEGAL_SECTIONS } from '../LegalLinks.svelte';
import SharedFooter from './SharedFooter.svelte';

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

async function openLegal(target: HTMLElement, label = 'Impressum'): Promise<void> {
	getByRoleButton(target, label).click();
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

describe('SharedFooter legal links', () => {
	it.each(LEGAL_SECTIONS)(
		'opens $label over the share page instead of leaving it',
		async ({ label }) => {
			const target = await render();
			await openLegal(target, label);

			const tab = requireElement<HTMLElement>(target, '.legal-modal .legal-tabs .active');
			expect(tab.textContent?.trim()).toBe(label);
			expect(target.querySelector('.powered')).not.toBeNull();
		}
	);
});
