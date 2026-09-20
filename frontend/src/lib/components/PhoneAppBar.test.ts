import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { phoneAppBar, sidebarOpen } from '$lib/stores/ui';
import { getByRoleButton } from '$lib/test-utils/accessible-name';
import {
	clearHitboxStyles,
	clearPointer,
	injectHitboxStyles,
	minSquarePx,
	setPointer
} from '$lib/test-utils/hitbox';
import { HITBOX_FREQUENT_PX, RAIL_DRAWER_OPEN_LABEL } from '$lib/constants';
import PhoneAppBar from './PhoneAppBar.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

beforeEach(() => {
	injectHitboxStyles();
	setPointer('coarse');
	phoneAppBar.set(null);
	sidebarOpen.set(false);
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	phoneAppBar.set(null);
	sidebarOpen.set(false);
	clearHitboxStyles();
	clearPointer();
	document.body.replaceChildren();
});

describe('PhoneAppBar', () => {
	it('offers four song slots with named touch actions and inline rename', async () => {
		const onrename = vi.fn(async () => undefined);
		phoneAppBar.set({
			title: 'Sommerlicht',
			onrename,
			share: {
				isShared: false,
				shareSlug: null,
				onshare: vi.fn(),
				onunshare: vi.fn()
			},
			menu: {
				saveDisabled: true,
				onsave: vi.fn(),
				onaddtoplaylist: vi.fn(),
				ondelete: vi.fn()
			}
		});
		const target = document.createElement('div');
		target.style.width = '390px';
		document.body.append(target);
		mounted.push(mount(PhoneAppBar, { target }));
		await tick();
		expect(target.querySelector('header')?.children).toHaveLength(4);
		expect(target.querySelector('h1')?.textContent?.trim()).toBe('Sommerlicht');
		expect(target.querySelector('.brand')).toBeNull();
		for (const name of [RAIL_DRAWER_OPEN_LABEL, 'Share song', 'Song menu']) {
			const button = getByRoleButton(target, name);
			expect(button.dataset.hitbox).toBe('frequent');
			expect(minSquarePx(button, name)).toEqual({
				width: HITBOX_FREQUENT_PX,
				height: HITBOX_FREQUENT_PX
			});
		}
		getByRoleButton(target, RAIL_DRAWER_OPEN_LABEL).click();
		await tick();
		expect(get(sidebarOpen)).toBe(true);
		getByRoleButton(target, 'Song menu').click();
		await tick();
		getByRoleButton(target, 'Rename').click();
		await tick();
		const input = target.querySelector<HTMLInputElement>('input[aria-label="Song title"]');
		if (!input) throw new Error('Expected inline title input');
		input.value = 'Abendlicht';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
		await tick();
		expect(onrename).toHaveBeenCalledWith('Abendlicht');
	});
});
