const ALBUM_ROUTE_PREFIX = '/album/';
const TAKE_ROUTE_SEGMENT = '/take/';
const PLAYLIST_ROUTE_PREFIX = '/playlist/';

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

export function isAlbumRoutePath(pathname: string): boolean {
	return pathname.startsWith(ALBUM_ROUTE_PREFIX) && pathname.length > ALBUM_ROUTE_PREFIX.length;
}

export function isSongRoutePath(pathname: string): boolean {
	if (!isAlbumRoutePath(pathname)) return false;
	const rest = pathname.slice(ALBUM_ROUTE_PREFIX.length);
	const slashIndex = rest.indexOf('/');
	return slashIndex !== -1 && rest.length > slashIndex + 1;
}

export function isTakeRoutePath(pathname: string): boolean {
	if (!isSongRoutePath(pathname)) return false;
	const takeIndex = pathname.indexOf(TAKE_ROUTE_SEGMENT);
	return takeIndex !== -1 && pathname.length > takeIndex + TAKE_ROUTE_SEGMENT.length;
}

export function isPlaylistRoutePath(pathname: string): boolean {
	return (
		pathname.startsWith(PLAYLIST_ROUTE_PREFIX) && pathname.length > PLAYLIST_ROUTE_PREFIX.length
	);
}

export type LibraryRouteShape =
	'root' | 'album' | 'album-song' | 'album-song-take' | 'playlist' | 'external';

export function libraryRouteShape(pathname: string): LibraryRouteShape {
	if (isPlaylistRoutePath(pathname)) return 'playlist';
	if (isAlbumRoutePath(pathname)) {
		if (!isSongRoutePath(pathname)) return 'album';
		return isTakeRoutePath(pathname) ? 'album-song-take' : 'album-song';
	}
	return pathname === '/' ? 'root' : 'external';
}

export function readLegacySongQuery(searchParams: URLSearchParams): {
	songId: string | null;
	generationId: string | null;
} {
	return {
		songId: searchParams.get('song'),
		generationId: searchParams.get('gen')
	};
}

export function legacySongRoutePath(songId: string, generationId: string | null): string {
	return generationId ? `/?song=${songId}&gen=${generationId}` : `/?song=${songId}`;
}

export function pendingTakeRoutePath(songPath: string, generationId: string): string {
	return `${songPath}?gen=${generationId}`;
}
