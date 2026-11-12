import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '#lib/api/fetch.ts';
import { words } from '#lib/words/en.ts';
import { resetLibraryContextForTests } from '#lib/stores/libraryContext.ts';
import { albumList, resetLibraryDataForTests } from '#lib/stores/libraryData.ts';
import { resourceSync, retryResourceSync } from '#lib/stores/resourceSync.ts';
import {
	albumsPage,
	createComponentMount,
	requireButtonContainingText,
	requireElement,
	songsPage
} from './rail-test-fixtures';

vi.mock('$app/navigation', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation()
);
vi.mock('$app/state', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppState()
);
vi.mock('#lib/stores/resourceSync.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/stores/resourceSync.ts')>()),
	retryResourceSync: vi.fn()
}));
vi.mock('$app/paths', async () => (await import('./rail-test-fixtures')).railPathsMock());
vi.mock('#lib/api/library.ts', async () =>
	(await import('./rail-test-fixtures')).railLibraryApiMock()
);
vi.mock('#lib/api/albums.ts', async () =>
	(await import('./rail-test-fixtures')).railAlbumsApiMock()
);
vi.mock('#lib/api/songs.ts', async () => (await import('./rail-test-fixtures')).railSongsApiMock());
const fetchAlbums = vi.fn();
const fetchSongs = vi.fn();
vi.mock('#lib/api/client.ts', async () => {
	const { railClientApiMock } = await import('./rail-test-fixtures');
	return railClientApiMock({
		fetchAlbums: (...args: unknown[]) => fetchAlbums(...args),
		fetchSongs: (...args: unknown[]) => fetchSongs(...args)
	});
});

import RailLibraryGroup from './RailLibraryGroup.svelte';

const { render, cleanup } = createComponentMount(RailLibraryGroup);

beforeEach(() => {
	localStorage.clear();
	resetLibraryContextForTests();
	fetchSongs.mockClear().mockResolvedValue(songsPage());
	resetLibraryDataForTests();
	albumList.set([]);
	resourceSync.update((state) => ({ ...state, ready: false, status: 'error' }));
});

afterEach(async () => {
	await cleanup();
	vi.mocked(retryResourceSync).mockReset();
	resourceSync.update((state) => ({ ...state, ready: true, status: 'live' }));
	resetLibraryContextForTests();
});

async function renderWithFailedRail(): Promise<HTMLElement> {
	fetchAlbums
		.mockReset()
		.mockRejectedValueOnce(new ApiError(503, 'Backend unreachable', '/api/albums'));
	const target = await render();
	await vi.waitFor(() =>
		expect(requireElement(target, '[role="alert"]').textContent).toBe('Backend unreachable')
	);
	return target;
}

describe('RailLibraryGroup Retry while the library load failed', () => {
	it('retries the library only and shows loading until that settles', async () => {
		const target = await renderWithFailedRail();
		const loadsBefore = fetchAlbums.mock.calls.length;
		let settle!: (recovered: boolean) => void;
		vi.mocked(retryResourceSync).mockReturnValue(new Promise((resolve) => (settle = resolve)));

		requireButtonContainingText(target, words['rail.retry']).click();
		await tick();

		expect(requireElement(target, '.rail-loading').textContent).toBe(words['rail.libraryLoading']);
		expect(target.querySelector('.rail-load-error')).toBeNull();
		expect(target.querySelector('[role="alert"]')).toBeNull();
		expect(fetchAlbums).toHaveBeenCalledTimes(loadsBefore);

		settle(true);
		await vi.waitFor(() => expect(target.textContent).not.toContain(words['rail.libraryLoading']));
	});

	it('shows its failure words and Retry again when the library retry settles false', async () => {
		const target = await renderWithFailedRail();
		vi.mocked(retryResourceSync).mockResolvedValue(false);

		requireButtonContainingText(target, words['rail.retry']).click();
		await tick();
		expect(target.textContent).toContain(words['rail.libraryLoading']);

		await vi.waitFor(() =>
			expect(requireElement(target, '[role="alert"]').textContent).toBe('Backend unreachable')
		);
		expect(requireButtonContainingText(target, words['rail.retry'])).toBeInstanceOf(
			HTMLButtonElement
		);
	});

	it('runs the rail load again, not the library retry, once the library is live', async () => {
		const target = await renderWithFailedRail();
		resourceSync.update((state) => ({ ...state, ready: true, status: 'live' }));
		fetchAlbums.mockResolvedValueOnce(albumsPage());

		requireButtonContainingText(target, words['rail.retry']).click();

		await vi.waitFor(() => expect(target.querySelector('[role="alert"]')).toBeNull());
		expect(retryResourceSync).not.toHaveBeenCalled();
	});
});
