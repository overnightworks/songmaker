import { flushSync, mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { describeBackClosesOverlay, plannedHistoryIndex } from '$lib/test-utils/library-history';
import { listenForGlobalEscape } from '$lib/test-utils/global-escape';
import ConfirmDeleteDialog from './ConfirmDeleteDialog.svelte';

const TITLE = 'Delete song?';

let openDialog: ReturnType<typeof mount> | null = null;
let stopListeningForEscape: () => void = () => undefined;

afterEach(async () => {
	stopListeningForEscape();
	if (openDialog) await unmount(openDialog);
	openDialog = null;
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

// SongMenu and CollectionMenu close in the same click that opens the confirm:
// the removed menu item drops focus to <body>, Svelte's flush mounts the dialog,
// and only then does the menu's own microtask hand focus back to its trigger.
async function openFromMenu(trigger: HTMLElement): Promise<HTMLElement> {
	const menuItem = document.createElement('button');
	document.body.append(menuItem);
	menuItem.focus();
	menuItem.remove();
	const target = document.createElement('div');
	document.body.append(target);
	queueMicrotask(() => {
		openDialog = mount(ConfirmDeleteDialog, {
			target,
			props: { title: TITLE, items: ['Night Drive'], onconfirm: closeDialog, oncancel: closeDialog }
		});
		flushSync();
	});
	queueMicrotask(() => trigger.focus());
	await tick();
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

	it('takes focus and later returns it to the menu trigger when a closing menu opened it', async () => {
		const trigger = renderOpener();
		const dialog = await openFromMenu(trigger);
		expect(document.activeElement).toBe(button(dialog, 'Cancel'));
		pressKey(button(dialog, 'Cancel'), 'Escape');
		await tick();
		expect(document.activeElement).toBe(trigger);
	});

	it('closes only itself on Escape, never also taking the page one level up', async () => {
		const levelUp = vi.fn();
		stopListeningForEscape = listenForGlobalEscape(levelUp);
		const dialog = await openFrom(renderOpener());
		pressKey(button(dialog, 'Cancel'), 'Escape');
		expect(document.querySelector('[role="dialog"]')).toBeNull();
		expect(levelUp).not.toHaveBeenCalled();
	});

	it('is labelled by its title', async () => {
		const dialog = await openFrom(renderOpener());
		const labelId = dialog.getAttribute('aria-labelledby');
		expect(labelId && document.getElementById(labelId)?.textContent).toBe(TITLE);
	});
});

const deletions: string[] = [];
let deletionSawHistoryAt: number | undefined;

function openDeleteConfirm(target: HTMLElement): void {
	deletions.length = 0;
	deletionSawHistoryAt = undefined;
	openDialog = mount(ConfirmDeleteDialog, {
		target,
		props: {
			title: TITLE,
			items: ['Night Drive'],
			onconfirm: () => {
				deletions.push('Night Drive');
				deletionSawHistoryAt = plannedHistoryIndex();
				closeDialog();
			},
			oncancel: closeDialog
		}
	});
}

describeBackClosesOverlay({
	name: 'the delete confirmation',
	render: async () => {
		const target = document.createElement('div');
		document.body.append(target);
		return target;
	},
	open: openDeleteConfirm,
	isShown: (target) => target.querySelector('[role="dialog"]') !== null,
	afterBack: () => expect(deletions).toEqual([]),
	closeWays: [
		{ way: 'Cancel', close: (target) => button(target, 'Cancel').click() },
		{
			way: 'Delete',
			close: (target) => button(target, 'Delete').click(),
			actionSawHistoryAt: () => deletionSawHistoryAt
		},
		{
			way: 'the backdrop',
			close: (target) => target.querySelector<HTMLElement>('.overlay')?.click()
		},
		{ way: 'Escape', close: (target) => pressKey(button(target, 'Cancel'), 'Escape') }
	]
});
