import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import type { Place } from '#lib/stores/libraryContext.ts';
import { reactiveProps } from '../../../tests/reactive-fixtures.svelte';
import Icon from '../Icon.svelte';
import PhoneTabs from './PhoneTabs.svelte';

const tabs = [
	{ place: 'home', label: 'Home', icon: 'home' },
	{ place: 'library', label: 'Library', icon: 'library' },
	{ place: 'playlists', label: 'Playlists', icon: 'playlists' }
] as const;
const routes = [
	{ pathname: '/', current: 'Home' },
	{ pathname: '/library', current: 'Library' },
	{ pathname: '/playlists', current: 'Playlists' },
	{ pathname: '/album/a1', current: 'Library' },
	{ pathname: '/album/a1/song', current: 'Library' },
	{ pathname: '/album/a1/song/take/1', current: 'Library' },
	{ pathname: '/playlist/p1', current: 'Playlists' },
	{ pathname: '/settings', current: null },
	{ pathname: '/settings/generation', current: null },
	{ pathname: '/loras', current: null },
	{ pathname: '/jobs', current: null },
	{ pathname: '/share/album/shared', current: null }
];
const mounted: ReturnType<typeof mount>[] = [];

async function render(pathname = '/') {
	const target = document.createElement('div');
	document.body.append(target);
	const selected: Place[] = [];
	const props = reactiveProps({ pathname, onSelect: (place: Place) => selected.push(place) });
	mounted.push(mount(PhoneTabs, { target, props }));
	await tick();
	return { target, props, selected, buttons: Array.from(target.querySelectorAll('button')) };
}

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
});

describe('PhoneTabs', () => {
	it('1354_37b_70_order: renders Home, Library, Playlists in order', async () => {
		const { buttons } = await render();
		expect(buttons.map((button) => button.textContent?.trim())).toEqual(
			tabs.map((tab) => tab.label)
		);
	});

	it.each(tabs)('1354_37b_70_icons: $label reuses its place icon', async ({ label, icon }) => {
		const { buttons } = await render();
		const reference = document.createElement('div');
		mounted.push(mount(Icon, { target: reference, props: { name: icon, size: 22 } }));
		await tick();
		const button = buttons.find((button) => button.textContent?.trim() === label);
		expect(button?.querySelector('svg')?.innerHTML).toBe(reference.querySelector('svg')?.innerHTML);
		expect(button?.querySelector('[aria-hidden="true"] svg')).not.toBeNull();
	});

	it.each(routes)('1354_37b_70_marks: $pathname marks $current', async ({ pathname, current }) => {
		const { target, props } = await render('/library');
		props.pathname = pathname;
		await tick();
		expect(
			Array.from(target.querySelectorAll('[aria-current="page"]'), (tab) => tab.textContent?.trim())
		).toEqual(current === null ? [] : [current]);
	});

	it.each(tabs)('1354_37b_70_selection: $label selects $place', async ({ place, label }) => {
		const { buttons, selected } = await render('/settings');
		buttons.find((button) => button.textContent?.trim() === label)?.click();
		await tick();
		expect(selected).toEqual([place]);
	});
});
