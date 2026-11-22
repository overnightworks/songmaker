import type { ComponentProps } from 'svelte';
import { vi } from 'vitest';
import type SongMenu from '#lib/components/editor/SongMenu.svelte';

/** The phone app bar's song-menu props: everything but the title and rename it adds itself. */
export function songMenuProps(): Omit<ComponentProps<typeof SongMenu>, 'title' | 'onrename'> {
	return {
		saveDisabled: true,
		onsave: vi.fn(),
		onaddto: vi.fn(),
		ondelete: vi.fn(),
		isShared: false,
		shareSlug: null,
		onshare: vi.fn(),
		onunshare: vi.fn()
	};
}
