// The cover editor reloads the suggestions while the network is out: once the
// connection is back, through a bounded run of retries, and never past a Suggest.

import { makeAlbum as album, makeSong as song } from '#lib/test-utils/factories.ts';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { JobItem } from '#lib/api/types.ts';
import { UNREACHABLE_RELOAD_DELAYS_MS } from '#lib/constants/connectivity.ts';
import {
	reportResourceStreamReachable,
	resetConnectivityForTests
} from '#lib/stores/connectivity.ts';
import { albumList, resetLibraryDataForTests, songList } from '#lib/stores/libraryData.ts';
import { selectedAlbumId } from '#lib/stores/player.ts';
import { activeJobs } from '#lib/stores/jobs.ts';
import { lostNetwork } from '#lib/test-utils/network.ts';
import {
	FakeJobEventSource,
	ONE_SUGGESTION,
	PAST_EVERY_RELOAD_MS,
	RELOAD_ATTEMPTS,
	afterPageRead,
	coverJob,
	coverSuggestions,
	coveredAlbum,
	openCoverEditing,
	pressEditorButton,
	reachSuggestionsLoads,
	shownImage,
	stageText
} from '#lib/test-utils/album-cover-editor.ts';
import { deferred } from '#lib/test-utils/deferred.ts';
import { createComponentMount, requireElement } from './shell/rail-test-fixtures';

const fetchAlbumCoverSuggestions = vi.fn();
const createAlbumCoverSuggestions = vi.fn();
const discardAlbumCoverSuggestions = vi.fn();
const cancelJob = vi.fn();

vi.mock('#lib/api/songs.ts', () => ({
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false })
}));
vi.mock('#lib/api/albums.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/albums.ts')>()),
	createAlbumCoverSuggestions: (...args: unknown[]) => createAlbumCoverSuggestions(...args),
	fetchAlbumCoverSuggestions: (...args: unknown[]) => fetchAlbumCoverSuggestions(...args),
	discardAlbumCoverSuggestions: (...args: unknown[]) => discardAlbumCoverSuggestions(...args)
}));
vi.mock('#lib/api/jobs.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/jobs.ts')>()),
	cancelJob: (...args: unknown[]) => cancelJob(...args)
}));
vi.mock('#lib/stores/toast.ts', () => ({ addToast: vi.fn(), addUndoToast: vi.fn() }));

import AlbumDetailView from './AlbumDetailView.svelte';

const { render: renderDetail, cleanup } = createComponentMount(AlbumDetailView);

const renderAfterPageRead = () => afterPageRead(renderDetail, fetchAlbumCoverSuggestions);

beforeEach(() => {
	albumList.set([album({ id: 'a-local', title: 'Night Drive' })]);
	songList.set([
		song({ id: 's-local', album_id: 'a-local', album_title: 'Night Drive', generation_count: 1 })
	]);
	selectedAlbumId.set('a-local');
	createAlbumCoverSuggestions.mockReset();
	fetchAlbumCoverSuggestions.mockReset().mockResolvedValue(coverSuggestions());
	discardAlbumCoverSuggestions.mockReset().mockResolvedValue(undefined);
	cancelJob.mockReset().mockResolvedValue(coverJob({ status: 'cancelled' }));
	activeJobs.set([]);
	FakeJobEventSource.sources.length = 0;
});

afterEach(async () => {
	await cleanup();
	selectedAlbumId.set(null);
	albumList.set([]);
	songList.set([]);
	activeJobs.set([]);
	vi.unstubAllGlobals();
	vi.useRealTimers();
	resetConnectivityForTests();
	resetLibraryDataForTests();
});

describe('The album cover editor while the network is out', () => {
	it('reloads the suggestions once the connection is back', async () => {
		vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
		const target = await renderAfterPageRead();
		reportResourceStreamReachable(false);
		fetchAlbumCoverSuggestions.mockRejectedValue(lostNetwork());
		await openCoverEditing(target);
		await reachSuggestionsLoads(fetchAlbumCoverSuggestions, 1);
		await vi.advanceTimersByTimeAsync(PAST_EVERY_RELOAD_MS);
		expect(fetchAlbumCoverSuggestions).toHaveBeenCalledTimes(1);

		fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions(ONE_SUGGESTION));
		reportResourceStreamReachable(true);

		await vi.waitFor(() => expect(shownImage(target)).toBe('/suggestion-one.png'));
		expect(fetchAlbumCoverSuggestions).toHaveBeenCalledTimes(2);
		expect(createAlbumCoverSuggestions).not.toHaveBeenCalled();
	});

	it('offers a quiet Try again once the bounded reloads still find no network while online', async () => {
		vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
		const target = await renderAfterPageRead();
		fetchAlbumCoverSuggestions.mockRejectedValue(lostNetwork());
		await openCoverEditing(target);
		await reachSuggestionsLoads(fetchAlbumCoverSuggestions, 1);
		for (const [attempt, delay] of UNREACHABLE_RELOAD_DELAYS_MS.entries()) {
			expect(target.querySelector('.cover-suggestions-retry')).toBeNull();
			await vi.advanceTimersByTimeAsync(delay);
			await reachSuggestionsLoads(fetchAlbumCoverSuggestions, attempt + 2);
		}

		await vi.waitFor(() =>
			expect(target.querySelector('.cover-suggestions-retry')?.textContent?.trim()).toBe(
				'Try again'
			)
		);
		expect(target.querySelector('[role="alert"]')).toBeNull();
		await vi.advanceTimersByTimeAsync(PAST_EVERY_RELOAD_MS);
		expect(fetchAlbumCoverSuggestions).toHaveBeenCalledTimes(1 + RELOAD_ATTEMPTS);

		fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions(ONE_SUGGESTION));
		requireElement<HTMLButtonElement>(target, '.cover-suggestions-retry').click();

		await vi.waitFor(() => expect(shownImage(target)).toBe('/suggestion-one.png'));
	});

	it('Suggest another stops a pending reload of the suggestions', async () => {
		vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
		vi.stubGlobal('EventSource', FakeJobEventSource);
		albumList.set([coveredAlbum()]);
		const suggestionJob = deferred<JobItem>();
		createAlbumCoverSuggestions.mockImplementation(() => suggestionJob.promise);
		const target = await renderAfterPageRead();
		fetchAlbumCoverSuggestions
			.mockRejectedValueOnce(lostNetwork())
			.mockResolvedValue(coverSuggestions({ job: coverJob({ status: 'running' }) }));
		await openCoverEditing(target);
		await reachSuggestionsLoads(fetchAlbumCoverSuggestions, 1);

		pressEditorButton(target, 'Suggest');
		await vi.waitFor(() => expect(createAlbumCoverSuggestions).toHaveBeenCalledWith('a-local'));
		await vi.advanceTimersByTimeAsync(PAST_EVERY_RELOAD_MS);

		expect(fetchAlbumCoverSuggestions).toHaveBeenCalledTimes(1);
		suggestionJob.resolve(coverJob());
		await vi.waitFor(() => expect(stageText(target)).toContain('Making a cover'));
	});
});
