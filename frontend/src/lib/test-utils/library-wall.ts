import { mount, tick, unmount } from 'svelte';
import { vi } from 'vitest';

import LibraryWall from '#lib/components/LibraryWall.svelte';
import { LIBRARY_WALL_ORDER_KEYS, type LibraryWallOrder } from '#lib/constants/library.ts';
import { albumList } from '#lib/stores/libraryData.ts';
import { playlistList } from '#lib/stores/playlists.ts';
import { makeAlbum as album, makePlaylist as playlist } from '#lib/test-utils/factories.ts';
import { words } from '#lib/words/en.ts';

const mounted: Array<ReturnType<typeof mount>> = [];

export const songs = words['libraryWall.songCount'];

export const orderFace = (order: LibraryWallOrder) => words[LIBRARY_WALL_ORDER_KEYS[order]];

export const headLabel = (page: 'places.library' | 'places.playlists', count: number) =>
	words['libraryWall.heading']({ page: words[page], count });

export async function unmountAll(): Promise<void> {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
}

export function albumPage(items: ReturnType<typeof album>[], hasMore: boolean) {
	return { items, total: items.length, offset: 0, limit: 50, has_more: hasMore };
}

export async function render(kind: 'library' | 'playlists' = 'library'): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(LibraryWall, { target, props: { kind } }));
	await tick();
	return target;
}

export function tileTitles(root: ParentNode): string[] {
	return [...root.querySelectorAll('.wall-tile .tile-title')].map(
		(title) => title.textContent ?? ''
	);
}

export function tileLines(root: ParentNode): string[] {
	return [...root.querySelectorAll('.wall-tile .tile-subtitle')].map(
		(line) => line.textContent ?? ''
	);
}

export function orderChoices(root: ParentNode): HTMLButtonElement[] {
	const group = root.querySelector('.wall-titlebar [role="group"]');
	return [...(group?.querySelectorAll('button') ?? [])];
}

export function choiceLabel(choice: HTMLButtonElement): string {
	return choice.textContent?.trim() ?? '';
}

export function orderButton(root: ParentNode, order: LibraryWallOrder): HTMLButtonElement {
	const button = orderChoices(root).find((choice) => choiceLabel(choice) === orderFace(order));
	if (!button) throw new Error(`no ${order} order`);
	return button;
}

export function pressedOrder(root: ParentNode): string[] {
	return orderChoices(root)
		.filter((choice) => choice.getAttribute('aria-pressed') === 'true')
		.map(choiceLabel);
}

export function place(type: 'album' | 'playlist', id: string, title: string, playedAt: string) {
	return {
		type,
		id,
		title,
		cover: null,
		album_covers: [],
		song_id: null,
		song_title: null,
		song_number: null,
		played_at: playedAt
	};
}

export function seedWall(): void {
	albumList.set([
		album({ id: 'a-sonne', title: 'Sonnenlauf', song_count: 7 }),
		album({ id: 'a-fuer', title: 'Sonne für Andrea', song_count: 5 }),
		album({ id: 'a-nacht', title: 'nachtstrom', song_count: 1 })
	]);
	playlistList.set([
		playlist({ id: 'p-night', title: 'Night drive', entry_count: 14, share_slug: null })
	]);
}

// Stubs every media query as matching the phone width; the returned function
// turns the viewport to the phone width or away from it and tells the listeners.
export function phoneViewport(): (phone: boolean) => void {
	let matches = true;
	const listeners = new Set<() => void>();
	vi.stubGlobal('matchMedia', () => ({
		get matches() {
			return matches;
		},
		addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
		removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener)
	}));
	return (phone) => {
		matches = phone;
		for (const listener of listeners) listener();
	};
}
