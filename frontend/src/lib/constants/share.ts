// Copy for the public `/shared/*` NowPlayingFrame mount — its own strings so
// they never drift with the logged-in app's NowPlaying copy in
// constants/now-playing.ts and constants.ts (one owner per label).

export const SHARE_NOW_PLAYING_SHEET_LABEL = 'Now playing';
export const SHARE_NOW_PLAYING_NO_LYRICS = 'No lyrics';
export const SHARE_NO_AUDIO_NOTICE = 'No audio available yet.';

export const SHARE_SONGS_HEADING = 'Songs';
const SHARE_ALBUM_KIND_LABEL = 'Album';
const SHARE_SEPARATOR = ' · ';

export function shareAlbumSubtitle(artist: string): string {
	return [artist, SHARE_ALBUM_KIND_LABEL].filter(Boolean).join(SHARE_SEPARATOR);
}

export function shareNowPlayingLine(songTitle: string, position: number, total: number): string {
	return `Now playing${SHARE_SEPARATOR}${songTitle}${SHARE_SEPARATOR}${position} of ${total}`;
}
