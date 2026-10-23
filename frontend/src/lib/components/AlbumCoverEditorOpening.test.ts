// The album page keeps the cover state read; opening the editor reads it once
// more without stopping or discarding anything, and an Upload that deletes the
// waiting suggestions leaves the closed cover without a mark.

import { makeAlbum as album, makeSong as song } from '$lib/test-utils/factories';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { resetConnectivityForTests } from '$lib/stores/connectivity';
import { albumList, resetLibraryDataForTests, songList } from '$lib/stores/libraryData';
import { selectedAlbumId } from '$lib/stores/player';
import { activeJobs } from '$lib/stores/jobs';
import {
	FakeJobEventSource,
	ONE_SUGGESTION,
	UPLOADED,
	afterPageRead,
	coverJob,
	coverSuggestions,
	coveredAlbum,
	deferred,
	editingClosed,
	openCoverEditing,
	shownImage,
	uploadCoverFile
} from '$lib/test-utils/album-cover-editor';
import { createComponentMount, requireElement } from './shell/rail-test-fixtures';

const fetchAlbumCoverSuggestions = vi.fn();
const discardAlbumCoverSuggestions = vi.fn();
const uploadAlbumCover = vi.fn();
const cancelJob = vi.fn();

vi.mock('$lib/api/songs', () => ({
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false })
}));
vi.mock('$lib/api/albums', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/albums')>()),
	fetchAlbumCoverSuggestions: (...args: unknown[]) => fetchAlbumCoverSuggestions(...args),
	discardAlbumCoverSuggestions: (...args: unknown[]) => discardAlbumCoverSuggestions(...args)
}));
vi.mock('$lib/api/jobs', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/jobs')>()),
	cancelJob: (...args: unknown[]) => cancelJob(...args)
}));
vi.mock('$lib/api/client', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/client')>()),
	uploadAlbumCover: (...args: unknown[]) => uploadAlbumCover(...args)
}));
vi.mock('$lib/stores/toast', () => ({ addToast: vi.fn(), addUndoToast: vi.fn() }));

import AlbumDetailView from './AlbumDetailView.svelte';

const { render: renderDetail, cleanup } = createComponentMount(AlbumDetailView);

beforeEach(() => {
	albumList.set([album({ id: 'a-local', title: 'Night Drive' })]);
	songList.set([
		song({ id: 's-local', album_id: 'a-local', album_title: 'Night Drive', generation_count: 1 })
	]);
	selectedAlbumId.set('a-local');
	fetchAlbumCoverSuggestions.mockReset().mockResolvedValue(coverSuggestions());
	discardAlbumCoverSuggestions.mockReset().mockResolvedValue(undefined);
	uploadAlbumCover.mockReset();
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
	resetConnectivityForTests();
	resetLibraryDataForTests();
});

describe('The album cover state around the editor', () => {
	it('opening the editor reads the state again and stops and discards nothing', async () => {
		const target = await afterPageRead(renderDetail, fetchAlbumCoverSuggestions);

		await openCoverEditing(target);

		await vi.waitFor(() => expect(fetchAlbumCoverSuggestions).toHaveBeenCalled());
		expect(cancelJob).not.toHaveBeenCalled();
		expect(discardAlbumCoverSuggestions).not.toHaveBeenCalled();
	});

	it('the closed cover shows no waiting mark once an Upload has deleted the suggestions', async () => {
		let deleted = false;
		fetchAlbumCoverSuggestions.mockImplementation(async () =>
			coverSuggestions(deleted ? { suggestions: [] } : ONE_SUGGESTION)
		);
		const deleting = deferred<undefined>();
		discardAlbumCoverSuggestions.mockReturnValue(deleting.promise);
		uploadAlbumCover.mockResolvedValue(coveredAlbum(UPLOADED));
		const target = await renderDetail();
		await openCoverEditing(target);
		await vi.waitFor(() => expect(shownImage(target)).toBe('/suggestion-one.png'));

		uploadCoverFile(target);
		await editingClosed(target);
		await vi.waitFor(() => expect(discardAlbumCoverSuggestions).toHaveBeenCalled());
		deleted = true;
		deleting.resolve(undefined);

		await vi.waitFor(() =>
			expect(
				requireElement(target, 'button.header-cover').getAttribute('aria-label') ?? ''
			).not.toContain('waiting')
		);
	});
});
