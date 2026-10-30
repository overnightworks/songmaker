import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { goto, replaceState } from '$app/navigation';
import { APP_NAME, RAIL_SETTINGS_LABEL, SETTINGS_NAV_LABEL } from '#lib/constants.ts';
import {
	installHistoryController,
	resetHistoryControllerForTests,
	stampNavigatedEntry
} from '#lib/history/historyController.ts';
import { currentUser } from '#lib/stores/auth.ts';
import { makeAuthUser } from '#lib/test-utils/factories.ts';
import {
	holdRouteLoads,
	holdShallowWrites,
	laterTask,
	reportFakeRouterEnter,
	startFakeRouter
} from '#lib/test-utils/app-navigation.ts';
import { clearPointer, setPointer } from '#lib/test-utils/hitbox.ts';

vi.mock('$app/state', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppState()
);

import SettingsPage from './+page.svelte';

let mounted: ReturnType<typeof mount> | undefined;

async function render(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(SettingsPage, { target });
	await tick();
	return target;
}

// The root layout stamps what the router reports in its own `afterNavigate`, which
// the router calls right after the page's.
function landOnPage(): void {
	reportFakeRouterEnter();
	stampNavigatedEntry('enter');
}

function listRows(target: HTMLElement): HTMLAnchorElement[] {
	return Array.from(
		target.querySelectorAll<HTMLAnchorElement>(`nav[aria-label="${SETTINGS_NAV_LABEL}"] a`)
	);
}

function rowLabels(target: HTMLElement): string[] {
	return listRows(target).map(
		(row) => row.querySelector('.settings-row-label')?.textContent?.trim() ?? ''
	);
}

beforeEach(() => {
	vi.mocked(goto).mockClear();
	vi.mocked(replaceState).mockClear();
	history.replaceState(null, '', '/settings');
	resetHistoryControllerForTests();
	startFakeRouter();
	installHistoryController();
	currentUser.set(makeAuthUser({ role: 'admin' }));
});

afterEach(async () => {
	resetHistoryControllerForTests();
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	clearPointer();
	currentUser.set(null);
});

describe('settings index on the phone', () => {
	beforeEach(() => setPointer('coarse'));

	it('lists every section an admin can open, each linking to its page, without redirecting', async () => {
		const target = await render();
		landOnPage();
		await laterTask();

		expect(rowLabels(target)).toEqual(['Generation', 'Voices', 'Admin', 'About']);
		expect(listRows(target).map((row) => row.getAttribute('href'))).toEqual([
			'/settings/generation',
			'/settings/voices',
			'/settings/users',
			'/settings/about'
		]);
		expect(goto).not.toHaveBeenCalled();
	});

	it('marks only the admin section as for admins only', async () => {
		const target = await render();

		const hints = listRows(target).map((row) => [
			row.querySelector('.settings-row-label')?.textContent?.trim(),
			row.querySelector('.settings-row-hint')?.textContent?.trim() ?? null
		]);
		expect(hints).toEqual([
			['Generation', null],
			['Voices', null],
			['Admin', 'admins only'],
			['About', null]
		]);
	});

	it('hides the admin-only sections from a non-admin', async () => {
		currentUser.set(makeAuthUser());
		const target = await render();

		expect(rowLabels(target)).toEqual(['Generation', 'Voices', 'About']);
	});

	it('names the tab after the Settings list', async () => {
		await render();

		expect(document.title).toBe(`${RAIL_SETTINGS_LABEL} — ${APP_NAME}`);
	});
});

describe('settings index on the desktop', () => {
	beforeEach(() => setPointer('fine'));

	it.each([
		{ viewer: 'an admin', user: makeAuthUser({ role: 'admin' }) },
		{ viewer: 'a non-admin', user: makeAuthUser() }
	])(
		'redirects $viewer straight into Generation, the first section they can see, and shows no list',
		async ({ user }) => {
			currentUser.set(user);
			const rendered = await render();

			landOnPage();

			await vi.waitFor(() =>
				expect(goto).toHaveBeenCalledWith('/settings/generation', { replace: true })
			);
			expect(listRows(rendered)).toHaveLength(0);
		}
	);

	it('redirects only once its own navigation was stamped and the stamp landed', async () => {
		const releaseWrites = holdShallowWrites();
		await render();
		await laterTask();
		expect(goto).not.toHaveBeenCalled();

		landOnPage();
		await laterTask();
		expect(replaceState).toHaveBeenCalledOnce();
		expect(goto).not.toHaveBeenCalled();

		await releaseWrites();
		await vi.waitFor(() => expect(goto).toHaveBeenCalledOnce());
	});

	it('redirects a page that mounts after the router landed, which `afterNavigate` never reports', async () => {
		landOnPage();
		await laterTask();

		await render();

		await vi.waitFor(() =>
			expect(goto).toHaveBeenCalledWith('/settings/generation', { replace: true })
		);
	});

	it('does not redirect while a navigation is still under way, only once it has landed', async () => {
		landOnPage();
		await laterTask();
		const releaseRouteLoads = holdRouteLoads();
		// eslint-disable-next-line svelte/no-navigation-without-resolve -- static SPA with no base path, and the fake router takes the address as is
		void goto('/settings');
		vi.mocked(goto).mockClear();

		await render();
		await laterTask();
		expect(goto).not.toHaveBeenCalled();

		releaseRouteLoads();
		await vi.waitFor(() =>
			expect(goto).toHaveBeenCalledWith('/settings/generation', { replace: true })
		);
	});

	it('does not redirect once the page was left before its navigation was stamped', async () => {
		await render();
		if (mounted) await unmount(mounted);
		mounted = undefined;

		landOnPage();
		await laterTask();

		expect(goto).not.toHaveBeenCalled();
	});
});
