export const REDUCED_MOTION_MEDIA = '(prefers-reduced-motion: reduce)';
export const COMPACT_LAYOUT_MAX_PX = 768;
export const COMPACT_LAYOUT_MEDIA = `(max-width: ${COMPACT_LAYOUT_MAX_PX}px), (any-pointer: coarse)`;
// A narrow desktop window is compact but still has a mouse — touch-only copy
// ("Tap play") asks this instead of the compact query.
export const COARSE_POINTER_MEDIA = '(any-pointer: coarse)';
export const LIBRARY_NARROW_MEDIA = `(max-width: ${COMPACT_LAYOUT_MAX_PX}px)`;

// Beside play's exact centre line a phone narrower than 360px leaves the
// mini player's left side too little room for cover and title, so the cover
// goes and the title takes the whole side. The query stays on max-width, like
// every other breakpoint, because iOS Safari before 16.4 ignores range syntax;
// the fraction also drops the cover on a sub-pixel viewport just under 360px.
const MINI_PLAYER_WITHOUT_COVER_MAX_VIEWPORT_PX = 359.98;
export const MINI_PLAYER_WITHOUT_COVER_MEDIA = `(max-width: ${MINI_PLAYER_WITHOUT_COVER_MAX_VIEWPORT_PX}px)`;
