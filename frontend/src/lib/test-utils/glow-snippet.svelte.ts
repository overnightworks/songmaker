import { createRawSnippet, type Snippet } from 'svelte';

// Runes only compile inside a `.svelte.ts` module; it lives under `lib/` so coverage measures it.

/** A snippet whose `data-style` follows the glow style it is handed, as the live title does. */
export function followingGlowSnippet(): Snippet<[string, string | null]> {
	return createRawSnippet<[string, string | null]>((glowStyle) => ({
		render: () => '<span class="glow">Nachtstrom</span>',
		setup: (element) => {
			$effect(() => {
				(element as HTMLElement).dataset.style = glowStyle();
			});
		}
	}));
}
