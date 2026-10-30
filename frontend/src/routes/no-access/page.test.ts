import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { APP_NAME, SIGN_OUT_FAILED_MESSAGE } from '#lib/constants.ts';
import { signOutFailed } from '#lib/stores/auth.ts';

const mockLogout = vi.hoisted(() => vi.fn());
vi.mock('#lib/stores/auth.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/stores/auth.ts')>()),
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

function logOutButton(target: HTMLElement): HTMLButtonElement | undefined {
	return Array.from(target.querySelectorAll('button')).find(
		(button) => button.textContent?.trim() === 'Log out'
	);
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
	it('says the account has no access to the app, with a name or group nowhere', async () => {
		const target = await renderPage();

		expect(target.querySelector('h1')?.textContent).toBe('No access');
		expect(target.textContent).toContain(
			`You are signed in, but this account has no access to ${APP_NAME}.`
		);
	});

	it('offers Log out as its one way on', async () => {
		const target = await renderPage();

		expect(logOutButton(target)).toBeDefined();
		expect(target.querySelectorAll('main a')).toHaveLength(0);
	});

	it('logs out through the sign-out the person menu uses', async () => {
		const target = await renderPage();

		logOutButton(target)?.click();

		expect(mockLogout).toHaveBeenCalledOnce();
	});

	it('shows no alert while the sign-out has not failed', async () => {
		const target = await renderPage();

		expect(target.querySelector('[role="alert"]')).toBeNull();
	});

	it('tells a sign-out the server did not confirm, as an alert', async () => {
		const target = await renderPage();
		signOutFailed.set(true);
		await tick();

		expect(target.querySelector('[role="alert"]')?.textContent).toBe(SIGN_OUT_FAILED_MESSAGE);
	});
});
