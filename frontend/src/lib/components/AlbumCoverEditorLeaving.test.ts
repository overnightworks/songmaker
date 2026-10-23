// Leaving the cover editor stops nothing; only ×, a successful Use and a
// successful Upload stop a running suggestion and discard the unused ones.
// Every way out is driven through the album header.

import { makeAlbum as album, makeSong as song } from '$lib/test-utils/factories';
import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { AlbumItem, CoverSuggestionsResponse, JobItem } from '$lib/api/types';
import { serverRefusal } from '$lib/test-utils/network';
import { getByRoleButton } from '$lib/test-utils/accessible-name';
import { resetConnectivityForTests } from '$lib/stores/connectivity';
import { listenForGlobalEscape } from '$lib/test-utils/global-escape';
import { dropLayersFrom, stackedLayers } from '$lib/stores/layers';
import { createComponentMount, requireElement } from './shell/rail-test-fixtures';
import { albumList, resetLibraryDataForTests, songList } from '$lib/stores/libraryData';
import { selectedAlbumId } from '$lib/stores/player';
import { activeJobs } from '$lib/stores/jobs';
import {
	FakeJobEventSource,
	coverSuggestions,
	coverJob,
	ONE_SUGGESTION,
	THREE_SUGGESTIONS,
	UPLOADED,
	coveredAlbum,
	editor,
	openCoverEditing,
	editingClosed,
	countLine,
	shownImage,
	pressSuggestOnceLoaded,
	pressEditorButton,
	uploadCoverFile,
	deferred
} from '$lib/test-utils/album-cover-editor';

const createAlbumCoverSuggestions = vi.fn();
const fetchAlbumCoverSuggestions = vi.fn();
const selectAlbumCoverSuggestion = vi.fn();
const discardAlbumCoverSuggestions = vi.fn();
const deleteAlbumCover = vi.fn();
const uploadAlbumCover = vi.fn();
const cancelJob = vi.fn();

vi.mock('$lib/api/songs', () => ({
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false })
}));
vi.mock('$lib/api/albums', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/albums')>()),
	createAlbumCoverSuggestions: (...args: unknown[]) => createAlbumCoverSuggestions(...args),
	fetchAlbumCoverSuggestions: (...args: unknown[]) => fetchAlbumCoverSuggestions(...args),
	selectAlbumCoverSuggestion: (...args: unknown[]) => selectAlbumCoverSuggestion(...args),
	discardAlbumCoverSuggestions: (...args: unknown[]) => discardAlbumCoverSuggestions(...args)
}));
vi.mock('$lib/api/jobs', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/jobs')>()),
	cancelJob: (...args: unknown[]) => cancelJob(...args)
}));
vi.mock('$lib/api/client', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/client')>()),
	deleteAlbumCover: (...args: unknown[]) => deleteAlbumCover(...args),
	uploadAlbumCover: (...args: unknown[]) => uploadAlbumCover(...args)
}));
vi.mock('$lib/stores/toast', () => ({
	addToast: vi.fn(),
	addUndoToast: vi.fn()
}));

import AlbumDetailView from './AlbumDetailView.svelte';
import { addToast } from '$lib/stores/toast';

const { render: renderDetail, cleanup } = createComponentMount(AlbumDetailView);

// A server that reports the run as going until it has been asked to cancel it.
function serverRunsUntilCancelled(extra: Partial<CoverSuggestionsResponse> = {}): void {
	fetchAlbumCoverSuggestions.mockImplementation(async () =>
		coverSuggestions({
			...extra,
			job: coverJob({ status: cancelJob.mock.calls.length > 0 ? 'cancelled' : 'running' }),
			used_today: 1
		})
	);
}

// The album page read the state when it opened; coming back to it reads again.
function comeBackToThePage(): void {
	document.dispatchEvent(new Event('visibilitychange'));
}

async function openEditorWithRunningSuggestion(
	target: HTMLElement,
	extra: Partial<CoverSuggestionsResponse> = {}
): Promise<void> {
	serverRunsUntilCancelled(extra);
	comeBackToThePage();
	await openCoverEditing(target);
	await vi.waitFor(() =>
		expect(target.querySelector('.cover-stage [role="status"]')).not.toBeNull()
	);
}

async function askForAnotherSuggestion(target: HTMLElement): Promise<void> {
	await vi.waitFor(() =>
		expect(
			getByRoleButton(requireElement(target, '.cover-editor'), 'Suggest another').disabled
		).toBe(false)
	);
	pressEditorButton(target, 'Suggest another');
	await vi.waitFor(() => expect(createAlbumCoverSuggestions).toHaveBeenCalledWith('a-local'));
}

async function reachSuggestionsLoads(count: number): Promise<void> {
	await vi.waitFor(() => expect(fetchAlbumCoverSuggestions).toHaveBeenCalledTimes(count));
	await tick();
}

beforeEach(() => {
	albumList.set([album({ id: 'a-local', title: 'Night Drive' })]);
	songList.set([
		song({ id: 's-local', album_id: 'a-local', album_title: 'Night Drive', generation_count: 1 })
	]);
	selectedAlbumId.set('a-local');
	createAlbumCoverSuggestions.mockReset();
	fetchAlbumCoverSuggestions.mockReset().mockResolvedValue(coverSuggestions());
	selectAlbumCoverSuggestion.mockReset();
	discardAlbumCoverSuggestions.mockReset().mockResolvedValue(undefined);
	deleteAlbumCover.mockReset();
	uploadAlbumCover.mockReset();
	cancelJob.mockReset().mockResolvedValue(coverJob({ status: 'cancelled' }));
	vi.mocked(addToast).mockReset();
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

describe('Leaving the album cover editor', () => {
	it('Escape closes the editor and moves no level up, keeping the suggestions and the run', async () => {
		fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions(THREE_SUGGESTIONS));
		const target = await renderDetail();
		await openCoverEditing(target);
		await vi.waitFor(() => expect(shownImage(target)).toBe('/suggestion-three.png'));
		const levelUp = vi.fn();
		const stopListening = listenForGlobalEscape(levelUp);

		document.body.dispatchEvent(
			new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
		);
		stopListening();

		await editingClosed(target);
		expect(discardAlbumCoverSuggestions).not.toHaveBeenCalled();
		expect(cancelJob).not.toHaveBeenCalled();
		expect(levelUp).not.toHaveBeenCalled();
	});

	it.each([
		{
			way: '×',
			leave: (target: HTMLElement) => pressEditorButton(target, 'Close cover editing')
		},
		{
			way: 'Upload',
			leave: (target: HTMLElement) => {
				uploadAlbumCover.mockResolvedValue(coveredAlbum(UPLOADED));
				uploadCoverFile(target);
			}
		},
		{
			way: 'Use',
			leave: async (target: HTMLElement) => {
				selectAlbumCoverSuggestion.mockResolvedValue(coveredAlbum());
				pressEditorButton(target, 'Previous suggestion');
				await tick();
				pressEditorButton(target, 'Use');
			}
		}
	])('$way stops the running suggestion and discards the unused ones', async ({ leave }) => {
		vi.stubGlobal('EventSource', FakeJobEventSource);
		const target = await renderDetail();
		await openEditorWithRunningSuggestion(target, ONE_SUGGESTION);

		await leave(target);

		await editingClosed(target);
		await vi.waitFor(() =>
			expect(discardAlbumCoverSuggestions).toHaveBeenCalledWith('a-local', {
				suggestionIds: ['one'],
				jobIds: ['cover-job']
			})
		);
		expect(discardAlbumCoverSuggestions).toHaveBeenCalledTimes(1);
		expect(cancelJob).toHaveBeenCalledWith('cover-job');
		expect(cancelJob.mock.invocationCallOrder[0]).toBeLessThan(
			discardAlbumCoverSuggestions.mock.invocationCallOrder[0]
		);
		expect(get(activeJobs)).toEqual([]);
	});

	it.each([
		{
			way: 'Escape',
			leave: () =>
				document.body.dispatchEvent(
					new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
				)
		},
		{ way: 'Back', leave: () => dropLayersFrom(stackedLayers().length - 1) },
		{ way: 'another album', leave: () => selectedAlbumId.set('a-other') },
		{ way: 'navigating away', leave: () => cleanup() },
		{
			way: 'Remove',
			leave: (target: HTMLElement) => {
				deleteAlbumCover.mockResolvedValue(album({ id: 'a-local', title: 'Night Drive' }));
				pressEditorButton(target, 'Remove');
			}
		}
	])(
		'leaving by $way leaves the suggestion running and the unused ones in place',
		async ({ leave }) => {
			vi.stubGlobal('EventSource', FakeJobEventSource);
			albumList.set([coveredAlbum(), album({ id: 'a-other', title: 'Other Night' })]);
			const stopListening = listenForGlobalEscape();
			const target = await renderDetail();
			await openEditorWithRunningSuggestion(target, ONE_SUGGESTION);

			await leave(target);
			await vi.waitFor(() => expect(editor(target)).toBeNull());
			await new Promise((settled) => setTimeout(settled, 0));
			stopListening();

			expect(cancelJob).not.toHaveBeenCalled();
			expect(discardAlbumCoverSuggestions).not.toHaveBeenCalled();
			expect(get(activeJobs).map((active) => active.job.id)).toEqual(['cover-job']);
		}
	);

	it('opening the editor again after leaving follows the run that went on', async () => {
		vi.stubGlobal('EventSource', FakeJobEventSource);
		const stopListening = listenForGlobalEscape();
		const target = await renderDetail();
		await openEditorWithRunningSuggestion(target, ONE_SUGGESTION);
		document.body.dispatchEvent(
			new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
		);
		await editingClosed(target);
		stopListening();

		await openCoverEditing(target);

		await vi.waitFor(() =>
			expect(target.querySelector('.cover-stage [role="status"]')).not.toBeNull()
		);
		expect(countLine(target)).toBe('9 of 10 left today');
	});

	it.each([
		{
			way: '×',
			leave: (target: HTMLElement) => pressEditorButton(target, 'Close cover editing')
		},
		{
			way: 'Use',
			leave: (target: HTMLElement) => {
				selectAlbumCoverSuggestion.mockResolvedValue(coveredAlbum());
				pressEditorButton(target, 'Use');
			}
		},
		{
			way: 'Upload',
			leave: (target: HTMLElement) => {
				uploadAlbumCover.mockResolvedValue(coveredAlbum(UPLOADED));
				uploadCoverFile(target);
			}
		}
	])('a suggestion asked for before $way is stopped when its answer arrives', async ({ leave }) => {
		vi.stubGlobal('EventSource', FakeJobEventSource);
		fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions(ONE_SUGGESTION));
		const asking = deferred<JobItem>();
		createAlbumCoverSuggestions.mockReturnValue(asking.promise);
		const target = await renderDetail();
		await openCoverEditing(target);
		await vi.waitFor(() => expect(shownImage(target)).toBe('/suggestion-one.png'));
		await askForAnotherSuggestion(target);

		await leave(target);
		await editingClosed(target);
		expect(cancelJob).not.toHaveBeenCalled();
		asking.resolve(coverJob());

		await vi.waitFor(() => expect(cancelJob).toHaveBeenCalledWith('cover-job'));
		await vi.waitFor(() => expect(discardAlbumCoverSuggestions).toHaveBeenCalledTimes(2));
		expect(discardAlbumCoverSuggestions.mock.calls).toEqual([
			['a-local', { suggestionIds: ['one'], jobIds: [] }],
			['a-local', { suggestionIds: [], jobIds: ['cover-job'] }]
		]);
		expect(get(activeJobs)).toEqual([]);
	});

	it('a run whose answer arrives while Use saves is stopped once the cover is saved', async () => {
		vi.stubGlobal('EventSource', FakeJobEventSource);
		fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions(ONE_SUGGESTION));
		const asking = deferred<JobItem>();
		createAlbumCoverSuggestions.mockReturnValue(asking.promise);
		const saving = deferred<AlbumItem>();
		selectAlbumCoverSuggestion.mockReturnValue(saving.promise);
		const target = await renderDetail();
		await openCoverEditing(target);
		await vi.waitFor(() => expect(shownImage(target)).toBe('/suggestion-one.png'));
		await askForAnotherSuggestion(target);

		pressEditorButton(target, 'Use');
		serverRunsUntilCancelled(ONE_SUGGESTION);
		asking.resolve(coverJob());
		await vi.waitFor(() =>
			expect(get(activeJobs).map((active) => active.job.id)).toEqual(['cover-job'])
		);
		expect(cancelJob).not.toHaveBeenCalled();
		saving.resolve(coveredAlbum());

		await vi.waitFor(() => expect(cancelJob).toHaveBeenCalledWith('cover-job'));
		await vi.waitFor(() => expect(discardAlbumCoverSuggestions).toHaveBeenCalledTimes(1));
		expect(discardAlbumCoverSuggestions.mock.calls).toEqual([
			['a-local', { suggestionIds: ['one'], jobIds: ['cover-job'] }]
		]);
	});

	it.each([
		{
			outcome: 'saved',
			editorCloses: true,
			settle: (saving: ReturnType<typeof deferred<AlbumItem>>) => saving.resolve(coveredAlbum())
		},
		{
			outcome: 'failed',
			editorCloses: false,
			settle: (saving: ReturnType<typeof deferred<AlbumItem>>) =>
				saving.reject(serverRefusal('Could not save'))
		}
	])(
		'the editor takes no other action while Use saves and takes them again once the save $outcome',
		async ({ settle, editorCloses }) => {
			vi.stubGlobal('EventSource', FakeJobEventSource);
			albumList.set([coveredAlbum()]);
			fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions(ONE_SUGGESTION));
			const saving = deferred<AlbumItem>();
			selectAlbumCoverSuggestion.mockReturnValue(saving.promise);
			const target = await renderDetail();
			await openCoverEditing(target);
			await vi.waitFor(() => expect(shownImage(target)).toBe('/suggestion-one.png'));
			const suggestAnother = () =>
				getByRoleButton(requireElement(target, '.cover-editor'), 'Suggest another');
			await vi.waitFor(() => expect(suggestAnother().disabled).toBe(false));
			const actions = ['Upload', 'Remove', 'Suggest another'].map(
				(name) => () => getByRoleButton(requireElement(target, '.cover-editor'), name)
			);

			pressEditorButton(target, 'Use');
			await vi.waitFor(() => expect(selectAlbumCoverSuggestion).toHaveBeenCalledTimes(1));
			for (const action of actions) {
				expect(action().disabled).toBe(true);
				action().click();
			}
			await tick();
			expect(createAlbumCoverSuggestions).not.toHaveBeenCalled();
			expect(deleteAlbumCover).not.toHaveBeenCalled();
			expect(uploadAlbumCover).not.toHaveBeenCalled();

			settle(saving);
			if (editorCloses) {
				await editingClosed(target);
				await openCoverEditing(target);
			}
			for (const action of actions) await vi.waitFor(() => expect(action().disabled).toBe(false));
		}
	);

	it.each([
		{
			way: 'Escape',
			leave: () =>
				document.body.dispatchEvent(
					new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
				)
		},
		{ way: 'another album', leave: () => selectedAlbumId.set('a-other') }
	])(
		'a suggestion asked for before $way is followed when its answer arrives',
		async ({ leave }) => {
			vi.stubGlobal('EventSource', FakeJobEventSource);
			albumList.set([
				album({ id: 'a-local', title: 'Night Drive' }),
				album({ id: 'a-other', title: 'Other Night' })
			]);
			const asking = deferred<JobItem>();
			createAlbumCoverSuggestions.mockReturnValue(asking.promise);
			const stopListening = listenForGlobalEscape();
			const target = await renderDetail();
			await openCoverEditing(target);
			await pressSuggestOnceLoaded(target);
			await vi.waitFor(() => expect(createAlbumCoverSuggestions).toHaveBeenCalledWith('a-local'));

			await leave();
			await editingClosed(target);
			asking.resolve(coverJob());
			await vi.waitFor(() => expect(get(activeJobs)).toHaveLength(1));
			stopListening();

			expect(cancelJob).not.toHaveBeenCalled();
			expect(discardAlbumCoverSuggestions).not.toHaveBeenCalled();
		}
	);

	it('Upload discards the suggestions of the album it started on once another album is open', async () => {
		albumList.set([
			album({ id: 'a-local', title: 'Night Drive' }),
			album({ id: 'a-other', title: 'Other Night' })
		]);
		fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions(ONE_SUGGESTION));
		const uploading = deferred<ReturnType<typeof coveredAlbum>>();
		uploadAlbumCover.mockReturnValue(uploading.promise);
		const target = await renderDetail();
		await openCoverEditing(target);
		await vi.waitFor(() => expect(shownImage(target)).toBe('/suggestion-one.png'));
		uploadCoverFile(target);
		await vi.waitFor(() =>
			expect(uploadAlbumCover).toHaveBeenCalledWith('a-local', expect.any(File))
		);

		selectedAlbumId.set('a-other');
		uploading.resolve(coveredAlbum(UPLOADED));

		await vi.waitFor(() =>
			expect(discardAlbumCoverSuggestions).toHaveBeenCalledWith('a-local', {
				suggestionIds: ['one'],
				jobIds: []
			})
		);
		expect(discardAlbumCoverSuggestions).toHaveBeenCalledTimes(1);
	});

	it('× that cannot stop the run keeps the editor open and the run followed', async () => {
		vi.stubGlobal('EventSource', FakeJobEventSource);
		cancelJob.mockRejectedValue(serverRefusal('Could not stop'));
		const target = await renderDetail();
		await openEditorWithRunningSuggestion(target, ONE_SUGGESTION);

		pressEditorButton(target, 'Close cover editing');

		await vi.waitFor(() => expect(addToast).toHaveBeenCalledWith('Could not stop', 'error'));
		expect(editor(target)).not.toBeNull();
		expect(discardAlbumCoverSuggestions).not.toHaveBeenCalled();
		expect(get(activeJobs).map((active) => active.job.id)).toEqual(['cover-job']);
	});

	it('a failed discard is shown and the editor rereads what the server still has', async () => {
		fetchAlbumCoverSuggestions
			.mockResolvedValueOnce(coverSuggestions(ONE_SUGGESTION))
			.mockResolvedValue(coverSuggestions());
		discardAlbumCoverSuggestions.mockRejectedValue(serverRefusal('Could not discard suggestions'));
		const target = await renderDetail();
		await openCoverEditing(target);
		await vi.waitFor(() => expect(shownImage(target)).toBe('/suggestion-one.png'));

		pressEditorButton(target, 'Close cover editing');

		await vi.waitFor(() =>
			expect(addToast).toHaveBeenCalledWith('Could not discard suggestions', 'error')
		);
		await vi.waitFor(() => expect(shownImage(target)).toBeNull());
		expect(fetchAlbumCoverSuggestions).toHaveBeenCalledTimes(2);
		expect(editor(target)).not.toBeNull();
	});

	it('a failed Use save keeps the run, the suggestions and the editor, and says why', async () => {
		vi.stubGlobal('EventSource', FakeJobEventSource);
		selectAlbumCoverSuggestion.mockRejectedValue(serverRefusal('Could not save'));
		const target = await renderDetail();
		await openEditorWithRunningSuggestion(target, ONE_SUGGESTION);

		pressEditorButton(target, 'Previous suggestion');
		await vi.waitFor(() => expect(shownImage(target)).toBe('/suggestion-one.png'));
		pressEditorButton(target, 'Use');

		await vi.waitFor(() => expect(addToast).toHaveBeenCalledWith('Could not save', 'error'));
		expect(selectAlbumCoverSuggestion).toHaveBeenCalledWith('a-local', { suggestion_id: 'one' });
		expect(editor(target)).not.toBeNull();
		expect(shownImage(target)).toBe('/suggestion-one.png');
		expect(cancelJob).not.toHaveBeenCalled();
		expect(discardAlbumCoverSuggestions).not.toHaveBeenCalled();
		expect(get(activeJobs).map((active) => active.job.id)).toEqual(['cover-job']);
	});

	it.each([
		{
			what: 'a failed Upload',
			act: (target: HTMLElement) => {
				uploadAlbumCover.mockRejectedValue(serverRefusal('Cover must be an image'));
				uploadCoverFile(target);
				return vi.waitFor(() =>
					expect(addToast).toHaveBeenCalledWith('Cover must be an image', 'error')
				);
			}
		},
		{
			what: 'a cancelled Upload picker',
			act: async (target: HTMLElement) => {
				const input = requireElement<HTMLInputElement>(target, '.cover-file-input');
				vi.spyOn(input, 'click').mockImplementation(() => undefined);
				pressEditorButton(target, 'Upload');
				Object.defineProperty(input, 'files', { configurable: true, value: [] });
				input.dispatchEvent(new Event('change', { bubbles: true }));
				await tick();
				expect(uploadAlbumCover).not.toHaveBeenCalled();
			}
		}
	])('$what stops nothing and discards nothing', async ({ act }) => {
		vi.stubGlobal('EventSource', FakeJobEventSource);
		const target = await renderDetail();
		await openEditorWithRunningSuggestion(target, ONE_SUGGESTION);

		await act(target);

		expect(editor(target)).not.toBeNull();
		expect(cancelJob).not.toHaveBeenCalled();
		expect(discardAlbumCoverSuggestions).not.toHaveBeenCalled();
		expect(get(activeJobs).map((active) => active.job.id)).toEqual(['cover-job']);
	});

	it('× stops the running suggestion before it discards, so nothing lands afterwards', async () => {
		fetchAlbumCoverSuggestions.mockResolvedValue(
			coverSuggestions({ ...ONE_SUGGESTION, job: coverJob({ status: 'running' }) })
		);
		const target = await renderDetail();
		await openCoverEditing(target);
		await vi.waitFor(() =>
			expect(target.querySelector('.cover-stage [role="status"]')).not.toBeNull()
		);

		pressEditorButton(target, 'Close cover editing');

		await editingClosed(target);
		expect(cancelJob.mock.invocationCallOrder[0]).toBeLessThan(
			discardAlbumCoverSuggestions.mock.invocationCallOrder[0]
		);
	});

	it('× stops the run once when the suggestions still load as it stops', async () => {
		vi.stubGlobal('EventSource', FakeJobEventSource);
		const loadAfterAsking = deferred<CoverSuggestionsResponse>();
		fetchAlbumCoverSuggestions
			.mockResolvedValueOnce(coverSuggestions())
			.mockReturnValueOnce(loadAfterAsking.promise)
			.mockReturnValue(deferred<CoverSuggestionsResponse>().promise);
		createAlbumCoverSuggestions.mockResolvedValue(coverJob());
		const stopping = deferred<JobItem>();
		cancelJob.mockReturnValue(stopping.promise);
		const target = await renderDetail();
		await openCoverEditing(target);
		await pressSuggestOnceLoaded(target);
		await reachSuggestionsLoads(2);

		pressEditorButton(target, 'Close cover editing');
		await vi.waitFor(() => expect(cancelJob).toHaveBeenCalledWith('cover-job'));
		loadAfterAsking.resolve(coverSuggestions({ job: coverJob({ status: 'running' }) }));
		await tick();
		stopping.resolve(coverJob({ status: 'cancelled' }));

		await editingClosed(target);
		await new Promise((settled) => setTimeout(settled, 0));
		expect(cancelJob).toHaveBeenCalledTimes(1);
		expect(discardAlbumCoverSuggestions).toHaveBeenCalledTimes(1);
		expect(get(activeJobs)).toEqual([]);
	});

	it('× while the first suggestion is still being asked for stops the run it starts', async () => {
		const suggestionJob = deferred<JobItem>();
		createAlbumCoverSuggestions.mockReturnValue(suggestionJob.promise);
		const target = await renderDetail();
		await openCoverEditing(target);
		await pressSuggestOnceLoaded(target);
		await vi.waitFor(() => expect(createAlbumCoverSuggestions).toHaveBeenCalledWith('a-local'));

		pressEditorButton(target, 'Close cover editing');
		await editingClosed(target);
		expect(cancelJob).not.toHaveBeenCalled();
		suggestionJob.resolve(coverJob());

		await vi.waitFor(() => expect(cancelJob).toHaveBeenCalledWith('cover-job'));
		expect(get(activeJobs)).toEqual([]);
	});

	it('a suggestion answered late after × discards only its own, never the one asked for since', async () => {
		vi.stubGlobal('EventSource', FakeJobEventSource);
		fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions(ONE_SUGGESTION));
		const firstAsk = deferred<JobItem>();
		createAlbumCoverSuggestions
			.mockReturnValueOnce(firstAsk.promise)
			.mockResolvedValue(coverJob({ id: 'second-job' }));
		const target = await renderDetail();
		await openCoverEditing(target);
		await vi.waitFor(() => expect(shownImage(target)).toBe('/suggestion-one.png'));
		await askForAnotherSuggestion(target);
		pressEditorButton(target, 'Close cover editing');
		await editingClosed(target);
		discardAlbumCoverSuggestions.mockClear();

		await openCoverEditing(target);
		await askForAnotherSuggestion(target);
		await vi.waitFor(() => expect(createAlbumCoverSuggestions).toHaveBeenCalledTimes(2));
		firstAsk.resolve(coverJob({ id: 'first-job' }));

		await vi.waitFor(() => expect(cancelJob).toHaveBeenCalledWith('first-job'));
		await vi.waitFor(() =>
			expect(get(activeJobs).map((active) => active.job.id)).toEqual(['second-job'])
		);
		await vi.waitFor(() =>
			expect(discardAlbumCoverSuggestions.mock.calls).toEqual([
				['a-local', { suggestionIds: [], jobIds: ['first-job'] }]
			])
		);
		expect(cancelJob).not.toHaveBeenCalledWith('second-job');
	});

	it('a load from before × that answers after the next Suggest follows that run', async () => {
		vi.stubGlobal('EventSource', FakeJobEventSource);
		const staleLoad = deferred<CoverSuggestionsResponse>();
		fetchAlbumCoverSuggestions
			.mockReturnValueOnce(staleLoad.promise)
			.mockResolvedValue(coverSuggestions());
		createAlbumCoverSuggestions.mockResolvedValue(coverJob({ id: 'later-job' }));
		const target = await renderDetail();
		await openCoverEditing(target);
		await reachSuggestionsLoads(1);
		pressEditorButton(target, 'Close cover editing');
		await editingClosed(target);
		await openCoverEditing(target);
		await pressSuggestOnceLoaded(target);
		await vi.waitFor(() => expect(createAlbumCoverSuggestions).toHaveBeenCalledWith('a-local'));

		staleLoad.resolve(coverSuggestions({ job: coverJob({ id: 'later-job', status: 'running' }) }));
		await new Promise((settled) => setTimeout(settled, 0));

		expect(cancelJob).not.toHaveBeenCalled();
		expect(discardAlbumCoverSuggestions).not.toHaveBeenCalled();
		expect(get(activeJobs).map((active) => active.job.id)).toEqual(['later-job']);
	});

	const exitsBeforeTheFirstLoad = [
		{
			way: '×',
			leave: (target: HTMLElement) => pressEditorButton(target, 'Close cover editing')
		},
		{
			way: 'Upload',
			leave: (target: HTMLElement) => {
				uploadAlbumCover.mockResolvedValue(coveredAlbum(UPLOADED));
				uploadCoverFile(target);
			}
		}
	];
	const firstLoadReports = [
		{
			report: 'a running run',
			answer: coverSuggestions({ job: coverJob({ status: 'running' }) }),
			followed: ['cover-job']
		},
		{
			report: 'a run that completed with its suggestion',
			answer: coverSuggestions({ ...ONE_SUGGESTION, job: coverJob({ status: 'completed' }) }),
			followed: []
		}
	];
	it.each(
		exitsBeforeTheFirstLoad.flatMap((exit) => firstLoadReports.map((r) => ({ ...exit, ...r })))
	)(
		'$report the first load answers after $way is neither stopped nor discarded',
		async ({ leave, answer, followed }) => {
			vi.stubGlobal('EventSource', FakeJobEventSource);
			const firstLoad = deferred<CoverSuggestionsResponse>();
			fetchAlbumCoverSuggestions.mockReturnValue(firstLoad.promise);
			const target = await renderDetail();
			await openCoverEditing(target);
			await reachSuggestionsLoads(1);

			leave(target);
			await editingClosed(target);
			firstLoad.resolve(answer);
			await new Promise((settled) => setTimeout(settled, 0));

			expect(cancelJob).not.toHaveBeenCalled();
			expect(discardAlbumCoverSuggestions).not.toHaveBeenCalled();
			expect(get(activeJobs).map((active) => active.job.id)).toEqual(followed);
		}
	);

	it('Suggest stays disabled after a Remove finishes first and the editor is opened again during a Use save', async () => {
		albumList.set([coveredAlbum()]);
		fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions(ONE_SUGGESTION));
		const removal = deferred<ReturnType<typeof coveredAlbum>>();
		const useSave = deferred<ReturnType<typeof coveredAlbum>>();
		deleteAlbumCover.mockReturnValue(removal.promise);
		selectAlbumCoverSuggestion.mockReturnValue(useSave.promise);
		const target = await renderDetail();
		await openCoverEditing(target);
		await vi.waitFor(() => expect(shownImage(target)).toBe('/suggestion-one.png'));

		pressEditorButton(target, 'Remove');
		pressEditorButton(target, 'Use');
		removal.resolve({ ...coveredAlbum(), cover: null });
		await editingClosed(target);
		await openCoverEditing(target);

		await tick();
		expect(
			getByRoleButton(requireElement(target, '.cover-editor'), 'Suggest another').disabled
		).toBe(true);
		useSave.resolve(coveredAlbum(UPLOADED));
		await editingClosed(target);
	});

	it('Swiping to another suggestion during a Use save shows nothing else', async () => {
		fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions(THREE_SUGGESTIONS));
		const useSave = deferred<ReturnType<typeof coveredAlbum>>();
		selectAlbumCoverSuggestion.mockReturnValue(useSave.promise);
		const target = await renderDetail();
		await openCoverEditing(target);
		await vi.waitFor(() => expect(shownImage(target)).toBe('/suggestion-three.png'));
		pressEditorButton(target, 'Use');

		for (const [from, to] of [
			[200, 100],
			[100, 200]
		]) {
			const stage = requireElement(target, '.cover-stage');
			const at = (clientX: number) => ({ bubbles: true, pointerId: 1, clientX, clientY: 100 });
			stage.dispatchEvent(new PointerEvent('pointerdown', at(from)));
			stage.dispatchEvent(new PointerEvent('pointerup', at(to)));
		}
		await tick();

		expect(shownImage(target)).toBe('/suggestion-three.png');
		useSave.resolve(coveredAlbum(UPLOADED));
		await editingClosed(target);
	});

	it('Upload pressed before the first read answered stops the run that read finds', async () => {
		vi.stubGlobal('EventSource', FakeJobEventSource);
		const firstRead = deferred<CoverSuggestionsResponse>();
		const uploading = deferred<ReturnType<typeof coveredAlbum>>();
		fetchAlbumCoverSuggestions.mockReturnValue(firstRead.promise);
		uploadAlbumCover.mockReturnValue(uploading.promise);
		const target = await renderDetail();
		await openCoverEditing(target);

		uploadCoverFile(target);
		await vi.waitFor(() => expect(uploadAlbumCover).toHaveBeenCalledOnce());
		firstRead.resolve(coverSuggestions({ job: coverJob({ status: 'running' }) }));
		await vi.waitFor(() => expect(get(activeJobs)).toHaveLength(1));
		uploading.resolve(coveredAlbum(UPLOADED));

		await vi.waitFor(() => expect(cancelJob).toHaveBeenCalledWith('cover-job'));
		expect(discardAlbumCoverSuggestions).toHaveBeenCalledWith('a-local', {
			suggestionIds: [],
			jobIds: ['cover-job']
		});
	});

	it('closing the editor reads the cover state once more and stops nothing', async () => {
		fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions());
		const target = await renderDetail();
		await openCoverEditing(target);
		await reachSuggestionsLoads(1);

		pressEditorButton(target, 'Close cover editing');
		await editingClosed(target);

		await reachSuggestionsLoads(2);
		expect(cancelJob).not.toHaveBeenCalled();
		expect(discardAlbumCoverSuggestions).not.toHaveBeenCalled();
	});
});
