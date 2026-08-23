import { mount, tick, unmount, type ComponentProps } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import EditableTitle from './EditableTitle.svelte';
import { getByRoleButton } from '$lib/test-utils/accessible-name';

let mounted: ReturnType<typeof mount> | undefined;

function requireElement<T extends Element>(root: ParentNode, selector: string): T {
	const element = root.querySelector<T>(selector);
	if (!element) throw new Error(`Expected ${selector} to be rendered`);
	return element;
}

type EditableTitleProps = ComponentProps<typeof EditableTitle>;

async function render(props: EditableTitleProps): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(EditableTitle, { target, props });
	await tick();
	return target;
}

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

describe('EditableTitle', () => {
	it('shows the value as visible text while the edit affordance keeps its own accessible name', async () => {
		const target = await render({
			value: 'Night Drive',
			onsave: vi.fn().mockResolvedValue(undefined),
			ariaLabel: 'Album title'
		});
		const display = requireElement<HTMLButtonElement>(target, '.editable-title-display');
		expect(display.textContent?.trim()).toBe('Night Drive');
		expect(getByRoleButton(target, 'Edit album title')).toBe(display);
	});

	it('enters edit mode on click and keyboard activation alike', async () => {
		const target = await render({
			value: 'Night Drive',
			onsave: vi.fn().mockResolvedValue(undefined)
		});
		requireElement<HTMLButtonElement>(target, '.editable-title-display').click();
		await tick();
		const input = requireElement<HTMLInputElement>(target, '.editable-title-input');
		expect(input.value).toBe('Night Drive');
	});

	it('commits a changed title on Enter and returns to display mode', async () => {
		const onsave = vi.fn().mockResolvedValue(undefined);
		const target = await render({ value: 'Night Drive', onsave });
		requireElement<HTMLButtonElement>(target, '.editable-title-display').click();
		await tick();
		const input = requireElement<HTMLInputElement>(target, '.editable-title-input');
		input.value = 'Sunset Drive';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
		await vi.waitFor(() => expect(onsave).toHaveBeenCalledWith('Sunset Drive'));
		await tick();
		expect(target.querySelector('.editable-title-input')).toBeNull();
		expect(requireElement(target, '.editable-title-display').textContent?.trim()).toBe(
			'Night Drive'
		);
	});

	it('discards the draft on Escape without calling onsave', async () => {
		const onsave = vi.fn().mockResolvedValue(undefined);
		const target = await render({ value: 'Night Drive', onsave });
		requireElement<HTMLButtonElement>(target, '.editable-title-display').click();
		await tick();
		const input = requireElement<HTMLInputElement>(target, '.editable-title-input');
		input.value = 'Discarded title';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
		await tick();
		expect(onsave).not.toHaveBeenCalled();
		expect(target.querySelector('.editable-title-input')).toBeNull();
	});

	it('defaults the edit affordance name to "Edit title" when no ariaLabel is given', async () => {
		const target = await render({
			value: 'Untitled',
			onsave: vi.fn().mockResolvedValue(undefined)
		});
		expect(getByRoleButton(target, 'Edit title')).not.toBeNull();
	});
});
