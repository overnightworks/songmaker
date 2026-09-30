import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { APP_NAME, RAIL_SETTINGS_LABEL, SETTINGS_NAV_LABEL } from '$lib/constants';
import { visibleSettingsSections } from '$lib/settingsSections';
import { currentUser } from '$lib/stores/auth';
import { clearPointer, setPointer } from '$lib/test-utils/hitbox';

const navigation = vi.hoisted(() => ({ goto: vi.fn() }));
vi.mock('$app/navigation', () => navigation);

import SettingsPage from './+page.svelte';

const ADMIN = { id: 'u1', username: 'felix', role: 'admin' as const };
const USER = { id: 'u2', username: 'jane', role: 'user' as const };

let mounted: ReturnType<typeof mount> | undefined;

async function render(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(SettingsPage, { target });
	await tick();
	return target;
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
	navigation.goto.mockReset();
	currentUser.set(ADMIN);
});

afterEach(async () => {
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

		expect(rowLabels(target)).toEqual([
			'Generation',
			'Playback',
			'Voices',
			'Account',
			'Admin',
			'Cleanup',
			'Legal'
		]);
		expect(listRows(target).map((row) => row.getAttribute('href'))).toEqual(
			visibleSettingsSections(true).map((section) => section.href)
		);
		expect(navigation.goto).not.toHaveBeenCalled();
	});

	it('hides the admin-only sections from a non-admin', async () => {
		currentUser.set(USER);
		const target = await render();

		expect(rowLabels(target)).toEqual(['Generation', 'Playback', 'Voices', 'Account', 'Legal']);
	});

	it('names the tab after the Settings list', async () => {
		await render();

		expect(document.title).toBe(`${RAIL_SETTINGS_LABEL} — ${APP_NAME}`);
	});

	it('shows the signed-in username beside Account', async () => {
		const target = await render();
		const account = listRows(target).find(
			(row) => row.getAttribute('href') === '/settings/account'
		);

		expect(account?.querySelector('.settings-row-value')?.textContent?.trim()).toBe('felix');
	});
});

describe('settings index on the desktop', () => {
	beforeEach(() => setPointer('fine'));

	it.each([
		{ viewer: 'an admin', user: ADMIN, admin: true },
		{ viewer: 'a non-admin', user: USER, admin: false }
	])(
		'redirects $viewer straight into the first section they can see and shows no list',
		async ({ user, admin }) => {
			currentUser.set(user);
			const rendered = await render();

			const [firstVisible] = visibleSettingsSections(admin);
			expect(navigation.goto).toHaveBeenCalledWith(firstVisible?.href, { replaceState: true });
			expect(listRows(rendered)).toHaveLength(0);
		}
	);
});
