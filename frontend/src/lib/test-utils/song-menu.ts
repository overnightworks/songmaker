import type { ComponentProps } from 'svelte';
import { vi } from 'vitest';
import { makeSong } from '#lib/test-utils/factories.ts';
import type SongMenu from '#lib/components/editor/SongMenu.svelte';

/** The phone app bar's song-menu props: everything but the rename it adds itself. */
export function songMenuProps(): Omit<ComponentProps<typeof SongMenu>, 'onrename'> {
	return {
		song: makeSong(),
		saveDisabled: true,
		onsave: vi.fn(),
		onaddto: vi.fn(),
		ondelete: vi.fn(),
		onshare: vi.fn(),
		onunshare: vi.fn()
	};
}
