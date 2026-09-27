import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError, NetworkError } from '$lib/api/fetch';

const api = vi.hoisted(() => ({ changePassword: vi.fn() }));
vi.mock('$lib/api/client', () => api);

import AccountPage from './+page.svelte';

let mounted: ReturnType<typeof mount> | undefined;

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	api.changePassword.mockReset();
});

async function submitPasswordChange(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(AccountPage, { target });
	await tick();
	for (const [index, value] of ['old-password', 'new-password', 'new-password'].entries()) {
		const input = target.querySelectorAll<HTMLInputElement>('form input')[index];
		input.value = value;
		input.dispatchEvent(new Event('input', { bubbles: true }));
	}
	target.querySelector('form')?.dispatchEvent(new Event('submit', { cancelable: true }));
	return target;
}

describe('account password change', () => {
	it.each([
		{
			failure: 'a server refusal',
			err: new ApiError(401, 'Current password is incorrect', '/api/auth/password'),
			shown: 'Current password is incorrect'
		},
		{
			failure: 'a lost network',
			err: new NetworkError('/api/auth/password', new TypeError('Failed to fetch')),
			shown: 'Password change failed'
		}
	])('names $failure without browser text', async ({ err, shown }) => {
		api.changePassword.mockRejectedValueOnce(err);
		const target = await submitPasswordChange();

		await vi.waitFor(() => expect(target.querySelector('.error')?.textContent).toBe(shown));
	});
});
