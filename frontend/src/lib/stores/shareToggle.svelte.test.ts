import { beforeEach, expect, it, vi } from 'vitest';
import type { ShareKind } from '#lib/routes/addresses.ts';
import { get } from 'svelte/store';
import { ApiError } from '#lib/api/fetch.ts';
import { toasts } from '#lib/stores/toast.ts';
import { words } from '#lib/words/en.ts';
import { createShareToggle } from './shareToggle.svelte';

const archivedRefusal = { key: 'takeRefusal.archived', values: {} };

beforeEach(() => {
	toasts.set([]);
});

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

it('toasts the page words of the key a refusal names when sharing is refused', async () => {
	const toggle = createShareToggle(() => ({
		kind: 'gen',
		isShared: false,
		shareSlug: null,
		onshare: vi
			.fn()
			.mockRejectedValue(
				new ApiError(409, 'Sentence of the server', '/share', null, '', null, null, archivedRefusal)
			),
		onunshare: vi.fn()
	}));

	await toggle.toggle();

	expect(get(toasts).map((toast) => toast.message)).toEqual([words['takeRefusal.archived']]);
});
