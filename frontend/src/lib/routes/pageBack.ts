import type { AlbumItem, PlaylistItem, SongItem } from '#lib/api/types.ts';
import { HOME_PAGE_LABEL, RAIL_SETTINGS_LABEL } from '#lib/constants.ts';
import {
	albumRoutePath,
	HOME_ROUTE_PATH,
	isPlaylistRoutePath,
	LIBRARY_ROUTE_PATH,
	libraryRouteShape,
	playlistRoutePath,
	PLAYLISTS_ROUTE_PATH,
	songAlbumRoutePath,
	songRoutePath
} from '#lib/routes/addresses.ts';
import type { StandingPage } from '#lib/routes/standingAddress.ts';
import { visibleRailSearchPages } from '#lib/stores/railSearch.ts';

const LIBRARY_HREF = LIBRARY_ROUTE_PATH;
const PLAYLISTS_HREF = PLAYLISTS_ROUTE_PATH;
export const SETTINGS_HREF = '/settings';
// Home and the lists the app opens on, which carry the brand and the account
// circle instead of ‹ wherever they were opened from.
const PLACE_LISTS: ReadonlySet<string> = new Set([HOME_ROUTE_PATH, LIBRARY_HREF, PLAYLISTS_HREF]);
const ALBUM_NAME = 'Album';
const PLAYLIST_NAME = 'Playlist';
const SONG_NAME = 'Song';
const PREVIOUS_PAGE_NAME = 'Previous page';

export function backLabel(pageName: string): string {
	return `Back to ${pageName}`;
}

interface LibraryTitles {
	readonly albums: readonly AlbumItem[];
	readonly playlists: readonly PlaylistItem[];
	readonly songs: readonly SongItem[];
}

// The list a page belongs to, which its ‹ opens when no page of the tab's
// own lies below it (#1354 rule 25): a Settings section belongs to the
// Settings list, a playlist to the Playlists page, every other page to the
// Library.
export function listOfPage(
	pathname: string
): typeof LIBRARY_ROUTE_PATH | typeof PLAYLISTS_ROUTE_PATH | typeof SETTINGS_HREF {
	if (pathname.startsWith(`${SETTINGS_HREF}/`)) return SETTINGS_HREF;
	return isPlaylistRoutePath(pathname) ? PLAYLISTS_HREF : LIBRARY_HREF;
}

// What ‹ calls the page it goes back to: an app page by the name the app
// gives it, an album, playlist or song by its title, or by its kind while
// the library has not loaded it.
function pageName(pathname: string, titles: LibraryTitles): string {
	if (pathname === HOME_ROUTE_PATH) return HOME_PAGE_LABEL;
	if (pathname === SETTINGS_HREF) return RAIL_SETTINGS_LABEL;
	const appPage = visibleRailSearchPages(true).find((page) => page.href === pathname);
	if (appPage) return appPage.label;
	switch (libraryRouteShape(pathname)) {
		case 'album':
			return (
				titles.albums.find((album) => albumRoutePath(album.id) === pathname)?.title ?? ALBUM_NAME
			);
		case 'playlist':
			return (
				titles.playlists.find((playlist) => playlistRoutePath(playlist.slug) === pathname)?.title ??
				PLAYLIST_NAME
			);
		case 'album-song':
		case 'album-song-take':
			return titles.songs.find((song) => isSongAddress(pathname, song))?.title ?? SONG_NAME;
		default:
			return PREVIOUS_PAGE_NAME;
	}
}

function isSongAddress(pathname: string, song: SongItem): boolean {
	const songPath = songRoutePath(song.album_id, song.slug);
	return pathname === songPath || pathname.startsWith(`${songPath}/`);
}
interface PageBackContext extends StandingPage {
	readonly shell: 'phone' | 'desktop';
}

export function pageBackShown({ pathname, below, shell }: PageBackContext): boolean {
	return shell === 'desktop' ? below !== null : !PLACE_LISTS.has(pathname);
}

export function backTargetName(
	context: PageBackContext & { readonly titles: LibraryTitles }
): string {
	const { pathname, below, titles } = context;
	const target =
		below !== null
			? new URL(below).pathname
			: (songAlbumRoutePath(pathname) ?? listOfPage(pathname));
	return pageName(target, titles);
}
