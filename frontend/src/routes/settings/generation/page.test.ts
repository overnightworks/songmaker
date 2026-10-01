import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { currentUser } from '$lib/stores/auth';

import GenerationSettingsPage from './+page.svelte';

const ADMIN = { id: 'u1', username: 'felix', role: 'admin' as const };
const USER = { id: 'u2', username: 'jane', role: 'user' as const };
const ADMIN_ONLY_DEFAULTS_PATH = '/api/settings/generation-defaults';

const RESPONSES: Record<string, unknown> = {
	'/api/settings/presets': [],
	'/api/settings/generation-builtins': {},
	'/api/settings/models': [],
	'/api/settings/default-config': { config: null },
	[ADMIN_ONLY_DEFAULTS_PATH]: {}
};

let mounted: ReturnType<typeof mount> | undefined;

interface OpenedPage {
	target: HTMLElement;
	requested: string[];
}

function stubApi(failing: ReadonlySet<string>): string[] {
	const requested: string[] = [];
	vi.stubGlobal(
		'fetch',
		vi.fn(async (path: string) => {
			requested.push(path);
			if (failing.has(path)) return new Response('{}', { status: 500 });
			return new Response(JSON.stringify(RESPONSES[path]), { status: 200 });
		})
	);
	return requested;
}

async function openPageAs(
	user: typeof ADMIN | typeof USER,
	failing: ReadonlySet<string> = new Set()
): Promise<OpenedPage> {
	currentUser.set(user);
	const requested = stubApi(failing);
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(GenerationSettingsPage, { target });
	await tick();
	await vi.waitFor(() => expect(requested).toContain('/api/settings/default-config'));
	return { target, requested };
}

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	currentUser.set(null);
	vi.unstubAllGlobals();
});

describe('generation settings', () => {
	it('asks a non-admin nothing an administrator alone may read', async () => {
		const { requested } = await openPageAs(USER);

		expect(requested).not.toContain(ADMIN_ONLY_DEFAULTS_PATH);
	});

	it('reads the global generation defaults for an administrator', async () => {
		const { requested } = await openPageAs(ADMIN);

		expect(requested).toContain(ADMIN_ONLY_DEFAULTS_PATH);
	});

	it('tells an administrator when the global generation defaults cannot be read', async () => {
		const { target } = await openPageAs(ADMIN, new Set([ADMIN_ONLY_DEFAULTS_PATH]));

		await vi.waitFor(() =>
			expect(target.querySelector('.error')?.textContent).toBe('Failed to load generation defaults')
		);
	});
});
