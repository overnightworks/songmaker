import { HOME_PAGE_LABEL, LIBRARY_PAGE_LABEL, PLAYLISTS_PAGE_LABEL } from '#lib/constants.ts';
import type { Place } from '#lib/stores/libraryContext.ts';

export const PHONE_TABS = [
	{ place: 'home', label: HOME_PAGE_LABEL, icon: 'home' },
	{ place: 'library', label: LIBRARY_PAGE_LABEL, icon: 'library' },
	{ place: 'playlists', label: PLAYLISTS_PAGE_LABEL, icon: 'playlists' }
] as const satisfies readonly { place: Place; label: string; icon: string }[];

export const PHONE_TABS_NAV_LABEL = 'Places';
