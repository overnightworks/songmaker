import { beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

const fetchLibraryListen = vi.fn();
vi.mock('#lib/api/library.ts', () => ({
	fetchLibraryListen: (...args: unknown[]) => fetchLibraryListen(...args)
}));

import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import { chooseLibraryWallOrder } from './ui';
import {
	ensureLastPlayedRead,
	inLibraryOrder,
	libraryPlaceOrder,
	outdateLastPlayedRanking,
	readLastPlayed,
	resetLibraryOrderForTests
} from './libraryOrder';

type Titled = { id: string; title: string };

const titled = (title: string): Titled => ({ id: title.toLowerCase(), title });

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
	audioPlayer.current = null;
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

	it('orders Last played by the last listen read, unranked places last in title order', async () => {
		chooseLibraryWallOrder('played');
		fetchLibraryListen.mockResolvedValue({
			items: [listened('kinetic'), listened('vernissage')]
		});
		const albums = ['Nightdrive', 'Vernissage', 'Kinetic', 'Afterglow'].map((title) =>
			titled(title)
		);

		expect(await readLastPlayed()).toBe(true);

		expect(fetchLibraryListen).toHaveBeenCalledWith({ offset: 0, limit: 200 });
		expect(titlesOf(inLibraryOrder('album', albums, get(libraryPlaceOrder)))).toEqual([
			'Kinetic',
			'Vernissage',
			'Afterglow',
			'Nightdrive'
		]);
	});

	it('keeps the last ranking when a later read fails', async () => {
		chooseLibraryWallOrder('played');
		fetchLibraryListen.mockResolvedValueOnce({ items: [listened('kinetic')] });
		await readLastPlayed();
		fetchLibraryListen.mockRejectedValueOnce(new Error('offline'));

		expect(await readLastPlayed()).toBe(false);

		const albums = [titled('Afterglow'), titled('Kinetic')];
		expect(titlesOf(inLibraryOrder('album', albums, get(libraryPlaceOrder)))).toEqual([
			'Kinetic',
			'Afterglow'
		]);
	});

	it('reads the last-played ranking once for every caller that only needs it present', async () => {
		fetchLibraryListen.mockResolvedValue({ items: [listened('kinetic')] });

		await Promise.all([ensureLastPlayedRead(), ensureLastPlayedRead()]);
		await ensureLastPlayedRead();

		expect(fetchLibraryListen).toHaveBeenCalledTimes(1);
	});

	it.each([
		[
			'the wall and both rail groups opening together',
			[readLastPlayed, ensureLastPlayedRead, ensureLastPlayedRead]
		],
		['a rail group opening before the wall', [ensureLastPlayedRead, readLastPlayed]]
	])(
		'1354_rule_8: starts one Listen read for %s, and reads again once it has come back',
		async (_, readers) => {
			fetchLibraryListen.mockResolvedValue({ items: [listened('kinetic')] });

			const applied = await Promise.all(readers.map((read) => read()));

			expect(applied).toEqual(readers.map(() => true));
			expect(fetchLibraryListen).toHaveBeenCalledTimes(1);
			await readLastPlayed();
			expect(fetchLibraryListen).toHaveBeenCalledTimes(2);
		}
	);

	it('1354_rule_8: asks Listen again only for a caller whose ranking is not yet present', async () => {
		fetchLibraryListen.mockRejectedValueOnce(new Error('offline'));
		expect(await ensureLastPlayedRead()).toBe(false);
		fetchLibraryListen.mockResolvedValue({ items: [listened('kinetic')] });

		expect(await ensureLastPlayedRead()).toBe(true);
		expect(await ensureLastPlayedRead()).toBe(true);

		expect(fetchLibraryListen).toHaveBeenCalledTimes(2);
	});

	it('1354_rule_8: asks Listen again for a caller once a recorded listen has outdated the ranking', async () => {
		fetchLibraryListen.mockResolvedValue({ items: [listened('kinetic')] });
		await ensureLastPlayedRead();
		await ensureLastPlayedRead();
		expect(fetchLibraryListen).toHaveBeenCalledTimes(1);

		outdateLastPlayedRanking();
		await ensureLastPlayedRead();
		await ensureLastPlayedRead();

		expect(fetchLibraryListen).toHaveBeenCalledTimes(2);
	});

	it('1354_rule_8: keeps the ranking present when a take is restored without a recorded listen', async () => {
		fetchLibraryListen.mockResolvedValue({ items: [listened('kinetic')] });
		await ensureLastPlayedRead();

		audioPlayer.current = { generation: { id: 'g-2' } } as unknown as typeof audioPlayer.current;
		await ensureLastPlayedRead();

		expect(fetchLibraryListen).toHaveBeenCalledTimes(1);
	});

	it('defect:#1537: reads again after a listen recorded while a read was out, which may not have seen it', async () => {
		const answer = Promise.withResolvers<{ items: ReturnType<typeof listened>[] }>();
		fetchLibraryListen.mockReturnValueOnce(answer.promise);
		const read = ensureLastPlayedRead();

		outdateLastPlayedRanking();
		answer.resolve({ items: [listened('kinetic')] });
		await read;
		fetchLibraryListen.mockResolvedValue({ items: [listened('kinetic')] });
		await ensureLastPlayedRead();

		expect(fetchLibraryListen).toHaveBeenCalledTimes(2);
	});

	it('defect:#1537: keeps the places in their ranked order while an outdated ranking waits for the next read', async () => {
		chooseLibraryWallOrder('played');
		fetchLibraryListen.mockResolvedValue({ items: [listened('kinetic')] });
		await ensureLastPlayedRead();
		const albums = ['Afterglow', 'Kinetic'].map((title) => titled(title));

		outdateLastPlayedRanking();

		expect(get(libraryPlaceOrder).known).toBe(true);
		expect(titlesOf(inLibraryOrder('album', albums, get(libraryPlaceOrder)))).toEqual([
			'Kinetic',
			'Afterglow'
		]);
	});

	it('1354_rule_8: holds every place back while Last played is chosen until Listen has answered', async () => {
		chooseLibraryWallOrder('played');
		const answer = Promise.withResolvers<{ items: ReturnType<typeof listened>[] }>();
		fetchLibraryListen.mockReturnValue(answer.promise);
		const albums = ['Afterglow', 'Kinetic'].map((title) => titled(title));
		const read = readLastPlayed();

		expect(get(libraryPlaceOrder).known).toBe(false);
		expect(inLibraryOrder('album', albums, get(libraryPlaceOrder))).toEqual([]);

		answer.resolve({ items: [listened('kinetic')] });
		await read;

		expect(get(libraryPlaceOrder).known).toBe(true);
		expect(titlesOf(inLibraryOrder('album', albums, get(libraryPlaceOrder)))).toEqual([
			'Kinetic',
			'Afterglow'
		]);
	});

	it('1354_rule_8: keeps the places in the order a viewer sees while they switch to Last played, until Listen has answered', async () => {
		const albums = ['Afterglow', 'Kinetic'].map((title) => titled(title));
		const standing = () => titlesOf(inLibraryOrder('album', albums, get(libraryPlaceOrder)));
		expect(standing()).toEqual(['Afterglow', 'Kinetic']);
		const answer = Promise.withResolvers<{ items: ReturnType<typeof listened>[] }>();
		fetchLibraryListen.mockReturnValue(answer.promise);

		chooseLibraryWallOrder('played');
		const read = readLastPlayed();

		expect(standing()).toEqual(['Afterglow', 'Kinetic']);

		answer.resolve({ items: [listened('kinetic')] });
		await read;

		expect(standing()).toEqual(['Kinetic', 'Afterglow']);
	});

	it('1354_rule_8: stands the places in title order when the first read fails, rather than holding them for good', async () => {
		chooseLibraryWallOrder('played');
		fetchLibraryListen.mockRejectedValue(new Error('offline'));

		await readLastPlayed();

		const albums = ['Kinetic', 'Afterglow'].map((title) => titled(title));
		expect(titlesOf(inLibraryOrder('album', albums, get(libraryPlaceOrder)))).toEqual([
			'Afterglow',
			'Kinetic'
		]);
	});
});
