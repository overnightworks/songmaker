import { expect, it, vi } from 'vitest';
import type { ShareKind } from '#lib/routes/addresses.ts';
import { get } from 'svelte/store';
import { ApiError } from '#lib/api/fetch.ts';
import { toasts } from '#lib/stores/toast.ts';
import { createShareToggle } from './shareToggle.svelte';

it.each<{ kind: ShareKind; address: string }>([
	{ kind: 'album', address: '/share/abc' },
	{ kind: 'song', address: '/share/song/abc' },
	{ kind: 'playlist', address: '/share/playlist/abc' },
	{ kind: 'gen', address: '/share/gen/abc' }
])('tooltip names the real share address of a shared $kind', ({ kind, address }) => {
	const toggle = createShareToggle(() => ({
		kind,
		isShared: true,
		shareSlug: 'abc',
		onshare: vi.fn(),
		onunshare: vi.fn()
	}));

	expect(toggle.sharedTooltip).toBe(`Shared: ${address}`);
});

it('toasts the server detail when sharing is refused', async () => {
	const toggle = createShareToggle(() => ({
		kind: 'gen',
		isShared: false,
		shareSlug: null,
		onshare: vi.fn().mockRejectedValue(new ApiError(409, 'Restore this take first.', '/share')),
		onunshare: vi.fn()
	}));

	await toggle.toggle();

	expect(get(toasts).map((toast) => toast.message)).toEqual(['Restore this take first.']);
});
