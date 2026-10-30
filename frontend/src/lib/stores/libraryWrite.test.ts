import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import type { LibraryWriteItem } from '#lib/api/types.ts';
import { lostNetwork } from '#lib/test-utils/network.ts';
import { makeAlbum, makeSong } from '#lib/test-utils/factories.ts';
import {
	addAlbumToList,
	addSongsToList,
	albumSongsLoad,
	loadSongsForAlbum,
	removeSongFromList,
	removeSongsForAlbum,
	resetLibraryDataForTests
} from './libraryData';
import {
	ensureLibraryWriteRead,
	libraryWriteItems,
	libraryWriteState,
	libraryWriteLoading,
	outdateLibraryWrite,
	resetLibraryWriteForTests
} from './libraryWrite';

const fetch = vi.fn<typeof globalThis.fetch>();
const row = (id: string, album = 'album'): LibraryWriteItem => ({
	song_id: id,
	song_title: id,
	album_id: album,
	album_title: album,
	work: 'lyrics',
	worked_at: '2026-10-17T12:00:00Z'
});
const answer = (...items: LibraryWriteItem[]) => Response.json({ items });
const ids = () => get(libraryWriteItems).map((item) => item.song_id);
function deferredRead() {
	let resolve!: (value: Response) => void;
	const promise = new Promise<Response>((done) => {
		resolve = done;
	});
	fetch.mockReturnValueOnce(promise);
	return resolve;
}

beforeEach(() => {
	resetLibraryWriteForTests();
	fetch.mockReset();
	vi.stubGlobal('fetch', fetch);
});
afterEach(() => {
	resetLibraryWriteForTests();
	resetLibraryDataForTests();
	vi.unstubAllGlobals();
});

it('1354_rule_14 joins concurrent readers and reuses the server order while fresh', async () => {
	const resolve = deferredRead();
	const first = ensureLibraryWriteRead();
	const second = ensureLibraryWriteRead();
	expect(get(libraryWriteLoading)).toBe(true);
	expect(first).toBe(second);
	resolve(answer(row('b'), row('a')));
	await first;
	await ensureLibraryWriteRead();
	expect(ids()).toEqual(['b', 'a']);
	expect(fetch).toHaveBeenCalledTimes(1);
	expect(get(libraryWriteLoading)).toBe(false);
});

it('1354_rule_18 distinguishes a successful empty answer from unread', async () => {
	expect(get(libraryWriteState)).toBe('unread');
	fetch.mockResolvedValueOnce(answer());
	await ensureLibraryWriteRead();
	expect(get(libraryWriteState)).toBe('ready');
	expect(ids()).toEqual([]);
});

it('1354_rule_19 refreshes after an explicit invalidation', async () => {
	fetch.mockResolvedValueOnce(answer(row('old'))).mockResolvedValueOnce(answer(row('new')));
	await ensureLibraryWriteRead();
	outdateLibraryWrite();
	await ensureLibraryWriteRead();
	expect(ids()).toEqual(['new']);
});

it.each([false, true])(
	'1354_rule_19 retries failure with a previous answer: %s',
	async (loaded) => {
		if (loaded) {
			fetch.mockResolvedValueOnce(answer(row('kept')));
			await ensureLibraryWriteRead();
			outdateLibraryWrite();
		}
		fetch.mockRejectedValueOnce(lostNetwork());
		await ensureLibraryWriteRead();
		expect(ids()).toEqual(loaded ? ['kept'] : []);
		expect(get(libraryWriteState)).toBe(loaded ? 'outdated' : 'failed');
		fetch.mockResolvedValueOnce(answer(row('fresh')));
		await ensureLibraryWriteRead();
		expect(get(libraryWriteState)).toBe('ready');
		expect(ids()).toEqual(['fresh']);
	}
);

it.each([{ removed: ['a'] }, { removed: ['a', 'b'] }, { removed: ['a', 'a'] }])(
	'1354_rule_20 keeps removals $removed out of a read started before deletion and refills',
	async ({ removed }) => {
		const resolve = deferredRead();
		const first = ensureLibraryWriteRead();
		const refill = deferredRead();
		for (const id of removed) removeSongFromList(id);
		resolve(answer(row('a'), row('b'), row('c')));
		await first;
		expect(ids()).toEqual(['a', 'b', 'c'].filter((id) => !removed.includes(id)));
		refill(answer(row('c'), row('d')));
		await ensureLibraryWriteRead();
		expect(ids()).toEqual(['c', 'd']);
		expect(get(libraryWriteState)).toBe('ready');
		await ensureLibraryWriteRead();
		expect(fetch).toHaveBeenCalledTimes(2);
	}
);

it.each(['before deletion', 'between deletion and Undo', 'after Undo'])(
	'1354_rule_20 restores a song with a read %s',
	async (timing) => {
		fetch.mockResolvedValueOnce(answer(row('a')));
		await ensureLibraryWriteRead();
		const resolve = deferredRead();
		if (timing === 'before deletion') {
			outdateLibraryWrite();
			void ensureLibraryWriteRead();
		}
		removeSongFromList('a');
		expect(ids()).toEqual([]);
		const restored = deferredRead();
		if (timing === 'after Undo') {
			resolve(answer());
			await ensureLibraryWriteRead();
		}
		addSongsToList([makeSong({ id: 'a' })]);
		if (timing !== 'after Undo') resolve(answer());
		await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(3));
		restored(answer(row('a')));
		await ensureLibraryWriteRead();
		expect(ids()).toEqual(['a']);
		expect(get(libraryWriteState)).toBe('ready');
		await ensureLibraryWriteRead();
		expect(fetch).toHaveBeenCalledTimes(3);
	}
);

it('1354_rule_20 failed Undo refresh stays outdated and retries on the next entry', async () => {
	fetch.mockResolvedValueOnce(answer(row('a')));
	await ensureLibraryWriteRead();
	const resolve = deferredRead();
	removeSongFromList('a');
	fetch.mockRejectedValueOnce(lostNetwork());
	addSongsToList([makeSong({ id: 'a' })]);
	resolve(answer());
	await vi.waitFor(() => {
		expect(get(libraryWriteState)).toBe('outdated');
		expect(get(libraryWriteLoading)).toBe(false);
	});
	fetch.mockResolvedValueOnce(answer(row('a')));
	await ensureLibraryWriteRead();
	expect(ids()).toEqual(['a']);
});

it('1354_rule_20 restores album membership even when fetching its unloaded songs fails', async () => {
	fetch.mockResolvedValueOnce(answer(row('a')));
	await ensureLibraryWriteRead();
	fetch.mockResolvedValueOnce(answer());
	removeSongsForAlbum('album');
	await ensureLibraryWriteRead();
	expect(ids()).toEqual([]);
	fetch.mockResolvedValueOnce(answer(row('a')));
	addAlbumToList(makeAlbum({ id: 'album' }));
	fetch.mockResolvedValueOnce(Response.json({ detail: 'unavailable' }, { status: 503 }));
	await loadSongsForAlbum('album');
	await ensureLibraryWriteRead();
	expect(get(albumSongsLoad).album).toBe('failed');
	expect(ids()).toEqual(['a']);
});

it.each(['unread', 'ready'] as const)(
	'1354_rule_05 ordinary additions do not invent work or trigger a read while %s',
	async (state) => {
		if (state === 'ready') {
			fetch.mockResolvedValue(answer(row('kept')));
			await ensureLibraryWriteRead();
		}
		addAlbumToList(makeAlbum());
		addSongsToList([makeSong()]);
		expect(ids()).toEqual(state === 'ready' ? ['kept'] : []);
		expect(get(libraryWriteState)).toBe(state);
		expect(fetch).toHaveBeenCalledTimes(state === 'ready' ? 1 : 0);
	}
);

it.each(['song', 'album'] as const)(
	'defect:#1557 leaves unread Write idle after a %s removal',
	async (kind) => {
		if (kind === 'song') removeSongFromList('a');
		else removeSongsForAlbum('album');
		expect(get(libraryWriteState)).toBe('unread');
		expect(fetch).not.toHaveBeenCalled();
		fetch.mockResolvedValueOnce(answer(row('b', 'other')));
		await ensureLibraryWriteRead();
		expect(ids()).toEqual(['b']);
	}
);

it.each([
	{ kind: 'song', ordinaryAddition: false },
	{ kind: 'album', ordinaryAddition: false },
	{ kind: 'album', ordinaryAddition: true }
] as const)(
	'1354_rule_20 accepts a cross-device restore after the read predating $kind deletion lands (ordinary addition: $ordinaryAddition)',
	async ({ kind, ordinaryAddition }) => {
		const resolve = deferredRead();
		const first = ensureLibraryWriteRead();
		const refill = deferredRead();
		if (kind === 'song') removeSongFromList('a');
		else removeSongsForAlbum('album');
		if (ordinaryAddition) addAlbumToList(makeAlbum({ id: 'not-removed-here' }));
		resolve(answer(row('a')));
		await first;
		expect(ids()).toEqual([]);
		refill(answer(row('b', 'other')));
		await ensureLibraryWriteRead();
		expect(ids()).toEqual(['b']);
		fetch.mockResolvedValueOnce(answer(row('a'), row('b', 'other')));
		outdateLibraryWrite();
		await ensureLibraryWriteRead();
		expect(ids()).toEqual(['a', 'b']);
	}
);

it.each(['song', 'album'] as const)(
	'defect:#1575 consumes stale %s restore recognition only once without inventing rows',
	async (kind) => {
		const remove = () => (kind === 'song' ? removeSongFromList('a') : removeSongsForAlbum('album'));
		const add = () =>
			kind === 'song'
				? addSongsToList([makeSong({ id: 'a' })])
				: addAlbumToList(makeAlbum({ id: 'album' }));
		fetch.mockResolvedValueOnce(answer(row('a')));
		await ensureLibraryWriteRead();
		fetch.mockResolvedValueOnce(answer());
		remove();
		await ensureLibraryWriteRead();
		fetch.mockResolvedValueOnce(answer(row('a'), row('b', 'other')));
		outdateLibraryWrite();
		await ensureLibraryWriteRead();
		fetch.mockResolvedValueOnce(answer(row('b', 'other'), row('a')));
		add();
		await ensureLibraryWriteRead();
		add();
		await ensureLibraryWriteRead();
		expect(fetch).toHaveBeenCalledTimes(4);
		expect(ids()).toEqual(['b', 'a']);
		expect(get(libraryWriteState)).toBe('ready');
	}
);

it.each(['album', 'song'] as const)(
	'1354_rule_20 defect:#1575 keeps a pre-removal %s answer excluded when the same ID is added before it settles',
	async (kind) => {
		const resolve = deferredRead();
		const oldRead = ensureLibraryWriteRead();
		const restored = deferredRead();
		if (kind === 'album') {
			removeSongsForAlbum('album');
			addAlbumToList(makeAlbum({ id: 'album' }));
		} else {
			removeSongFromList('a');
			addSongsToList([makeSong({ id: 'a' })]);
		}
		resolve(answer(row('a'), row('b', 'other')));
		await oldRead;
		expect(ids()).toEqual(['b']);
		restored(answer(row('a'), row('c', 'other')));
		await ensureLibraryWriteRead();
		expect(ids()).toEqual(['a', 'c']);
		expect(get(libraryWriteState)).toBe('ready');
		expect(fetch).toHaveBeenCalledTimes(2);
	}
);

it.each(['song', 'album'] as const)(
	'1354_rule_20 defect:#1575 restores the %s deleted again after Undo while one read stays in flight',
	async (kind) => {
		const remove = () => (kind === 'song' ? removeSongFromList('a') : removeSongsForAlbum('album'));
		const undo = () =>
			kind === 'song'
				? addSongsToList([makeSong({ id: 'a' })])
				: addAlbumToList(makeAlbum({ id: 'album' }));
		const resolve = deferredRead();
		const oldRead = ensureLibraryWriteRead();
		remove();
		undo();
		remove();
		const refill = deferredRead();
		resolve(answer(row('a'), row('b', 'other')));
		await oldRead;
		refill(answer(row('b', 'other')));
		await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
		await ensureLibraryWriteRead();
		expect(ids()).toEqual(['b']);
		fetch.mockResolvedValueOnce(answer(row('a'), row('b', 'other')));
		undo();
		await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(3));
		await ensureLibraryWriteRead();
		expect(ids()).toEqual(['a', 'b']);
		expect(get(libraryWriteState)).toBe('ready');
	}
);

it.each(['song', 'album'] as const)(
	'1354_rule_20 defect:#1575 a %s restored on another device and deleted here again leaves at once',
	async (kind) => {
		const remove = () => (kind === 'song' ? removeSongFromList('a') : removeSongsForAlbum('album'));
		fetch.mockResolvedValueOnce(answer(row('a'), row('b', 'other')));
		await ensureLibraryWriteRead();
		fetch.mockResolvedValueOnce(answer(row('b', 'other')));
		remove();
		await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
		await ensureLibraryWriteRead();
		expect(ids()).toEqual(['b']);
		fetch.mockResolvedValueOnce(answer(row('a'), row('b', 'other')));
		outdateLibraryWrite();
		await ensureLibraryWriteRead();
		expect(ids()).toEqual(['a', 'b']);
		const resolve = deferredRead();
		outdateLibraryWrite();
		const inFlight = ensureLibraryWriteRead();
		remove();
		expect(ids()).toEqual(['b']);
		fetch.mockResolvedValueOnce(answer(row('b', 'other')));
		resolve(answer(row('a'), row('b', 'other')));
		await inFlight;
		expect(ids()).toEqual(['b']);
		await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(5));
		await ensureLibraryWriteRead();
		expect(ids()).toEqual(['b']);
	}
);
