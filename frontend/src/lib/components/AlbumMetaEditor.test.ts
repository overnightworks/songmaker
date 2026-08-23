import { mount, tick, unmount, type ComponentProps } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import AlbumMetaEditor from './AlbumMetaEditor.svelte';
import { getByRoleButton } from '$lib/test-utils/accessible-name';

let mounted: ReturnType<typeof mount> | undefined;

function requireElement<T extends Element>(root: ParentNode, selector: string): T {
	const element = root.querySelector<T>(selector);
	if (!element) throw new Error(`Expected ${selector} to be rendered`);
	return element;
}

function requireAll<T extends Element>(root: ParentNode, selector: string): T[] {
	return Array.from(root.querySelectorAll<T>(selector));
}

type Props = ComponentProps<typeof AlbumMetaEditor>;

function baseProps(overrides: Partial<Props> = {}): Props {
	return {
		subtitle: 'Live at the Roxy',
		year: '1994',
		onsavesubtitle: vi.fn().mockResolvedValue(undefined),
		onsaveyear: vi.fn().mockResolvedValue(undefined),
		...overrides
	};
}

async function render(props: Props): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(AlbumMetaEditor, { target, props });
	await tick();
	return target;
}

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

describe('AlbumMetaEditor', () => {
	it('shows the current subtitle and year, each independently named', async () => {
		const target = await render(baseProps());
		const [subtitleDisplay, yearDisplay] = requireAll<HTMLButtonElement>(
			target,
			'.editable-title-display'
		);
		expect(subtitleDisplay.textContent?.trim()).toBe('Live at the Roxy');
		expect(yearDisplay.textContent?.trim()).toBe('1994');
		expect(getByRoleButton(target, 'Edit album subtitle')).toBe(subtitleDisplay);
		expect(getByRoleButton(target, 'Edit album year')).toBe(yearDisplay);
	});

	it('shows placeholders and commits an edited subtitle', async () => {
		const onsavesubtitle = vi.fn().mockResolvedValue(undefined);
		const target = await render(baseProps({ subtitle: '', onsavesubtitle }));
		const display = getByRoleButton(target, 'Edit album subtitle');
		expect(display.textContent?.trim()).toBe('Add subtitle');

		display.click();
		await tick();
		const input = requireElement<HTMLInputElement>(target, '.editable-title-input');
		input.value = 'Remastered';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
		await vi.waitFor(() => expect(onsavesubtitle).toHaveBeenCalledWith('Remastered'));
	});

	it('clears the subtitle when emptied', async () => {
		const onsavesubtitle = vi.fn().mockResolvedValue(undefined);
		const target = await render(baseProps({ onsavesubtitle }));
		requireElement<HTMLButtonElement>(target, '.editable-title-display').click();
		await tick();
		const input = requireElement<HTMLInputElement>(target, '.editable-title-input');
		input.value = '';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
		await vi.waitFor(() => expect(onsavesubtitle).toHaveBeenCalledWith(''));
	});

	it('commits an edited year through the numeric field', async () => {
		const onsaveyear = vi.fn().mockResolvedValue(undefined);
		const target = await render(baseProps({ onsaveyear }));
		const yearButton = getByRoleButton(target, 'Edit album year');
		yearButton.click();
		await tick();
		const inputs = requireAll<HTMLInputElement>(target, '.editable-title-input');
		const input = inputs[0];
		input.value = '2001';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
		await vi.waitFor(() => expect(onsaveyear).toHaveBeenCalledWith('2001'));
	});

	it('cancels an edit on Escape without calling either save handler', async () => {
		const onsavesubtitle = vi.fn().mockResolvedValue(undefined);
		const onsaveyear = vi.fn().mockResolvedValue(undefined);
		const target = await render(baseProps({ onsavesubtitle, onsaveyear }));
		requireElement<HTMLButtonElement>(target, '.editable-title-display').click();
		await tick();
		const input = requireElement<HTMLInputElement>(target, '.editable-title-input');
		input.value = 'Discarded';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
		await tick();
		expect(onsavesubtitle).not.toHaveBeenCalled();
		expect(onsaveyear).not.toHaveBeenCalled();
		expect(target.querySelector('.editable-title-input')).toBeNull();
	});
});
