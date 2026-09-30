import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { describeBackClosesOverlay } from '$lib/test-utils/library-history';
import ConfirmDialog from './ConfirmDialog.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
});

function defaultProps() {
	return {
		title: 'Unsaved changes',
		message: 'Save this draft as a new version before leaving, or discard it?',
		confirmLabel: 'Save',
		onconfirm: vi.fn(),
		secondaryLabel: 'Discard',
		onsecondary: vi.fn(),
		oncancel: vi.fn()
	};
}

async function render(overrides: Partial<ReturnType<typeof defaultProps>> = {}) {
	const target = document.createElement('div');
	document.body.append(target);
	const props = { ...defaultProps(), ...overrides };
	mounted.push(mount(ConfirmDialog, { target, props }));
	await tick();
	return { target, props };
}

describe('ConfirmDialog', () => {
	it('renders the title, message, and all three actions', async () => {
		const { target } = await render();
		expect(target.querySelector('h3')?.textContent).toBe('Unsaved changes');
		expect(target.querySelector('.message')?.textContent).toContain('Save this draft');
		expect(target.querySelector('.confirm-btn')?.textContent).toBe('Save');
		expect(target.querySelector('.secondary-btn')?.textContent).toBe('Discard');
		expect(target.querySelector('.cancel-btn')?.textContent).toBe('Cancel');
	});

	it('calls onconfirm on the primary action', async () => {
		const { target, props } = await render();
		target.querySelector<HTMLButtonElement>('.confirm-btn')?.click();
		expect(props.onconfirm).toHaveBeenCalledTimes(1);
	});

	it('calls onsecondary on the secondary action', async () => {
		const { target, props } = await render();
		target.querySelector<HTMLButtonElement>('.secondary-btn')?.click();
		expect(props.onsecondary).toHaveBeenCalledTimes(1);
	});

	it('calls oncancel on Cancel and on Escape', async () => {
		const { target, props } = await render();
		target.querySelector<HTMLButtonElement>('.cancel-btn')?.click();
		expect(props.oncancel).toHaveBeenCalledTimes(1);

		window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
		expect(props.oncancel).toHaveBeenCalledTimes(2);
	});

	it('omits the secondary action when none is given', async () => {
		const { target } = await render({ secondaryLabel: undefined, onsecondary: undefined });
		expect(target.querySelector('.secondary-btn')).toBeNull();
	});

	it('marks the dialog aria-modal and labels it with the title', async () => {
		const { target } = await render();
		const dialog = target.querySelector('[role="dialog"]');
		expect(dialog?.getAttribute('aria-modal')).toBe('true');
		expect(dialog?.getAttribute('aria-label')).toBe('Unsaved changes');
	});

	it('focuses the first focusable element on open', async () => {
		const { target } = await render();
		await tick();
		expect(document.activeElement).toBe(target.querySelector('.cancel-btn'));
	});

	it('traps Tab within the dialog', async () => {
		const { target } = await render();
		await tick();
		const cancelBtn = target.querySelector<HTMLButtonElement>('.cancel-btn');
		const confirmBtn = target.querySelector<HTMLButtonElement>('.confirm-btn');
		confirmBtn?.focus();

		window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
		expect(document.activeElement).toBe(cancelBtn);

		window.dispatchEvent(
			new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true })
		);
		expect(document.activeElement).toBe(confirmBtn);
	});

	it('prevents the default action when Escape cancels', async () => {
		await render();
		const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
		window.dispatchEvent(event);
		expect(event.defaultPrevented).toBe(true);
	});

	it('cancels on a backdrop click', async () => {
		const { target, props } = await render();
		target.querySelector<HTMLButtonElement>('.overlay-backdrop')?.click();
		expect(props.oncancel).toHaveBeenCalledTimes(1);
	});
});

// The dirty-draft dialog as SongDetailView shows it: every answer closes it.
function dirtyDraftUnderBack() {
	const answers: string[] = [];
	let shown: ReturnType<typeof mount> | null = null;
	function answer(choice: string): () => void {
		return () => {
			answers.push(choice);
			if (shown) void unmount(shown);
			shown = null;
		};
	}
	return {
		answers,
		open(target: HTMLElement): void {
			answers.length = 0;
			shown = mount(ConfirmDialog, {
				target,
				props: {
					...defaultProps(),
					onconfirm: answer('save'),
					onsecondary: answer('discard'),
					oncancel: answer('keep editing')
				}
			});
			mounted.push(shown);
		}
	};
}

const dirtyDraft = dirtyDraftUnderBack();

async function renderPage(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	return target;
}

function press(target: HTMLElement, selector: string): void {
	target.querySelector<HTMLButtonElement>(selector)?.click();
}

describeBackClosesOverlay({
	name: 'the unsaved-draft dialog',
	render: renderPage,
	open: (target) => dirtyDraft.open(target),
	isShown: (target) => target.querySelector('[role="dialog"]') !== null,
	afterBack: () => expect(dirtyDraft.answers).toEqual(['keep editing']),
	closeWays: [
		{ way: 'Cancel', close: (target) => press(target, '.cancel-btn') },
		{ way: 'the backdrop', close: (target) => press(target, '.overlay-backdrop') },
		{ way: 'Save', close: (target) => press(target, '.confirm-btn') },
		{ way: 'Discard', close: (target) => press(target, '.secondary-btn') },
		{
			way: 'Escape',
			close: () =>
				window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
		}
	]
});
