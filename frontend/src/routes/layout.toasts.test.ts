import { createRawSnippet, flushSync, mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { fakePage, reportFakeRouterEnter } from '#lib/test-utils/app-navigation.ts';
import { makeAuthUser } from '#lib/test-utils/factories.ts';
import { authLoading, currentUser, resetAuthForTests } from '#lib/stores/auth.ts';
import { addToast, toasts } from '#lib/stores/toast.ts';

vi.mock('$app/state', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppState()
);
vi.mock('$app/navigation', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation()
);
vi.mock('$app/env', () => ({ browser: true, dev: true }));
vi.mock('#lib/stores/auth.ts', async (importOriginal) => {
	const actual = await importOriginal<typeof import('#lib/stores/auth.ts')>();
	return { ...actual, checkAuth: vi.fn(async () => actual.currentUser) };
});
vi.mock('#lib/stores/resourceSync.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/stores/resourceSync.ts')>()),
	startLibraryResourceSync: vi.fn(),
	stopLibraryResourceSync: vi.fn()
}));

import Layout from './+layout.svelte';

const page = createRawSnippet(() => ({ render: () => '<main></main>' }));
let mounted: ReturnType<typeof mount> | undefined;

beforeEach(() => {
	vi.stubGlobal(
		'matchMedia',
		vi.fn(() => ({
			matches: false,
			addEventListener: vi.fn(),
			removeEventListener: vi.fn()
		}))
	);
	vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
	toasts.set([]);
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	resetAuthForTests();
	vi.unstubAllGlobals();
});

describe('the toast surface of the signed-in shell', () => {
	it.each(['/settings/users', '/settings/voices', '/library', '/playlists'])(
		'a toast raised on %s shows once, from the one mount',
		async (path) => {
			currentUser.set(makeAuthUser());
			authLoading.set(false);
			fakePage.url = new URL(`https://songmaker.test${path}`);
			const target = document.createElement('div');
			document.body.append(target);
			mounted = mount(Layout, { target, props: { children: page } });
			flushSync();
			reportFakeRouterEnter();

			addToast('Restart requested', 'success');
			await tick();

			expect(target.querySelectorAll('[role="alert"]')).toHaveLength(1);
			expect(target.querySelector('[role="alert"]')?.textContent).toContain('Restart requested');
		}
	);
});
