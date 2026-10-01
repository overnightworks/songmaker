// Global Escape (issue #1182): close the topmost open layer -- the one Back
// closes too, through stores/navigation's `closeTopLayer`, which the layout
// hands in -- and only with nothing open move one level up (song -> collection
// interior, collection -> the wall). Mounted once in +layout.svelte. A focus trap asks the same stack and claims
// the key (utils/focus-trap.ts), as does a component with an Escape of its own
// that is not a layer (clearing the rail search, cancelling a title edit):
// both prevent the default, which this yields to. A text field's Escape still
// closes the layer it sits in, but never leaves the page.
export function isEditableElement(target: EventTarget | null): boolean {
	if (!(target instanceof HTMLElement)) return false;
	if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) return true;
	return target.contentEditable === 'true';
}

interface EscapeAnswers {
	closeTopLayer: () => boolean;
	levelUp: () => void;
}

export function handleGlobalEscape(
	event: Pick<KeyboardEvent, 'key' | 'target' | 'defaultPrevented' | 'preventDefault'>,
	{ closeTopLayer, levelUp }: EscapeAnswers
): void {
	if (event.key !== 'Escape' || event.defaultPrevented) return;
	if (closeTopLayer()) {
		event.preventDefault();
		return;
	}
	if (!isEditableElement(event.target)) levelUp();
}

type EscapeLevelUpTarget = 'now-playing' | 'collection' | 'wall' | null;

// Pure decision: what one level up means for the current state. The
// +layout.svelte handler reads the live stores and calls the matching action
// (escapeNowPlaying / backToCollection / openLibraryWall).
//
// Now Playing sits above the navigation levels because it is the surface the
// listener opened last. A full surface the listener chose is a layer and has
// closed before any level up; what reaches this decision is the docked panel,
// deliberately not a layer, or a full surface the window narrowed it into,
// which holds no history entry (stores/navigation).
export function escapeLevelUpTarget(
	hasOpenNowPlaying: boolean,
	hasOpenSong: boolean,
	hasOpenCollection: boolean
): EscapeLevelUpTarget {
	if (hasOpenNowPlaying) return 'now-playing';
	if (hasOpenSong) return 'collection';
	if (hasOpenCollection) return 'wall';
	return null;
}
