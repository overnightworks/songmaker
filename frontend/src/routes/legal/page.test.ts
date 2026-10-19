import { mount, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$app/navigation', async () =>
	(await import('$lib/test-utils/app-navigation')).fakeAppNavigation()
);
vi.mock('$app/state', async () => (await import('$lib/test-utils/app-navigation')).fakeAppState());

import { goto } from '$app/navigation';
import { resolve } from '$app/paths';
import {
	installHistoryController,
	loadHistoryPageForTests,
	pageStateOfHistoryState,
	resetHistoryControllerForTests,
	stampNavigatedEntry
} from '$lib/history/historyController';
import { fakePage, startFakeRouter } from '$lib/test-utils/app-navigation';
import DatenschutzPage from '../datenschutz/+page.svelte';
import ImpressumPage from '../impressum/+page.svelte';
import Page from './+page.svelte';

let component: ReturnType<typeof mount> | undefined;

function standingEntry(): unknown {
	return pageStateOfHistoryState(history.state)?.entry;
}

// The app starts on `address` in a tab that holds `tabLength` entries, the
// way the root layout starts it.
function startAppOn(address: string, tabLength: number): void {
	history.replaceState(null, '', address);
	const length = vi.spyOn(history, 'length', 'get').mockReturnValue(tabLength);
	resetHistoryControllerForTests();
	loadHistoryPageForTests();
	startFakeRouter();
	installHistoryController();
	stampNavigatedEntry('enter');
	length.mockRestore();
}

function pressLegalBack(): void {
	fakePage.url = new URL(location.href);
	const target = document.createElement('div');
	document.body.append(target);
	component = mount(Page, { target });
	target.querySelector<HTMLButtonElement>('button[aria-label="Back"]')?.click();
}

beforeEach(() => {
	sessionStorage.clear();
});

afterEach(() => {
	if (component) unmount(component);
	component = undefined;
	document.body.replaceChildren();
	resetHistoryControllerForTests();
	vi.restoreAllMocks();
});

describe('the legal page Back', () => {
	it('returns to the sign-in page it was opened from as a history step', async () => {
		startAppOn('/login', 1);
		const signIn = standingEntry();
		await goto(resolve('/legal'));
		stampNavigatedEntry('link');

		pressLegalBack();

		await vi.waitFor(() => expect(location.pathname).toBe('/login'));
		expect(standingEntry()).toEqual(signIn);
	});

	it.each([
		{ opened: 'directly in a new tab', tabLength: 1 },
		{ opened: 'from another site', tabLength: 3 }
	])('goes to sign-in when the page was opened $opened', async ({ tabLength }) => {
		startAppOn('/legal', tabLength);
		const back = vi.spyOn(history, 'back');

		pressLegalBack();

		await vi.waitFor(() => expect(location.pathname).toBe('/login'));
		expect(back).not.toHaveBeenCalled();
	});

	it.each([
		{ arrivedFrom: 'another site', referrer: 'https://elsewhere.example/', stepsBack: false },
		{ arrivedFrom: 'a typed address', referrer: '', stepsBack: false },
		{ arrivedFrom: 'an app page', referrer: `${location.origin}/login`, stepsBack: true }
	])(
		'on a later visit in the same tab, from $arrivedFrom, returns to sign-in by history only from the app',
		async ({ referrer, stepsBack }) => {
			startAppOn('/login', 1);
			history.pushState(null, '', '/legal');
			vi.spyOn(document, 'referrer', 'get').mockReturnValue(referrer);
			startAppOn('/legal', 2);
			const back = vi.spyOn(history, 'back');

			pressLegalBack();

			await vi.waitFor(() => expect(location.pathname).toBe('/login'));
			expect(back).toHaveBeenCalledTimes(stepsBack ? 1 : 0);
		}
	);
});

describe('the legal addresses', () => {
	it.each([
		{ address: '/legal', Address: Page, heading: 'Impressum' },
		{ address: '/legal#unknown', Address: Page, heading: 'Impressum' },
		{ address: '/legal#datenschutz', Address: Page, heading: 'Datenschutzerklärung' },
		{ address: '/legal#nutzungsbedingungen', Address: Page, heading: 'Nutzungsbedingungen' },
		{ address: '/impressum', Address: ImpressumPage, heading: 'Impressum' },
		{ address: '/datenschutz', Address: DatenschutzPage, heading: 'Datenschutzerklärung' }
	])('$address shows $heading', ({ address, Address, heading }) => {
		history.replaceState(null, '', address);
		fakePage.url = new URL(location.href);
		component = mount(Address, { target: document.body });

		expect(document.querySelector('h1')?.textContent).toBe(heading);
	});
});
