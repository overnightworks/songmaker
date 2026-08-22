import { writable } from 'svelte/store';

// The single owner of "what collection is open". Nothing else may write the
// navigation collection directly — album/playlist selection, history
// hydration, and the derived `selectedPlaylistId` in playlists.ts all read or
// set it through this leaf store. It imports nothing from other stores so any
// module (player, playlists, navigation, libraryContext) can depend on it
// without creating a cycle.
export type OpenCollection = { kind: 'album'; id: string } | { kind: 'playlist'; id: string };

export const openCollection = writable<OpenCollection | null>(null);

export function setOpenCollection(next: OpenCollection | null): void {
	openCollection.set(next);
}

export function resetCollectionForTests(): void {
	openCollection.set(null);
}
