import { writable } from 'svelte/store';

// Whether an address page (`/album/<slug>`, `/album/<slug>/<song-slug>`) is
// showing its own overlay -- resolving, unknown or unreachable -- instead of
// the standing LibraryWorkspace underneath. The overlay only controls paint
// order (`position: absolute`), not the accessibility tree or the tab order,
// so `inertWhileAddressOverlay` makes what it is attached to `inert` while an
// overlay is up: the workspace in `(library)/+layout.svelte`, and the song's
// controls in the phone app bar, whose dialogs mount inside that inert
// workspace (#1531). A keyboard or screen-reader user must not reach into a
// surface the visible page has already declared invalid (issue #276 review
// fix). Each address page owns writing it -- true whenever its own
// resolution isn't `open`, false once it is, and false again when the page
// itself unmounts (leaving the group, or a genuine reload) -- so the root `/`
// address, which never shows an overlay, never touches it.
export const libraryAddressOverlayActive = writable(false);

// An `{@attach}` that mirrors the store onto the element's `inert` attribute.
// Driven imperatively rather than through a Svelte `inert={...}` attribute
// binding: jsdom (used by the unit suite) has no `inert` IDL property, and
// Svelte's attribute codegen detects that absence and falls back to a plain
// property assignment invisible to `hasAttribute` -- correct in a real
// browser, untestable here. `toggleAttribute` is the same DOM API in both.
export function inertWhileAddressOverlay(element: HTMLElement): () => void {
	return libraryAddressOverlayActive.subscribe((active) => {
		element.toggleAttribute('inert', active);
	});
}
