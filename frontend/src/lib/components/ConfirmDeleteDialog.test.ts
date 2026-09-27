import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import { shouldHandleGlobalEscape } from '$lib/utils/escape-level-up';
import ConfirmDeleteDialog from './ConfirmDeleteDialog.svelte';

const TITLE = 'Delete song?';

let openDialog: ReturnType<typeof mount> | null = null;
let globalEscapeFired = false;

function onWindowKeydown(event: KeyboardEvent): void {
	if (shouldHandleGlobalEscape(event, document)) globalEscapeFired = true;
}

afterEach(async () => {
	window.removeEventListener('keydown', onWindowKeydown);
	if (openDialog) await unmount(openDialog);
	openDialog = null;
	globalEscapeFired = false;
	document.body.replaceChildren();
});

// A real browser runs microtasks between listeners, so the caller's close has
// already unmounted the dialog before the page's window listener looks at the
// DOM; closing synchronously here reproduces that ordering.
function closeDialog(): void {
	if (!openDialog) return;
	void unmount(openDialog);
	openDialog = null;
}

async function openFrom(opener: HTMLElement): Promise<HTMLElement> {
	opener.focus();
	const target = document.createElement('div');
	document.body.append(target);
	openDialog = mount(ConfirmDeleteDialog, {
		target,
		props: { title: TITLE, items: ['Night Drive'], onconfirm: closeDialog, oncancel: closeDialog }
	});
	await tick();
	const dialog = document.querySelector<HTMLElement>('[role="dialog"]');
	if (!dialog) throw new Error('Expected the confirm dialog to be rendered');
	return dialog;
}

function renderOpener(): HTMLButtonElement {
	const opener = document.createElement('button');
	opener.textContent = 'Delete song';
	document.body.append(opener);
	return opener;
}

function button(dialog: HTMLElement, label: string): HTMLButtonElement {
	const match = Array.from(dialog.querySelectorAll('button')).find(
		(candidate) => candidate.textContent === label
	);
	if (!match) throw new Error(`Expected a ${label} button`);
	return match;
}

function pressKey(target: EventTarget, key: string, shiftKey = false): void {
	target.dispatchEvent(
		new KeyboardEvent('keydown', { key, shiftKey, bubbles: true, cancelable: true })
	);
}

describe('ConfirmDeleteDialog', () => {
	it('moves focus onto Cancel when it opens', async () => {
		const dialog = await openFrom(renderOpener());
		expect(document.activeElement).toBe(button(dialog, 'Cancel'));
	});

	it.each([
		['Tab from Delete', 'Delete', false, 'Cancel'],
		['Shift+Tab from Cancel', 'Cancel', true, 'Delete']
	])('keeps focus inside the dialog on %s', async (_case, from, shiftKey, to) => {
		const dialog = await openFrom(renderOpener());
		button(dialog, from).focus();
		pressKey(button(dialog, from), 'Tab', shiftKey);
		expect(document.activeElement).toBe(button(dialog, to));
	});

	it.each([
		['Cancel', (dialog: HTMLElement) => button(dialog, 'Cancel').click()],
		['Delete', (dialog: HTMLElement) => button(dialog, 'Delete').click()],
		['Escape', (dialog: HTMLElement) => pressKey(button(dialog, 'Cancel'), 'Escape')]
	])('returns focus to the control that opened it after %s', async (_case, close) => {
		const opener = renderOpener();
		const dialog = await openFrom(opener);
		close(dialog);
		await tick();
		expect(document.querySelector('[role="dialog"]')).toBeNull();
		expect(document.activeElement).toBe(opener);
	});

	it('closes only itself on Escape, never also taking the page one level up', async () => {
		window.addEventListener('keydown', onWindowKeydown);
		const dialog = await openFrom(renderOpener());
		pressKey(button(dialog, 'Cancel'), 'Escape');
		expect(document.querySelector('[role="dialog"]')).toBeNull();
		expect(globalEscapeFired).toBe(false);
	});

	it('is labelled by its title', async () => {
		const dialog = await openFrom(renderOpener());
		const labelId = dialog.getAttribute('aria-labelledby');
		expect(labelId && document.getElementById(labelId)?.textContent).toBe(TITLE);
	});
});
