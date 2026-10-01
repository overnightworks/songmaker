import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AUTH_ACCOUNT_DISABLED_MESSAGE, AUTH_SESSION_EXPIRED_MESSAGE } from '$lib/constants/auth';

const { authError, authNotice, mockLogin } = vi.hoisted(() => ({
	authError: store(''),
	authNotice: store<'unauthorized' | 'disabled' | null>(null),
	mockLogin: vi.fn()
}));

function store<T>(initial: T) {
	let value = initial;
	const subscribers = new Set<(next: T) => void>();
	return {
		subscribe(subscriber: (next: T) => void) {
			subscriber(value);
			subscribers.add(subscriber);
			return () => subscribers.delete(subscriber);
		},
		set(next: T) {
			value = next;
			subscribers.forEach((subscriber) => subscriber(value));
		}
	};
}

vi.mock('$app/navigation', async () =>
	(await import('$lib/test-utils/app-navigation')).fakeAppNavigation()
);
vi.mock('$app/state', async () => (await import('$lib/test-utils/app-navigation')).fakeAppState());
vi.mock('$lib/stores/auth', () => ({ authError, authNotice, login: mockLogin }));

import { goto } from '$app/navigation';
import { fakePage } from '$lib/test-utils/app-navigation';
import Page from './+page.svelte';

let component: ReturnType<typeof mount> | undefined;

function renderPage(address = '/login'): HTMLElement {
	fakePage.url = new URL(address, window.location.origin);
	const target = document.createElement('div');
	document.body.append(target);
	component = mount(Page, { target });
	return target;
}

beforeEach(() => {
	authError.set('');
	authNotice.set(null);
	mockLogin.mockReset();
	vi.mocked(goto).mockClear();
});

afterEach(async () => {
	if (component) await unmount(component);
	component = undefined;
	document.body.replaceChildren();
});

describe('login page', () => {
	it('shows the disabled-account notice', async () => {
		authNotice.set('disabled');
		const target = renderPage();
		await tick();

		expect(target.querySelector('.error')?.textContent).toBe(AUTH_ACCOUNT_DISABLED_MESSAGE);
	});

	it('shows the expired-session notice', async () => {
		authNotice.set('unauthorized');
		const target = renderPage();
		await tick();

		expect(target.querySelector('.error')?.textContent).toBe(AUTH_SESSION_EXPIRED_MESSAGE);
	});

	it('says nothing about an expired session without a notice', async () => {
		const target = renderPage();
		await tick();

		expect(target.querySelector('.error')).toBeNull();
	});

	it.each([
		[
			'the asked-for song',
			'/login?redirect=%2Falbum%2Fnorthern-lights%2Fglass-river',
			'/album/northern-lights/glass-river'
		],
		['the library without a target', '/login', '/'],
		[
			'the library instead of a foreign site',
			`/login?redirect=${encodeURIComponent('https://attacker.example/x')}`,
			'/'
		],
		[
			'the library instead of a foreign host',
			`/login?redirect=${encodeURIComponent('//attacker.example/x')}`,
			'/'
		]
	])('signs in and lands on %s', async (_label, address, landing) => {
		mockLogin.mockResolvedValueOnce({ id: 'u1', username: 'felix', role: 'user' });
		const target = renderPage(address);
		await tick();

		target.querySelector('form')?.dispatchEvent(new SubmitEvent('submit', { cancelable: true }));

		await vi.waitFor(() => expect(goto).toHaveBeenCalledWith(landing, { replaceState: true }));
	});

	it('waits for a submitted form before attempting login', async () => {
		authNotice.set('disabled');
		renderPage();
		await tick();

		expect(mockLogin).not.toHaveBeenCalled();
	});
});
