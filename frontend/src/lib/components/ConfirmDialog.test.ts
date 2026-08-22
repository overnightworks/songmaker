import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
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
});
