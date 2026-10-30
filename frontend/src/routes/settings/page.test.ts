import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { APP_NAME, RAIL_SETTINGS_LABEL, SETTINGS_NAV_LABEL } from '#lib/constants.ts';
import { currentUser } from '#lib/stores/auth.ts';
import { makeAuthUser } from '#lib/test-utils/factories.ts';
import { clearPointer, setPointer } from '#lib/test-utils/hitbox.ts';

const navigation = vi.hoisted(() => ({ goto: vi.fn() }));
vi.mock('$app/navigation', () => navigation);

import SettingsPage from './+page.svelte';

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
	currentUser.set(makeAuthUser({ role: 'admin' }));
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

		expect(rowLabels(target)).toEqual(['Generation', 'Voices', 'Admin']);
		expect(listRows(target).map((row) => row.getAttribute('href'))).toEqual([
			'/settings/generation',
			'/settings/voices',
			'/settings/users'
		]);
		expect(navigation.goto).not.toHaveBeenCalled();
	});

	it('hides the admin-only sections from a non-admin', async () => {
		currentUser.set(makeAuthUser());
		const target = await render();

		expect(rowLabels(target)).toEqual(['Generation', 'Voices']);
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

			expect(navigation.goto).toHaveBeenCalledWith('/settings/generation', {
				replaceState: true
			});
			expect(listRows(rendered)).toHaveLength(0);
		}
	);
});
