import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';

import { currentUser } from '$lib/stores/auth';
import AccountPage from './+page.svelte';

let mounted: ReturnType<typeof mount> | undefined;

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	currentUser.set(null);
});

async function renderAccountFor(role: 'admin' | 'user'): Promise<HTMLElement> {
	currentUser.set({ id: 'u1', username: 'felix', role });
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(AccountPage, { target });
	await tick();
	return target;
}

describe('account page', () => {
	it.each([
		['admin', 'Admin'],
		['user', 'Member']
	] as const)('names a %s account by username and role', async (role, shown) => {
		const target = await renderAccountFor(role);

		expect(target.querySelector('.username')?.textContent).toBe('felix');
		expect(target.querySelector('.role')?.textContent).toBe(shown);
	});

	it('offers no password form', async () => {
		const target = await renderAccountFor('user');

		expect(target.querySelector('form, input')).toBeNull();
	});
});
