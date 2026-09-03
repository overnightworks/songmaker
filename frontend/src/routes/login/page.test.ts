import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AUTH_ACCOUNT_DISABLED_MESSAGE, AUTH_SESSION_EXPIRED_MESSAGE } from '$lib/constants';

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

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$lib/stores/auth', () => ({ authError, authNotice, login: mockLogin }));

import Page from './+page.svelte';

let component: ReturnType<typeof mount> | undefined;

function renderPage(): HTMLElement {
	const target = document.createElement('div');
	document.body.append(target);
	component = mount(Page, { target });
	return target;
}

beforeEach(() => {
	authError.set('');
	authNotice.set(null);
	mockLogin.mockReset();
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

	it('waits for a submitted form before attempting login', async () => {
		authNotice.set('disabled');
		renderPage();
		await tick();

		expect(mockLogin).not.toHaveBeenCalled();
	});
});
