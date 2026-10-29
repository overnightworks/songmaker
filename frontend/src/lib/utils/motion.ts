import { REDUCED_MOTION_MEDIA } from '#lib/constants.ts';

// Smooth or instant is one decision for every scroll the app makes on its
// own: a listener who asked for less motion gets the jump.
export function preferredScrollBehavior(): ScrollBehavior {
	return window.matchMedia(REDUCED_MOTION_MEDIA).matches ? 'auto' : 'smooth';
}
