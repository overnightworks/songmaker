// The album page keeps the cover state read; opening the editor reads it once
// more without stopping or discarding anything, and an Upload that deletes the
// waiting suggestions leaves the closed cover without a mark. A Suggest that ×
// retired holds nothing of what comes after it.

import { makeAlbum as album, makeSong as song } from '#lib/test-utils/factories.ts';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { resetConnectivityForTests } from '#lib/stores/connectivity.ts';
import { albumList, resetLibraryDataForTests, songList } from '#lib/stores/libraryData.ts';
import { selectedAlbumId } from '#lib/stores/player.ts';
import { activeJobs } from '#lib/stores/jobs.ts';
import type { JobItem } from '#lib/api/types.ts';
import { getByRoleButton } from '#lib/test-utils/accessible-name.ts';
import {
	FakeJobEventSource,
	ONE_SUGGESTION,
	UPLOADED,
	afterPageRead,
	countLine,
	coverJob,
	coverSuggestions,
	coveredAlbum,
	deferred,
	editingClosed,
	openCoverEditing,
	pressEditorButton,
	pressSuggestOnceLoaded,
	shownImage,
	uploadCoverFile
} from '#lib/test-utils/album-cover-editor.ts';
import { createComponentMount, requireElement } from './shell/rail-test-fixtures';

const fetchAlbumCoverSuggestions = vi.fn();
const createAlbumCoverSuggestions = vi.fn();
const discardAlbumCoverSuggestions = vi.fn();
const uploadAlbumCover = vi.fn();
const cancelJob = vi.fn();

vi.mock('#lib/api/songs.ts', () => ({
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false })
}));
vi.mock('#lib/api/albums.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/albums.ts')>()),
	fetchAlbumCoverSuggestions: (...args: unknown[]) => fetchAlbumCoverSuggestions(...args),
	createAlbumCoverSuggestions: (...args: unknown[]) => createAlbumCoverSuggestions(...args),
	discardAlbumCoverSuggestions: (...args: unknown[]) => discardAlbumCoverSuggestions(...args)
}));
vi.mock('#lib/api/jobs.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/jobs.ts')>()),
	cancelJob: (...args: unknown[]) => cancelJob(...args)
}));
vi.mock('#lib/api/client.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/client.ts')>()),
	uploadAlbumCover: (...args: unknown[]) => uploadAlbumCover(...args)
}));
vi.mock('#lib/stores/toast.ts', () => ({ addToast: vi.fn(), addUndoToast: vi.fn() }));

import AlbumDetailView from './AlbumDetailView.svelte';

const { render: renderDetail, cleanup } = createComponentMount(AlbumDetailView);

function editorButton(target: HTMLElement, name: string): HTMLButtonElement {
	return getByRoleButton(requireElement(target, '.cover-editor'), name);
}

async function closeWithX(target: HTMLElement): Promise<void> {
	pressEditorButton(target, 'Close cover editing');
	await editingClosed(target);
}

const askAnswers = [
	{
		answer: 'succeeds',
		settle: (ask: ReturnType<typeof deferred<JobItem>>) => ask.resolve(coverJob())
	},
	{
		answer: 'fails',
		settle: (ask: ReturnType<typeof deferred<JobItem>>) => ask.reject(new Error('down'))
	}
];

beforeEach(() => {
	albumList.set([album({ id: 'a-local', title: 'Night Drive' })]);
	songList.set([
		song({ id: 's-local', album_id: 'a-local', album_title: 'Night Drive', generation_count: 1 })
	]);
	selectedAlbumId.set('a-local');
	fetchAlbumCoverSuggestions.mockReset().mockResolvedValue(coverSuggestions());
	createAlbumCoverSuggestions.mockReset();
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

	it('opening the editor before the page read answered says the suggestions still load', async () => {
		const pageRead = deferred<ReturnType<typeof coverSuggestions>>();
		fetchAlbumCoverSuggestions.mockReturnValue(pageRead.promise);
		const target = await renderDetail();

		await openCoverEditing(target);
		expect(countLine(target)).toBe('Loading cover suggestion…');

		pageRead.resolve(coverSuggestions());
		await vi.waitFor(() => expect(countLine(target)).toBe('10 of 10 left today'));
	});

	it.each(askAnswers)(
		'× on an ask that knew nothing frees Suggest when the ask $answer late',
		async ({ settle }) => {
			const ask = deferred<JobItem>();
			createAlbumCoverSuggestions.mockReturnValue(ask.promise);
			const target = await renderDetail();
			await openCoverEditing(target);
			await pressSuggestOnceLoaded(target);
			await vi.waitFor(() => expect(createAlbumCoverSuggestions).toHaveBeenCalledTimes(1));

			await closeWithX(target);
			settle(ask);
			await new Promise((settled) => setTimeout(settled, 0));
			await openCoverEditing(target);

			await vi.waitFor(() => expect(editorButton(target, 'Suggest').disabled).toBe(false));
		}
	);

	it('an ask × retired that fails late leaves the newer ask waiting and unannounced', async () => {
		fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions(ONE_SUGGESTION));
		const retiredAsk = deferred<JobItem>();
		createAlbumCoverSuggestions
			.mockReturnValueOnce(retiredAsk.promise)
			.mockReturnValueOnce(deferred<JobItem>().promise);
		const target = await renderDetail();
		await openCoverEditing(target);
		await vi.waitFor(() => expect(editorButton(target, 'Suggest another').disabled).toBe(false));
		editorButton(target, 'Suggest another').click();
		await closeWithX(target);
		await openCoverEditing(target);
		await vi.waitFor(() => expect(editorButton(target, 'Suggest another').disabled).toBe(false));
		editorButton(target, 'Suggest another').click();
		await vi.waitFor(() => expect(createAlbumCoverSuggestions).toHaveBeenCalledTimes(2));

		retiredAsk.reject(new Error('down'));
		await new Promise((settled) => setTimeout(settled, 0));

		expect(editorButton(target, 'Suggest another').disabled).toBe(true);
		expect(target.querySelector('.cover-failure')).toBeNull();
	});
});
