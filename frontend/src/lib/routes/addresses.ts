const ALBUM_ROUTE_PREFIX = '/album/';
const TAKE_ROUTE_SEGMENT = '/take/';
const PLAYLIST_ROUTE_PREFIX = '/playlist/';
export type ShareKind = 'album' | 'song' | 'playlist' | 'gen';
const SHARE_PAGE_PREFIX: Readonly<Record<ShareKind, string>> = {
	album: '/share/',
	song: '/share/song/',
	playlist: '/share/playlist/',
	gen: '/share/gen/'
};
export const HOME_ROUTE_PATH = '/';
export const LIBRARY_ROUTE_PATH = '/library';
export const PLAYLISTS_ROUTE_PATH = '/playlists';
export const LIBRARY_ROUTE_ID = '/(library)/library';
export const PLAYLISTS_ROUTE_ID = '/(library)/playlists';

export function albumRoutePath(albumId: string): string {
	return `${ALBUM_ROUTE_PREFIX}${encodeURIComponent(albumId)}`;
}

export function songRoutePath(albumId: string, songSlug: string): string {
	return `${albumRoutePath(albumId)}/${encodeURIComponent(songSlug)}`;
}

export function takeRoutePath(albumId: string, songSlug: string, takeNumber: number): string {
	return `${songRoutePath(albumId, songSlug)}${TAKE_ROUTE_SEGMENT}${takeNumber}`;
}

export function playlistRoutePath(slug: string): string {
	return `${PLAYLIST_ROUTE_PREFIX}${encodeURIComponent(slug)}`;
}

export function sharePagePath(kind: ShareKind, slug: string): string {
	return `${SHARE_PAGE_PREFIX[kind]}${encodeURIComponent(slug)}`;
}

function isAlbumRoutePath(pathname: string): boolean {
	return pathname.startsWith(ALBUM_ROUTE_PREFIX) && pathname.length > ALBUM_ROUTE_PREFIX.length;
}

export function isSongRoutePath(pathname: string): boolean {
	if (!isAlbumRoutePath(pathname)) return false;
	const rest = pathname.slice(ALBUM_ROUTE_PREFIX.length);
	const slashIndex = rest.indexOf('/');
	return slashIndex !== -1 && rest.length > slashIndex + 1;
}

export function songAlbumRoutePath(pathname: string): string | null {
	if (!isSongRoutePath(pathname)) return null;
	return pathname.slice(0, pathname.indexOf('/', ALBUM_ROUTE_PREFIX.length));
}

function isTakeRoutePath(pathname: string): boolean {
	if (!isSongRoutePath(pathname)) return false;
	const takeIndex = pathname.indexOf(TAKE_ROUTE_SEGMENT);
	return takeIndex !== -1 && pathname.length > takeIndex + TAKE_ROUTE_SEGMENT.length;
}

export function isPlaylistRoutePath(pathname: string): boolean {
	return (
		pathname.startsWith(PLAYLIST_ROUTE_PREFIX) && pathname.length > PLAYLIST_ROUTE_PREFIX.length
	);
}

type LibraryRouteShape =
	| 'home'
	| 'library'
	| 'album'
	| 'album-song'
	| 'album-song-take'
	| 'playlists'
	| 'playlist'
	| 'external';

export function libraryRouteShape(pathname: string): LibraryRouteShape {
	if (pathname === PLAYLISTS_ROUTE_PATH) return 'playlists';
	if (isPlaylistRoutePath(pathname)) return 'playlist';
	if (isAlbumRoutePath(pathname)) {
		if (!isSongRoutePath(pathname)) return 'album';
		return isTakeRoutePath(pathname) ? 'album-song-take' : 'album-song';
	}
	if (pathname === HOME_ROUTE_PATH) return 'home';
	return pathname === LIBRARY_ROUTE_PATH ? 'library' : 'external';
}

export function standsOnHomePage(pathname: string): boolean {
	return libraryRouteShape(pathname) === 'home';
}

export function standsOnLibraryPage(pathname: string): boolean {
	return libraryRouteShape(pathname) === 'library';
}

export function standsOnPlaylistsPage(pathname: string): boolean {
	return libraryRouteShape(pathname) === 'playlists';
}

export function readLegacySongQuery(searchParams: Pick<URLSearchParams, 'get'>): {
	songId: string | null;
	generationId: string | null;
} {
	return {
		songId: searchParams.get('song'),
		generationId: searchParams.get('gen')
	};
}

export function legacySongRoutePath(songId: string, generationId: string | null): string {
	return generationId
		? `${HOME_ROUTE_PATH}?song=${songId}&gen=${generationId}`
		: `${HOME_ROUTE_PATH}?song=${songId}`;
}

export function pendingTakeRoutePath(songPath: string, generationId: string): string {
	return `${songPath}?gen=${generationId}`;
}
