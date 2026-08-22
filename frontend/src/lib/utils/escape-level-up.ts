// Global Escape = one level up (song -> collection interior, collection -> the
// wall). Mounted once in +layout.svelte. Yields whenever a dialog, drawer, or
// menu is open, or while an editable element has focus, so it never fights a
// component that already owns Escape for its own overlay. The contract: any
// component that owns an overlay (dialog, drawer, dropdown menu, popover)
// marks its open root `aria-modal="true"` and closes itself on Escape — that
// marker is what this module checks for; it does not track overlays itself.
// A popover whose ARIA role does not permit `aria-modal` (e.g. `role="menu"`
// for the take overflow menu) marks itself `data-escape-overlay="true"`
// instead, for the same purpose.
export function isEditableElement(target: EventTarget | null): boolean {
	if (!(target instanceof HTMLElement)) return false;
	if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) return true;
	return target.contentEditable === 'true';
}

export function hasOpenOverlay(root: Document | null): boolean {
	if (!root) return false;
	return root.querySelector('[aria-modal="true"], [data-escape-overlay="true"]') !== null;
}

export function shouldHandleGlobalEscape(
	event: Pick<KeyboardEvent, 'key' | 'target'>,
	root: Document | null
): boolean {
	if (event.key !== 'Escape') return false;
	if (isEditableElement(event.target)) return false;
	if (hasOpenOverlay(root)) return false;
	return true;
}

export type EscapeLevelUpTarget = 'collection' | 'wall' | null;

// Pure decision: what one level up means for the current navigation state.
// The +layout.svelte handler reads the live stores and calls the matching
// navigation action (backToCollection / openLibraryWall).
export function escapeLevelUpTarget(
	hasOpenSong: boolean,
	hasOpenCollection: boolean
): EscapeLevelUpTarget {
	if (hasOpenSong) return 'collection';
	if (hasOpenCollection) return 'wall';
	return null;
}
