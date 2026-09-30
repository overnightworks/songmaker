import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError, NetworkError } from '$lib/api/fetch';

const api = vi.hoisted(() => ({ setupAdmin: vi.fn() }));
vi.mock('$lib/api/client', () => api);
vi.mock('$app/navigation', async () =>
	(await import('$lib/test-utils/app-navigation')).fakeAppNavigation()
);

import SetupPage from './+page.svelte';

let mounted: ReturnType<typeof mount> | undefined;

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	api.setupAdmin.mockReset();
});

async function submitSetup(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(SetupPage, { target });
	await tick();
	for (const [index, value] of ['admin', 'admin-password', 'admin-password'].entries()) {
		const input = target.querySelectorAll<HTMLInputElement>('form input')[index];
		input.value = value;
		input.dispatchEvent(new Event('input', { bubbles: true }));
	}
	target.querySelector('form')?.dispatchEvent(new Event('submit', { cancelable: true }));
	return target;
}

describe('first-run setup', () => {
	it.each([
		{
			failure: 'a server refusal',
			err: new ApiError(403, 'Setup already completed', '/api/auth/setup'),
			shown: 'Setup already completed'
		},
		{
			failure: 'a lost network',
			err: new NetworkError('/api/auth/setup', new TypeError('Failed to fetch')),
			shown: 'Setup failed'
		}
	])('names $failure without browser text', async ({ err, shown }) => {
		api.setupAdmin.mockRejectedValueOnce(err);
		const target = await submitSetup();

		await vi.waitFor(() => expect(target.querySelector('.error')?.textContent).toBe(shown));
	});
});
