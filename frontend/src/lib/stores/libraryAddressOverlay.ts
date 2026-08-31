import { writable } from 'svelte/store';

// Whether an address page (`/album/<slug>`, `/album/<slug>/<song-slug>`) is
// showing its own overlay -- resolving, unknown or unreachable -- instead of
// the standing LibraryWorkspace underneath. The overlay only controls paint
// order (`position: absolute`), not the accessibility tree or the tab order,
// so `(library)/+layout.svelte` reads this to make the workspace `inert`
// while an overlay is up: a keyboard or screen-reader user must not reach
// into a workspace surface the visible page has already declared invalid
// (issue #276 review fix). Each address page owns writing it -- true
// whenever its own resolution isn't `open`, false once it is, and false
// again when the page itself unmounts (leaving the group, or a genuine
// reload) -- so the root `/` address, which never shows an overlay, never
// touches it.
export const libraryAddressOverlayActive = writable(false);
