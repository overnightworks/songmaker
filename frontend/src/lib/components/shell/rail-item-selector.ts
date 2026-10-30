import { tick } from 'svelte';
import type { Action } from 'svelte/action';
import { REDUCED_MOTION_MEDIA } from '#lib/constants.ts';

export const RAIL_ALBUM_ITEM_CLASS = 'album-label';
export const RAIL_PLAYLIST_ITEM_CLASS = 'playlist-label';

export const RAIL_ITEM_SELECTOR = `.${RAIL_ALBUM_ITEM_CLASS}, .${RAIL_PLAYLIST_ITEM_CLASS}`;

function animationsAround(row: HTMLElement): Animation[] {
	const animations: Animation[] = [];
	for (let ancestor = row.parentElement; ancestor; ancestor = ancestor.parentElement) {
		animations.push(...ancestor.getAnimations());
	}
	return animations;
}

function revealScrollBehavior(): ScrollBehavior {
	return window.matchMedia(REDUCED_MOTION_MEDIA).matches ? 'auto' : 'smooth';
}

// The open row scrolls into the rail's view the moment it becomes shown -- a
// navigation, Back or Forward, its group opening, the tree returning once a
// search is cleared, or a reload listing it -- and never again while it
// merely stays shown, so a viewer who scrolls the rail elsewhere is not pulled
// back. It waits until the group around it has finished opening: any
// earlier, the rail cannot reach the row yet.
export const revealOpenRailItem: Action<HTMLElement, boolean> = (row, shown) => {
	let latestRequest = 0;

	async function reveal(): Promise<void> {
		if (typeof row.scrollIntoView !== 'function') return;
		latestRequest += 1;
		const request = latestRequest;
		await tick();
		await Promise.allSettled(animationsAround(row).map((animation) => animation.finished));
		if (request !== latestRequest) return;
		row.scrollIntoView({ block: 'nearest', behavior: revealScrollBehavior() });
	}

	function cancelReveal(): void {
		latestRequest += 1;
	}

	if (shown) void reveal();
	return {
		update(nowShown) {
			if (nowShown) void reveal();
			else cancelReveal();
		},
		destroy: cancelReveal
	};
};
