import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import SongMenu from './SongMenu.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
});

function defaultProps() {
	return {
		title: 'Sommerlicht',
		isShared: false,
		shareSlug: null,
		onshare: vi.fn(async () => ({
			status: 'ok',
			share_url: '',
			share_slug: 's',
			songs_without_playable_take: []
		})),
		onunshare: vi.fn(async () => undefined),
		onrename: vi.fn(),
		onsaveversion: vi.fn(),
		onaddtoplaylist: vi.fn(),
		ondelete: vi.fn()
	};
}

async function renderMenu(overrides: Partial<ReturnType<typeof defaultProps>> = {}) {
	const target = document.createElement('div');
	document.body.append(target);
	const props = { ...defaultProps(), ...overrides };
	mounted.push(mount(SongMenu, { target, props }));
	await tick();
	return { target, props };
}

describe('SongMenu', () => {
	it('names the song on the first row and lists its actions', async () => {
		const { target } = await renderMenu();
		target.querySelector<HTMLButtonElement>('.menu-trigger')?.click();
		await tick();
		expect(target.querySelector('.menu-heading')?.textContent).toBe('Song · Sommerlicht');
		expect(target.querySelector('.menu-row-label')?.textContent).toBe('Share song');
		const items = Array.from(target.querySelectorAll('.menu-item')).map((el) =>
			el.textContent?.trim()
		);
		expect(items).toContain('Rename');
		expect(items).toContain('Save version');
		expect(items).toContain('Add to playlist');
		expect(items).toContain('Delete song');
	});

	it('runs the action and closes the menu on click', async () => {
		const { target, props } = await renderMenu();
		target.querySelector<HTMLButtonElement>('.menu-trigger')?.click();
		await tick();
		const rename = Array.from(target.querySelectorAll<HTMLButtonElement>('.menu-item')).find(
			(el) => el.textContent?.trim() === 'Rename'
		);
		rename?.click();
		await tick();
		expect(props.onrename).toHaveBeenCalledTimes(1);
		expect(target.querySelector('.menu-panel')).toBeNull();
	});

	it('saves a version from the menu', async () => {
		const { target, props } = await renderMenu();
		target.querySelector<HTMLButtonElement>('.menu-trigger')?.click();
		await tick();
		const saveVersion = Array.from(target.querySelectorAll<HTMLButtonElement>('.menu-item')).find(
			(el) => el.textContent?.trim() === 'Save version'
		);
		saveVersion?.click();
		await tick();
		expect(props.onsaveversion).toHaveBeenCalledTimes(1);
	});

	it('closes on Escape without triggering an action', async () => {
		const { target } = await renderMenu();
		target.querySelector<HTMLButtonElement>('.menu-trigger')?.click();
		await tick();
		window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
		await tick();
		expect(target.querySelector('.menu-panel')).toBeNull();
	});
});
