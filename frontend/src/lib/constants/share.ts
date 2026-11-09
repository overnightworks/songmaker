// Copy for the public `/shared/*` NowPlayingFrame mount — its own strings so
// they never drift with the logged-in app's NowPlaying copy in
// constants/now-playing.ts and constants/song.ts (one owner per label).

export const SHARE_NOW_PLAYING_NO_LYRICS = 'No lyrics';
export const SHARE_NO_AUDIO_NOTICE = 'No audio available yet.';

export const SHARE_BACK_TO_PLAYER_LABEL = 'Back to the player';
export const SHARE_SONGS_HEADING = 'Songs';
const SHARE_ALBUM_KIND_LABEL = 'Album';
const SHARE_SEPARATOR = ' · ';

export function shareAlbumSubtitle(artist: string): string {
	return [artist, SHARE_ALBUM_KIND_LABEL].filter(Boolean).join(SHARE_SEPARATOR);
}

export function shareNowPlayingLine(songTitle: string, position: number, total: number): string {
	return `Now playing${SHARE_SEPARATOR}${songTitle}${SHARE_SEPARATOR}${position} of ${total}`;
}

export function sharePlaylistSubtitle(count: number): string {
	return `Playlist${SHARE_SEPARATOR}${count} song${count === 1 ? '' : 's'}`;
}

// The share succeeded server-side even when the follow-up clipboard write
// throws (no permission, no focus, etc.) — that toast must never read as a
// share failure, since the link exists and only the copy step didn't.
export const SHARE_BUTTON_COPY_FAILED_TOAST =
	'Shared — copy the link manually, clipboard write failed';
export const SHARE_BUTTON_COPIED_TOAST = 'Link copied to clipboard';
export const SHARE_BUTTON_UNSHARED_TOAST = 'Sharing disabled';
export const SHARE_BUTTON_FAILED_TOAST = 'Share failed';

export const SHARE_LINK_COPIED_TOAST = 'Link copied';
export const SHARE_LINK_COPY_FAILED_TOAST = 'Copy failed';
