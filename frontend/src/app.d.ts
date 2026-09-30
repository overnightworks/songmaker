// See https://svelte.dev/docs/kit/types#app.d.ts
// for information about these interfaces
import type { LibraryHistoryState } from '$lib/stores/libraryContext';

declare global {
	namespace App {
		// interface Error {}
		// interface Locals {}
		// interface PageData {}
		// The library a history entry shows, written by writeLibraryHistory.
		interface PageState {
			library?: LibraryHistoryState;
		}
		// interface Platform {}
	}
}

export {};
