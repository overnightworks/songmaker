import type { Place } from '#lib/stores/libraryContext.ts';
import type { Key } from '#lib/words/en.ts';

export const PHONE_TABS = [
	{ place: 'home', labelKey: 'places.home', icon: 'home' },
	{ place: 'library', labelKey: 'places.library', icon: 'library' },
	{ place: 'playlists', labelKey: 'places.playlists', icon: 'playlists' }
] as const satisfies readonly { place: Place; labelKey: Key; icon: string }[];
