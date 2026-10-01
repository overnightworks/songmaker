import { mount, tick, unmount, type ComponentProps } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import AlbumMetaEditor from './AlbumMetaEditor.svelte';
import { getByRoleButton } from '$lib/test-utils/accessible-name';
import { field, type } from '$lib/test-utils/new-place-card';

let mounted: ReturnType<typeof mount> | undefined;

type Props = ComponentProps<typeof AlbumMetaEditor>;

function baseProps(overrides: Partial<Props> = {}): Props {
	return {
		details: { title: 'Night Drive', subtitle: 'Live at the Roxy', year: '1994' },
		onsave: vi.fn().mockResolvedValue(undefined),
		onclose: vi.fn(),
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

async function submit(target: HTMLElement): Promise<void> {
	getByRoleButton(target, 'Save').click();
	await tick();
	await tick();
}

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

describe('AlbumMetaEditor', () => {
	it('opens as Edit details on the current title, subtitle and year, the title in focus', async () => {
		const target = await render(baseProps());

		expect(target.querySelector('form')?.getAttribute('aria-label')).toBe('Edit details');
		expect(field(target, 'Title').value).toBe('Night Drive');
		expect(field(target, 'Subtitle').value).toBe('Live at the Roxy');
		expect(field(target, 'Year').value).toBe('1994');
		expect(document.activeElement).toBe(field(target, 'Title'));
	});

	it('saves title, subtitle and year together, trimmed, then closes', async () => {
		const props = baseProps();
		const target = await render(props);

		type(field(target, 'Title'), ' Nightdrive ');
		type(field(target, 'Subtitle'), 'Late-night synthwave');
		type(field(target, 'Year'), '2026');
		await submit(target);

		expect(props.onsave).toHaveBeenCalledWith({
			title: 'Nightdrive',
			subtitle: 'Late-night synthwave',
			year: '2026'
		});
		expect(props.onclose).toHaveBeenCalledTimes(1);
	});

	it('× closes without saving the edited draft', async () => {
		const props = baseProps();
		const target = await render(props);

		type(field(target, 'Year'), '2026');
		getByRoleButton(target, 'Close edit details').click();
		await tick();

		expect(props.onclose).toHaveBeenCalledTimes(1);
		expect(props.onsave).not.toHaveBeenCalled();
	});

	it.each([
		['the title field', (target: HTMLElement) => field(target, 'Title')],
		['the Save button', (target: HTMLElement) => getByRoleButton(target, 'Save')]
	])('Escape in %s closes without saving and claims the Escape', async (_where, focusOf) => {
		const props = baseProps();
		const target = await render(props);
		type(field(target, 'Year'), '2026');

		const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
		focusOf(target).dispatchEvent(escape);

		expect(props.onclose).toHaveBeenCalledTimes(1);
		expect(props.onsave).not.toHaveBeenCalled();
		expect(escape.defaultPrevented).toBe(true);
	});

	it('neither × nor Escape closes while a save is in flight', async () => {
		const props = baseProps({ onsave: vi.fn(() => new Promise<void>(() => {})) });
		const target = await render(props);

		await submit(target);
		const close = getByRoleButton(target, 'Close edit details');
		close.click();
		field(target, 'Title').dispatchEvent(
			new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
		);

		expect(close.disabled).toBe(true);
		expect(props.onclose).not.toHaveBeenCalled();
	});

	it('offers no Save while the title is blank and names why beside the title', async () => {
		const target = await render(baseProps());
		expect(target.querySelector('[role="alert"]')).toBeNull();

		type(field(target, 'Title'), '   ');

		expect(getByRoleButton(target, 'Save').disabled).toBe(true);
		expect(target.querySelector('[role="alert"]')?.textContent?.trim()).toBe(
			'Title cannot be empty'
		);
		expect(field(target, 'Title').getAttribute('aria-invalid')).toBe('true');
	});

	it('Escape with the focus outside the form closes it without saving', async () => {
		const props = baseProps();
		await render(props);
		const outside = document.createElement('button');
		document.body.append(outside);
		outside.focus();

		outside.dispatchEvent(
			new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
		);

		expect(props.onclose).toHaveBeenCalledTimes(1);
		expect(props.onsave).not.toHaveBeenCalled();
	});

	it('leaves an Escape an open popover already claimed to that popover', async () => {
		const props = baseProps();
		const target = await render(props);
		const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
		escape.preventDefault();

		field(target, 'Title').dispatchEvent(escape);

		expect(props.onclose).not.toHaveBeenCalled();
	});

	it('stays open with the draft when the save is refused', async () => {
		const props = baseProps({ onsave: vi.fn().mockRejectedValue(new Error('refused')) });
		const target = await render(props);

		type(field(target, 'Year'), '1850');
		await submit(target);

		expect(props.onclose).not.toHaveBeenCalled();
		expect(field(target, 'Year').value).toBe('1850');
		expect(getByRoleButton(target, 'Save').disabled).toBe(false);
	});
});
