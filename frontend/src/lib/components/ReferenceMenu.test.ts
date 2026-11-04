import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ReferenceMenu from './ReferenceMenu.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

async function openReferenceMenu(inUse: boolean, ondelete = vi.fn()): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(
		mount(ReferenceMenu, { target, props: { filename: 'voice-memo.mp3', inUse, ondelete } })
	);
	await tick();
	target.querySelector<HTMLButtonElement>('[aria-haspopup="dialog"]')?.click();
	await tick();
	return document.body;
}

afterEach(async () => {
	await Promise.all(mounted.splice(0).map((component) => unmount(component)));
	document.body.replaceChildren();
});

describe('ReferenceMenu', () => {
	it('heads the menu with the filename', async () => {
		const body = await openReferenceMenu(false);

		expect(body.querySelector('.menu-heading')?.textContent).toBe('voice-memo.mp3');
	});

	it('offers Delete for an unused reference and reports the choice', async () => {
		const ondelete = vi.fn();
		const body = await openReferenceMenu(false, ondelete);
		const button = Array.from(body.querySelectorAll('button')).find(
			(candidate) => candidate.textContent?.trim() === 'Delete'
		) as HTMLButtonElement;

		expect(button.disabled).toBe(false);
		button.click();
		expect(ondelete).toHaveBeenCalledOnce();
	});

	it('greys Delete for a used reference and names the reason in its accessible name', async () => {
		const ondelete = vi.fn();
		const body = await openReferenceMenu(true, ondelete);
		const button = Array.from(body.querySelectorAll<HTMLButtonElement>('button')).find(
			(candidate) => candidate.textContent?.includes('Delete')
		) as HTMLButtonElement;

		expect(button.disabled).toBe(true);
		expect(button.textContent).toContain('In use');
		expect(button.querySelector('[aria-hidden="true"]')).toBeNull();
		button.click();
		expect(ondelete).not.toHaveBeenCalled();
	});
});
