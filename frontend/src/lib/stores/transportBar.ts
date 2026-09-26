import { derived } from 'svelte/store';
import { nowPlayingSurface } from '$lib/stores/player';
import { typingOnPhone } from '$lib/stores/ui';

// The app's transport bar gives way to the full Now Playing surface, which
// carries the only transport, and to the on-screen keyboard; the bar and the
// room the shell reserves for it both read this one fact.
export const transportBarHidden = derived(
	[nowPlayingSurface, typingOnPhone],
	([surface, typing]) => surface === 'full' || typing
);
