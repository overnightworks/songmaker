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
import {
	ACCOUNT_MENU_LABEL,
	ACCOUNT_MENU_LOGOUT_LABEL,
	APP_NAME,
	HITBOX_FREQUENT_PX,
	RAIL_DRAWER_OPEN_LABEL
} from '$lib/constants';
import PhoneAppBar from './PhoneAppBar.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

const ACCOUNT_CIRCLE_NAME = `${ACCOUNT_MENU_LABEL} · felix`;

function renderBar(onlogout = vi.fn()): HTMLElement {
	const target = document.createElement('div');
	target.style.width = '390px';
	document.body.append(target);
	mounted.push(mount(PhoneAppBar, { target, props: { username: 'felix', onlogout } }));
	return target;
}

function expectFrequentHitbox(button: HTMLButtonElement, name: string): void {
	expect(button.dataset.hitbox).toBe('frequent');
	expect(minSquarePx(button, name)).toEqual({
		width: HITBOX_FREQUENT_PX,
		height: HITBOX_FREQUENT_PX
	});
}

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
			kind: 'song',
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
		const target = renderBar();
		await tick();
		expect(target.querySelector('header')?.children).toHaveLength(4);
		expect(target.querySelector('h1')?.textContent?.trim()).toBe('Sommerlicht');
		expect(target.querySelector('.brand')).toBeNull();
		expect(() => getByRoleButton(target, ACCOUNT_CIRCLE_NAME)).toThrow();
		for (const name of [RAIL_DRAWER_OPEN_LABEL, 'Share song', 'Song menu']) {
			expectFrequentHitbox(getByRoleButton(target, name), name);
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

	it("carries the viewer's account circle at the right on a library screen", async () => {
		const target = renderBar();
		await tick();

		const header = target.querySelector('header');
		expect(header?.textContent).toContain(APP_NAME);
		const circle = getByRoleButton(target, ACCOUNT_CIRCLE_NAME);
		expect(circle.textContent?.trim()).toBe('F');
		expect(header?.lastElementChild?.contains(circle)).toBe(true);
		expectFrequentHitbox(circle, ACCOUNT_CIRCLE_NAME);
	});

	it('keeps Log out off the bar and one tap away in the account menu', async () => {
		const onlogout = vi.fn();
		const target = renderBar(onlogout);
		await tick();
		const bar = target.querySelector('header');
		if (!bar) throw new Error('Expected the app bar');
		const logoutOnBar = () => getByRoleButton(bar, ACCOUNT_MENU_LOGOUT_LABEL);
		expect(logoutOnBar).toThrow();

		getByRoleButton(target, ACCOUNT_CIRCLE_NAME).click();
		await tick();
		getByRoleButton(document.body, ACCOUNT_MENU_LOGOUT_LABEL).click();

		expect(onlogout).toHaveBeenCalledOnce();
	});
});
