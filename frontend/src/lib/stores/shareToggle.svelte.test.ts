import { expect, it, vi } from 'vitest';
import type { ShareKind } from '#lib/routes/addresses.ts';
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
