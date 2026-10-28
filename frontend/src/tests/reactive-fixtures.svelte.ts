import { createRawSnippet, type Snippet } from 'svelte';

// Runes only compile inside a `.svelte.ts` module, so a test that needs real
// reactive state — a `$state` proxy, or props a mounted component follows —
// asks for it here rather than describing it in a plain `.test.ts`.

/**
 * The shape reactive state hands on: a deep proxy, which is exactly what
 * refuses to be structured-cloned into a worker.
 */
export function stateProxy<T extends object>(value: T): T {
	const proxied = $state(value);
	return proxied;
}

/** Props a mounted component re-reads when the test changes one of them. */
export function reactiveProps<T extends object>(props: T): T {
	const reactive = $state(props);
	return reactive;
}

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
