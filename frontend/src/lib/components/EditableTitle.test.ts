import { mount, tick, unmount, type ComponentProps } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { words } from '#lib/words/en.ts';
import EditableTitle from './EditableTitle.svelte';
import { getByRoleButton } from '#lib/test-utils/accessible-name.ts';

let mounted: ReturnType<typeof mount> | undefined;

function requireElement<T extends Element>(root: ParentNode, selector: string): T {
	const element = root.querySelector<T>(selector);
	if (!element) throw new Error(`Expected ${selector} to be rendered`);
	return element;
}

type EditableTitleProps = ComponentProps<typeof EditableTitle>;

async function render(
	props: Pick<EditableTitleProps, 'value' | 'onsave'> & Partial<EditableTitleProps>
): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(EditableTitle, {
		target,
		props: {
			labelKey: 'songHeader.title',
			editLabelKey: 'songHeader.editTitle',
			...props
		}
	});
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
			labelKey: 'collectionHeader.titleAlbum',
			editLabelKey: 'collectionHeader.editTitleAlbum'
		});
		const display = requireElement<HTMLButtonElement>(target, '.editable-title-display');
		expect(display.textContent?.trim()).toBe('Night Drive');
		expect(getByRoleButton(target, words['collectionHeader.editTitleAlbum'])).toBe(display);
		expect(display.title).toBe(words['editableTitle.hint']);
	});

	it('names the field by its own key while editing', async () => {
		const target = await render({
			value: 'Night Drive',
			onsave: vi.fn().mockResolvedValue(undefined),
			labelKey: 'collectionHeader.titlePlaylist',
			editLabelKey: 'collectionHeader.editTitlePlaylist'
		});
		requireElement<HTMLButtonElement>(target, '.editable-title-display').click();
		await tick();
		expect(requireElement<HTMLInputElement>(target, '.editable-title-input').ariaLabel).toBe(
			words['collectionHeader.titlePlaylist']
		);
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

	it('reverts an emptied field by default instead of committing an empty value', async () => {
		const onsave = vi.fn().mockResolvedValue(undefined);
		const target = await render({ value: 'Night Drive', onsave });
		requireElement<HTMLButtonElement>(target, '.editable-title-display').click();
		await tick();
		const input = requireElement<HTMLInputElement>(target, '.editable-title-input');
		input.value = '   ';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
		await tick();
		expect(onsave).not.toHaveBeenCalled();
		expect(target.querySelector('.editable-title-input')).toBeNull();
	});

	it('keeps the field in edit mode with the draft intact when onsave rejects', async () => {
		const onsave = vi.fn().mockRejectedValue(new Error('save failed'));
		const target = await render({ value: 'Night Drive', onsave });
		requireElement<HTMLButtonElement>(target, '.editable-title-display').click();
		await tick();
		const input = requireElement<HTMLInputElement>(target, '.editable-title-input');
		input.value = 'Sunset Drive';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
		await vi.waitFor(() => expect(onsave).toHaveBeenCalledWith('Sunset Drive'));
		await tick();
		const stillEditing = requireElement<HTMLInputElement>(target, '.editable-title-input');
		expect(stillEditing.value).toBe('Sunset Drive');
		expect(stillEditing.disabled).toBe(false);
	});

	it('saves once when the browser blurs the field it disabled for the save', async () => {
		let rejectSave: (reason: Error) => void = () => {};
		const onsave = vi.fn(() => new Promise<void>((_resolve, reject) => (rejectSave = reject)));
		const target = await render({ value: 'Night Drive', onsave });
		requireElement<HTMLButtonElement>(target, '.editable-title-display').click();
		await tick();
		const input = requireElement<HTMLInputElement>(target, '.editable-title-input');
		input.value = 'Sunset Drive';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
		await tick();
		expect(input.disabled).toBe(true);
		input.dispatchEvent(new FocusEvent('blur'));
		rejectSave(new Error('Rename failed'));
		await tick();

		expect(onsave).toHaveBeenCalledTimes(1);
	});
});
