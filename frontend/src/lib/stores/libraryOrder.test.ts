import { beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

const fetchLibraryListen = vi.fn();
vi.mock('$lib/api/library', () => ({
	fetchLibraryListen: (...args: unknown[]) => fetchLibraryListen(...args)
}));

import { chooseLibraryWallOrder } from './ui';
import {
	ensureRecentWorkRead,
	inLibraryOrder,
	libraryPlaceOrder,
	readRecentWork,
	resetLibraryOrderForTests
} from './libraryOrder';

type Titled = { id: string; title: string; created_at: string };

const titled = (title: string, created_at = '2026-09-01T10:00:00Z'): Titled => ({
	id: title.toLowerCase(),
	title,
	created_at
});

const titlesOf = (items: readonly Titled[]) => items.map((item) => item.title);

const listened = (id: string) => ({
	type: 'album' as const,
	id,
	title: id,
	album_covers: [],
	played_at: '2026-09-27T03:47:00Z'
});

beforeEach(() => {
	localStorage.clear();
	chooseLibraryWallOrder('title');
	resetLibraryOrderForTests();
	fetchLibraryListen.mockReset().mockResolvedValue({ items: [] });
});

describe('library order', () => {
	it('orders A–Z by the natural title comparison, number by number', () => {
		const albums = ['Filler 10', 'nightdrive', 'Filler 2', 'Afterglow'].map((title) =>
			titled(title)
		);

		expect(titlesOf(inLibraryOrder('album', albums, get(libraryPlaceOrder)))).toEqual([
			'Afterglow',
			'Filler 2',
			'Filler 10',
			'nightdrive'
		]);
	});

	it('orders Added newest first', () => {
		chooseLibraryWallOrder('added');
		const albums = [
			titled('Old', '2026-07-28T10:00:00Z'),
			titled('New', '2026-09-01T10:00:00Z'),
			titled('Middle', '2026-08-03T10:00:00Z')
		];

		expect(titlesOf(inLibraryOrder('album', albums, get(libraryPlaceOrder)))).toEqual([
			'New',
			'Middle',
			'Old'
		]);
	});

	it('orders Recent by the last listen read, unranked places last in title order', async () => {
		chooseLibraryWallOrder('recent');
		fetchLibraryListen.mockResolvedValue({
			items: [listened('kinetic'), listened('vernissage')]
		});
		const albums = ['Afterglow', 'Vernissage', 'Kinetic', 'Nightdrive'].map((title) =>
			titled(title)
		);

		expect(await readRecentWork()).toBe(true);

		expect(fetchLibraryListen).toHaveBeenCalledWith({ offset: 0, limit: 200 });
		expect(titlesOf(inLibraryOrder('album', albums, get(libraryPlaceOrder)))).toEqual([
			'Kinetic',
			'Vernissage',
			'Afterglow',
			'Nightdrive'
		]);
	});

	it('keeps the last ranking when a later read fails', async () => {
		chooseLibraryWallOrder('recent');
		fetchLibraryListen.mockResolvedValueOnce({ items: [listened('kinetic')] });
		await readRecentWork();
		fetchLibraryListen.mockRejectedValueOnce(new Error('offline'));

		expect(await readRecentWork()).toBe(false);

		const albums = [titled('Afterglow'), titled('Kinetic')];
		expect(titlesOf(inLibraryOrder('album', albums, get(libraryPlaceOrder)))).toEqual([
			'Kinetic',
			'Afterglow'
		]);
	});

	it('reads the recent ranking once for every caller that only needs it present', async () => {
		fetchLibraryListen.mockResolvedValue({ items: [listened('kinetic')] });

		await Promise.all([ensureRecentWorkRead(), ensureRecentWorkRead()]);
		await ensureRecentWorkRead();

		expect(fetchLibraryListen).toHaveBeenCalledTimes(1);
	});
});
