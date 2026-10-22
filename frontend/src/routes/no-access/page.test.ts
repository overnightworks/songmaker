import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NO_ACCESS_BACK_LABEL, NO_ACCESS_HEADING, NO_ACCESS_MESSAGE } from '$lib/constants/auth';
import { ACCOUNT_MENU_LOGOUT_LABEL, SIGN_OUT_FAILED_MESSAGE } from '$lib/constants';
import { signOutFailed } from '$lib/stores/auth';

const mockLogout = vi.hoisted(() => vi.fn());
vi.mock('$lib/stores/auth', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/stores/auth')>()),
	logout: mockLogout
}));

import Page from './+page.svelte';

let component: ReturnType<typeof mount> | undefined;

async function renderPage(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	component = mount(Page, { target });
	await tick();
	return target;
}

beforeEach(() => {
	mockLogout.mockReset();
	signOutFailed.set(false);
});

afterEach(async () => {
	if (component) await unmount(component);
	component = undefined;
	document.body.replaceChildren();
});

describe('no-access page', () => {
	it('says the account has no access, with a name or group nowhere', async () => {
		const target = await renderPage();

		expect(target.querySelector('h1')?.textContent).toBe(NO_ACCESS_HEADING);
		expect(target.querySelector('[role="alert"]')?.textContent?.trim()).toBe(NO_ACCESS_MESSAGE);
	});

	it('offers Sign out and Back, Back leading to the signed-out page', async () => {
		const target = await renderPage();

		const actions = Array.from(target.querySelectorAll('.actions a, .actions button'));
		expect(actions.map((action) => action.textContent?.trim())).toEqual([
			ACCOUNT_MENU_LOGOUT_LABEL,
			NO_ACCESS_BACK_LABEL
		]);
		expect(actions[1].getAttribute('href')).toBe('/login');
	});

	it('logs out through the sign-out the person menu uses', async () => {
		const target = await renderPage();

		target.querySelector<HTMLButtonElement>('.actions button')?.click();

		expect(mockLogout).toHaveBeenCalledOnce();
	});

	it('tells a sign-out the server did not confirm', async () => {
		const target = await renderPage();
		signOutFailed.set(true);
		await tick();

		expect(target.textContent).toContain(SIGN_OUT_FAILED_MESSAGE);
	});
});
