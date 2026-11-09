export const NOW_PLAYING_LABEL = 'Now Playing';

// The phone's mini player opens Now Playing from its cover and title. The
// name starts with the visible title so a voice command naming what is on
// screen reaches it (WCAG 2.5.3), then says what the tap opens.
export function openNowPlayingLabel(songTitle: string): string {
	return `${songTitle} — open ${NOW_PLAYING_LABEL}`;
}
// Swiping the mini player up opens Now Playing once the finger has risen
// this far, and further up than sideways; anything less is a tap or a slip.
export const NOW_PLAYING_SWIPE_RISE_PX = 40;
// Beside play's exact centre line a phone narrower than 360px leaves the
// mini player's left side too little room for cover and title, so the cover
// goes and the title takes the whole side. The query stays on max-width, like
// every other breakpoint, because iOS Safari before 16.4 ignores range syntax;
// the fraction also drops the cover on a sub-pixel viewport just under 360px.
const MINI_PLAYER_WITHOUT_COVER_MAX_VIEWPORT_PX = 359.98;
export const MINI_PLAYER_WITHOUT_COVER_MEDIA = `(max-width: ${MINI_PLAYER_WITHOUT_COVER_MAX_VIEWPORT_PX}px)`;

// While the offline strip is not showing, a load that could not reach the
// server runs again on this bounded backoff before its surface names the
// failure with a Retry (connectivity.ts reloadWhileUnreachable).
export const UNREACHABLE_RELOAD_DELAYS_MS: readonly number[] = [2_000, 5_000, 15_000];
export const SONG_PREVIOUS_LABEL = 'Previous song';
export const SONG_NEXT_LABEL = 'Next song';
