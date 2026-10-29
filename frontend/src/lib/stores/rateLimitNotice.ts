import { get } from 'svelte/store';

import { RATE_LIMITED_TOAST_MESSAGE } from '#lib/constants.ts';
import { addToast, toasts } from '#lib/stores/toast.ts';

// A path whose own 429 is already visible some other way, so the generic
// toast would only repeat it.
//   - '/api/auth/me': `stores/auth.ts`'s `checkAuth()` turns a 429 into the
//     full-page session-check retry banner.
//   - '/api/albums/<id>/cover-suggestions': `AlbumCoverEditor.svelte` shows
//     every refusal there itself -- the spent daily limit under the cover,
//     any other as its failure or error toast; nothing retries it, so
//     "it will continue in a moment" would be untrue there.
const RATE_LIMIT_TOAST_EXEMPT_PATHS: readonly RegExp[] = [
	/^\/api\/auth\/me$/,
	/^\/api\/albums\/[^/]+\/cover-suggestions$/
];

/**
 * Never more than one throttle toast on screen at once, not one per
 * rejected request: a 429 burst calls this many times in a row, but a
 * toast already showing the same message is left alone instead of being
 * duplicated (issue #257). The toast auto-dismisses after 5s (`addToast`'s
 * 'info' type), so a burst that outlasts that raises a fresh toast every
 * ~5s for as long as it's still being throttled -- which reads as "still
 * throttled", not as a bug.
 */
export function notifyRateLimited(path: string): void {
	if (RATE_LIMIT_TOAST_EXEMPT_PATHS.some((exempt) => exempt.test(path))) return;
	const alreadyShown = get(toasts).some((toast) => toast.message === RATE_LIMITED_TOAST_MESSAGE);
	if (alreadyShown) return;
	addToast(RATE_LIMITED_TOAST_MESSAGE, 'info');
}
