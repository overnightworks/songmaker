import { makeAlbum as album, makeSong as song } from '#lib/test-utils/factories.ts';
import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { CoverSuggestionsResponse } from '#lib/api/types.ts';
import { ApiError } from '#lib/api/fetch.ts';
import { lostNetwork, serverRefusal } from '#lib/test-utils/network.ts';
import { accessibleName } from '#lib/test-utils/accessible-name.ts';
import { describeBackClosesOverlay } from '#lib/test-utils/library-history.ts';
import {
	reportResourceStreamReachable,
	resetConnectivityForTests
} from '#lib/stores/connectivity.ts';
import { words } from '#lib/words/en.ts';
import { listenForGlobalEscape } from '#lib/test-utils/global-escape.ts';
import { dropLayersFrom, stackedLayers } from '#lib/stores/layers.ts';
import { createComponentMount, requireElement } from './shell/rail-test-fixtures';
import { albumList, resetLibraryDataForTests, songList } from '#lib/stores/libraryData.ts';
import { selectedAlbumId } from '#lib/stores/player.ts';
import { activeJobs } from '#lib/stores/jobs.ts';
import {
	FakeJobEventSource,
	PAST_EVERY_RELOAD_MS,
	reachSuggestionsLoads,
	coverSuggestions,
	coverJob,
	ONE_SUGGESTION,
	THREE_SUGGESTIONS,
	THREE_SHOWN,
	UPLOADED,
	coveredAlbum,
	editor,
	openCoverEditing,
	editingClosed,
	countLine,
	stageAnnouncement,
	stageText,
	shownImage,
	pressSuggestOnceLoaded,
	editorButton,
	editorButtonNames,
	pressEditorButton,
	uploadCoverFile,
	afterPageRead
} from '#lib/test-utils/album-cover-editor.ts';
import { deferred } from '#lib/test-utils/deferred.ts';

const createAlbumCoverSuggestions = vi.fn();
const fetchAlbumCoverSuggestions = vi.fn();
const selectAlbumCoverSuggestion = vi.fn();
const discardAlbumCoverSuggestions = vi.fn();
const deleteAlbumCover = vi.fn();
const uploadAlbumCover = vi.fn();
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
	selectAlbumCoverSuggestion: (...args: unknown[]) => selectAlbumCoverSuggestion(...args),
	discardAlbumCoverSuggestions: (...args: unknown[]) => discardAlbumCoverSuggestions(...args)
}));
vi.mock('#lib/api/jobs.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/jobs.ts')>()),
	cancelJob: (...args: unknown[]) => cancelJob(...args)
}));
vi.mock('#lib/api/client.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/client.ts')>()),
	deleteAlbumCover: (...args: unknown[]) => deleteAlbumCover(...args),
	uploadAlbumCover: (...args: unknown[]) => uploadAlbumCover(...args)
}));
vi.mock('#lib/stores/toast.ts', () => ({
	addToast: vi.fn(),
	addUndoToast: vi.fn()
}));

import AlbumDetailView from './AlbumDetailView.svelte';
import { addToast } from '#lib/stores/toast.ts';

const { render: renderDetail, cleanup } = createComponentMount(AlbumDetailView);

function failureAlert(target: HTMLElement): HTMLElement | null {
	return target.querySelector('.cover-editor [role="alert"]');
}

function stageLabel(target: HTMLElement): string | null {
	return requireElement(target, '.cover-stage').getAttribute('aria-label');
}

function editorActions(target: HTMLElement): string[] {
	return Array.from(target.querySelectorAll('.cover-actions button')).map(accessibleName);
}

function swipe(target: HTMLElement, travel: number): void {
	const stage = requireElement(target, '.cover-stage');
	stage.dispatchEvent(
		new PointerEvent('pointerdown', { bubbles: true, pointerId: 1, clientX: 200, clientY: 100 })
	);
	stage.dispatchEvent(
		new PointerEvent('pointerup', {
			bubbles: true,
			pointerId: 1,
			clientX: 200 + travel,
			clientY: 104
		})
	);
}
const renderAfterPageRead = () => afterPageRead(renderDetail, fetchAlbumCoverSuggestions);

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

describe('AlbumCoverEditor in the album header', () => {
	it('keeps covers off the page until the dashed Add cover place is tapped', async () => {
		const target = await renderDetail();

		const place = requireElement<HTMLButtonElement>(target, 'button.header-cover');
		expect(accessibleName(place)).toBe(words['albumCover.add']);
		expect(place.textContent).toContain(words['albumCover.add']);
		expect(editor(target)).toBeNull();
		expect(target.textContent).not.toContain('Choose a cover');
		expect(createAlbumCoverSuggestions).not.toHaveBeenCalled();
	});

	it('tapping Add cover grows the cover in place with Upload · Suggest and makes nothing', async () => {
		const target = await renderDetail();

		await openCoverEditing(target);
		await vi.waitFor(() => expect(countLine(target)).toBe(''));
		expect(editorActions(target)).toEqual(
			editorButtonNames('albumCover.upload', 'albumCover.suggest', 'albumCover.editingClose')
		);
		expect(stageLabel(target)).toBeNull();

		pressEditorButton(target, 'albumCover.editingClose');
		await editingClosed(target);
		await openCoverEditing(target);
		await vi.waitFor(() => expect(countLine(target)).toBe(''));

		expect(createAlbumCoverSuggestions).not.toHaveBeenCalled();
		expect(discardAlbumCoverSuggestions).not.toHaveBeenCalled();
	});

	it('Suggest makes the first suggestion in place and then reads Suggest another', async () => {
		vi.stubGlobal('EventSource', FakeJobEventSource);
		createAlbumCoverSuggestions.mockResolvedValue(coverJob());
		const target = await renderAfterPageRead();
		fetchAlbumCoverSuggestions
			.mockResolvedValueOnce(coverSuggestions())
			.mockResolvedValueOnce(
				coverSuggestions({ job: coverJob({ status: 'running', progress: 0.4 }) })
			)
			.mockResolvedValue(coverSuggestions(ONE_SUGGESTION));
		await openCoverEditing(target);

		await pressSuggestOnceLoaded(target);

		await vi.waitFor(() => expect(createAlbumCoverSuggestions).toHaveBeenCalledWith('a-local'));
		await vi.waitFor(() =>
			expect(target.querySelector('.cover-stage [role="status"]')).not.toBeNull()
		);
		await vi.waitFor(() => expect(FakeJobEventSource.sources).toHaveLength(1));
		FakeJobEventSource.sources[0].emit(coverJob({ status: 'completed', progress: 1 }));

		await vi.waitFor(() => expect(shownImage(target)).toBe('/suggestion-one.png'));
		expect(countLine(target)).toBe('1 / 1');
		expect(editorActions(target)).toEqual(
			editorButtonNames(
				'albumCover.upload',
				'albumCover.suggestAnother',
				'albumCover.use',
				'albumCover.editingClose'
			)
		);
		expect(createAlbumCoverSuggestions).toHaveBeenCalledTimes(1);
		expect(target.querySelector('.header-title')?.textContent).toContain('Night Drive');
		expect(target.querySelector('.play-circle')).not.toBeNull();
		expect(target.querySelector('.song-row')).not.toBeNull();
	});

	it.each([
		{ detail: 'Too many requests, slow down', shown: 'Too many requests, slow down' },
		{ detail: '', shown: words['albumCover.throttledFallback'] }
	])(
		'a throttled ask shows $shown beside the cover, never red, and keeps Suggest open',
		async ({ detail, shown }) => {
			createAlbumCoverSuggestions.mockRejectedValue(
				new ApiError(429, detail, '/api/albums/a-local')
			);
			const target = await renderAfterPageRead();
			await openCoverEditing(target);

			await pressSuggestOnceLoaded(target);
			await vi.waitFor(() => expect(countLine(target)).toBe(shown));

			expect(fetchAlbumCoverSuggestions).toHaveBeenCalledTimes(2);
			expect(failureAlert(target)).toBeNull();
			expect(addToast).not.toHaveBeenCalled();
			expect(editorButton(target, 'albumCover.suggest').disabled).toBe(false);
		}
	);

	it('keeps Suggest open however many suggestions the album has made', async () => {
		const made = Array.from({ length: 11 }, (_, index) => ({
			id: `made-${index}`,
			url: `/made-${index}.png`
		}));
		fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions({ suggestions: made }));
		const target = await renderDetail();

		await openCoverEditing(target);

		await vi.waitFor(() => expect(countLine(target)).toBe('11 / 11'));
		expect(editorButton(target, 'albumCover.suggestAnother').disabled).toBe(false);
	});

	it.each([
		{
			before: 'no suggestion',
			made: [],
			counted: '',
			shown: '/cover-detail.jpg',
			label: null
		},
		{
			before: 'two suggestions',
			made: THREE_SUGGESTIONS.suggestions.slice(0, 2),
			counted: '2 / 2',
			shown: '/suggestion-two.png',
			label: 'Cover suggestion 2 of 2'
		}
	])(
		'a failed suggestion after $before shows its failure on its own, not as a slot',
		async ({ made, counted, shown, label }) => {
			albumList.set([coveredAlbum()]);
			fetchAlbumCoverSuggestions.mockResolvedValue(
				coverSuggestions({
					suggestions: made,
					job: coverJob({ status: 'failed', error: 'Cover suggestion could not be generated' })
				})
			);
			const target = await renderDetail();

			await openCoverEditing(target);
			await vi.waitFor(() =>
				expect(failureAlert(target)?.textContent).toContain(words['coverProblem.unavailable'])
			);
			expect(target.textContent).not.toContain('Cover suggestion could not be generated');

			expect(countLine(target)).toContain(counted);
			expect(shownImage(target)).toBe(shown);
			expect(stageLabel(target)).toBe(label);
			expect(target.querySelector('.cover-stage [role="alert"]')).toBeNull();
		}
	);

	it('opens a cover already set with a quiet Remove and makes nothing by itself', async () => {
		albumList.set([coveredAlbum()]);
		const target = await renderDetail();

		expect(accessibleName(requireElement(target, 'button.header-cover'))).toBe(
			words['albumCover.edit']
		);
		await openCoverEditing(target);
		await vi.waitFor(() => expect(countLine(target)).toBe(''));

		expect(shownImage(target)).toBe('/cover-detail.jpg');
		expect(editorActions(target)).toEqual(
			editorButtonNames(
				'albumCover.upload',
				'albumCover.suggest',
				'albumCover.remove',
				'albumCover.editingClose'
			)
		);
		expect(stageLabel(target)).toBeNull();
		expect(createAlbumCoverSuggestions).not.toHaveBeenCalled();
	});

	it('with a cover set and a suggestion made the row ends Use · Remove · ×', async () => {
		albumList.set([coveredAlbum()]);
		fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions(ONE_SUGGESTION));
		const target = await renderDetail();

		await openCoverEditing(target);
		await vi.waitFor(() => expect(shownImage(target)).toBe('/suggestion-one.png'));

		expect(editorActions(target)).toEqual(
			editorButtonNames(
				'albumCover.upload',
				'albumCover.suggestAnother',
				'albumCover.use',
				'albumCover.remove',
				'albumCover.editingClose'
			)
		);
	});

	it('browses the suggestions made so far with ‹ › and a swipe on the cover', async () => {
		fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions(THREE_SUGGESTIONS));
		const target = await renderDetail();
		await openCoverEditing(target);

		await vi.waitFor(() => expect(countLine(target)).toBe('3 / 3'));
		expect(shownImage(target)).toBe('/suggestion-three.png');
		expect(requireElement(target, '.cover-stage').getAttribute('aria-label')).toBe(
			'Cover suggestion 3 of 3'
		);

		pressEditorButton(target, 'albumCover.previousSuggestion');
		await tick();
		expect(countLine(target)).toBe('2 / 3');
		expect(shownImage(target)).toBe('/suggestion-two.png');

		swipe(target, 60);
		await tick();
		expect(shownImage(target)).toBe('/suggestion-one.png');
		expect(editorButton(target, 'albumCover.previousSuggestion').disabled).toBe(true);

		swipe(target, 10);
		await tick();
		expect(shownImage(target)).toBe('/suggestion-one.png');

		swipe(target, -60);
		await tick();
		pressEditorButton(target, 'albumCover.nextSuggestion');
		await tick();
		expect(countLine(target)).toBe('3 / 3');
		expect(createAlbumCoverSuggestions).not.toHaveBeenCalled();
	});

	it('Suggest another keeps every earlier suggestion and shows the new one once it lands', async () => {
		vi.stubGlobal('EventSource', FakeJobEventSource);
		const two = { suggestions: THREE_SUGGESTIONS.suggestions.slice(0, 2) };
		createAlbumCoverSuggestions.mockResolvedValue(coverJob());
		const target = await renderAfterPageRead();
		fetchAlbumCoverSuggestions
			.mockResolvedValueOnce(coverSuggestions(two))
			.mockResolvedValueOnce(coverSuggestions({ ...two, job: coverJob({ status: 'running' }) }))
			.mockResolvedValue(coverSuggestions(THREE_SUGGESTIONS));
		await openCoverEditing(target);
		await vi.waitFor(() => expect(countLine(target)).toBe('2 / 2'));

		pressEditorButton(target, 'albumCover.suggestAnother');

		await vi.waitFor(() =>
			expect(target.querySelector('.cover-stage [role="status"]')).not.toBeNull()
		);
		expect(stageLabel(target)).toBeNull();
		expect(discardAlbumCoverSuggestions).not.toHaveBeenCalled();
		FakeJobEventSource.sources[0].emit(coverJob({ status: 'completed', progress: 1 }));

		await vi.waitFor(() => expect(shownImage(target)).toBe('/suggestion-three.png'));
		pressEditorButton(target, 'albumCover.previousSuggestion');
		await tick();
		expect(shownImage(target)).toBe('/suggestion-two.png');
	});

	it('Use sets the shown suggestion as the cover, discards the rest and closes the editor', async () => {
		fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions(THREE_SUGGESTIONS));
		selectAlbumCoverSuggestion.mockResolvedValue(coveredAlbum());
		const target = await renderDetail();
		await openCoverEditing(target);
		await vi.waitFor(() => expect(shownImage(target)).toBe('/suggestion-three.png'));
		pressEditorButton(target, 'albumCover.previousSuggestion');
		await tick();

		pressEditorButton(target, 'albumCover.use');

		await editingClosed(target);
		expect(selectAlbumCoverSuggestion).toHaveBeenCalledWith('a-local', { suggestion_id: 'two' });
		expect(discardAlbumCoverSuggestions).toHaveBeenCalledWith('a-local', THREE_SHOWN);
		expect(target.querySelector('.header-cover img')?.getAttribute('src')).toBe(
			'/cover-detail.jpg'
		);
	});

	it('Escape while Use saves closes nothing; the editor closes once the cover is saved', async () => {
		fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions(THREE_SUGGESTIONS));
		const saving = deferred<ReturnType<typeof coveredAlbum>>();
		selectAlbumCoverSuggestion.mockReturnValue(saving.promise);
		const target = await renderDetail();
		await openCoverEditing(target);
		await vi.waitFor(() => expect(shownImage(target)).toBe('/suggestion-three.png'));
		const levelUp = vi.fn();
		const stopListening = listenForGlobalEscape(levelUp);

		pressEditorButton(target, 'albumCover.use');
		await tick();
		document.body.dispatchEvent(
			new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
		);
		await tick();

		expect(editor(target)).not.toBeNull();
		expect(discardAlbumCoverSuggestions).not.toHaveBeenCalled();
		saving.resolve(coveredAlbum());
		await editingClosed(target);
		stopListening();
		expect(levelUp).not.toHaveBeenCalled();
	});

	it.each([
		{
			way: 'Escape',
			press: () =>
				document.body.dispatchEvent(
					new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
				)
		},
		{ way: 'Back', press: () => dropLayersFrom(stackedLayers().length - 1) },
		{
			way: '×',
			press: (target: HTMLElement) => pressEditorButton(target, 'albumCover.editingClose')
		}
	])('$way during an upload closes nothing until the cover is saved', async ({ press }) => {
		const uploading = deferred<ReturnType<typeof coveredAlbum>>();
		uploadAlbumCover.mockReturnValue(uploading.promise);
		const target = await renderDetail();
		await openCoverEditing(target);
		const stopListening = listenForGlobalEscape();

		uploadCoverFile(target);
		await vi.waitFor(() => expect(uploadAlbumCover).toHaveBeenCalledOnce());
		press(target);
		await tick();

		expect(editor(target)).not.toBeNull();
		uploading.resolve(coveredAlbum(UPLOADED));
		await editingClosed(target);
		stopListening();
	});

	it('× discards the unused suggestions and closes the editor', async () => {
		fetchAlbumCoverSuggestions.mockImplementation(async () =>
			coverSuggestions(discardAlbumCoverSuggestions.mock.calls.length ? {} : THREE_SUGGESTIONS)
		);
		const target = await renderDetail();
		await openCoverEditing(target);
		await vi.waitFor(() => expect(shownImage(target)).toBe('/suggestion-three.png'));

		pressEditorButton(target, 'albumCover.editingClose');

		await editingClosed(target);
		expect(discardAlbumCoverSuggestions).toHaveBeenCalledWith('a-local', THREE_SHOWN);
		expect(selectAlbumCoverSuggestion).not.toHaveBeenCalled();
		expect(cancelJob).not.toHaveBeenCalled();
		expect(accessibleName(requireElement(target, 'button.header-cover'))).toBe(
			words['albumCover.add']
		);
	});

	it('× while the suggestions still load closes the editor without making a suggestion', async () => {
		const firstLoad = deferred<CoverSuggestionsResponse>();
		const target = await renderAfterPageRead();
		fetchAlbumCoverSuggestions.mockReturnValueOnce(firstLoad.promise);
		await openCoverEditing(target);
		await reachSuggestionsLoads(fetchAlbumCoverSuggestions, 1);
		pressEditorButton(target, 'albumCover.editingClose');
		await editingClosed(target);
		firstLoad.resolve(coverSuggestions());
		await new Promise((settled) => setTimeout(settled, 0));

		expect(createAlbumCoverSuggestions).not.toHaveBeenCalled();
	});

	it.each([
		{
			action: 'albumCover.editingClose' as const,
			arrange: () =>
				discardAlbumCoverSuggestions.mockRejectedValue(
					serverRefusal('Could not discard suggestions')
				),
			toast: 'Could not discard suggestions'
		},
		{
			action: 'albumCover.use' as const,
			arrange: () => selectAlbumCoverSuggestion.mockRejectedValue(serverRefusal('Could not save')),
			toast: 'Could not save'
		},
		{
			action: 'albumCover.editingClose' as const,
			arrange: () => discardAlbumCoverSuggestions.mockRejectedValue(lostNetwork()),
			toast: words['albumCover.suggestionFailedFallback']
		},
		{
			action: 'albumCover.use' as const,
			arrange: () => selectAlbumCoverSuggestion.mockRejectedValue(lostNetwork()),
			toast: words['albumCover.suggestionFailedFallback']
		}
	])(
		'keeps the editor and its suggestions when $action fails, naming "$toast"',
		async ({ action, arrange, toast }) => {
			fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions(ONE_SUGGESTION));
			arrange();
			const target = await renderDetail();
			await openCoverEditing(target);
			await vi.waitFor(() => expect(shownImage(target)).toBe('/suggestion-one.png'));

			pressEditorButton(target, action);

			await vi.waitFor(() => expect(addToast).toHaveBeenCalledWith(toast, 'error'));
			expect(editor(target)).not.toBeNull();
			expect(shownImage(target)).toBe('/suggestion-one.png');
			expect(vi.mocked(addToast).mock.calls.flat()).not.toContain('Failed to fetch');
		}
	);

	it('Remove takes the cover off and closes the editor', async () => {
		albumList.set([coveredAlbum()]);
		deleteAlbumCover.mockResolvedValue(album({ id: 'a-local', title: 'Night Drive' }));
		const target = await renderDetail();
		await openCoverEditing(target);

		pressEditorButton(target, 'albumCover.remove');

		await editingClosed(target);
		expect(deleteAlbumCover).toHaveBeenCalledWith('a-local');
		expect(accessibleName(requireElement(target, 'button.header-cover'))).toBe(
			words['albumCover.add']
		);
	});

	it('another album closes the editor', async () => {
		albumList.set([coveredAlbum(), album({ id: 'a-other', title: 'Other Night' })]);
		const target = await renderDetail();
		await openCoverEditing(target);

		selectedAlbumId.set('a-other');

		await editingClosed(target);
		expect(target.querySelector('.header-title')?.textContent).toContain('Other Night');
	});

	it('shows the elapsed time only while the suggestion runs and names a run that hit its time limit unavailable', async () => {
		vi.stubGlobal('EventSource', FakeJobEventSource);
		const fortyTwoSecondsAgo = new Date(Date.now() - 42_000).toISOString();
		fetchAlbumCoverSuggestions
			.mockResolvedValueOnce(
				coverSuggestions({ job: coverJob({ status: 'running', started_at: fortyTwoSecondsAgo }) })
			)
			.mockResolvedValue(
				coverSuggestions({
					job: coverJob({
						status: 'failed',
						error: 'Cover suggestion could not be generated',
						error_type: 'timeout'
					})
				})
			);
		const target = await renderDetail();
		await openCoverEditing(target);

		await vi.waitFor(() => expect(stageText(target)).toMatch(/cover\s·\s0:4\d/));
		expect(target.querySelector('[role="progressbar"]')).toBeNull();
		expect(stageAnnouncement(target)).toBe(words['albumCover.suggesting']);
		await vi.waitFor(() => expect(FakeJobEventSource.sources).toHaveLength(1));
		FakeJobEventSource.sources[0].emit(
			coverJob({ status: 'failed', error: 'Cover suggestion could not be generated' })
		);

		await vi.waitFor(() =>
			expect(target.querySelector('[role="alert"]')?.textContent).toContain(
				words['coverProblem.unavailable']
			)
		);
		expect(target.textContent).not.toContain('Cover suggestion could not be generated');
		expect(target.querySelector('.cover-stage [role="status"]')).toBeNull();
		expect(target.querySelector('.suggestion-placeholder')).toBeNull();
		expect(createAlbumCoverSuggestions).not.toHaveBeenCalled();
	});

	it.each([
		{
			reread: 'follows the run that still goes',
			found: coverSuggestions({
				job: coverJob({ status: 'running', progress: 0.3 })
			}),
			shows: (target: HTMLElement) =>
				expect(target.querySelector('.cover-stage [role="status"]')).not.toBeNull()
		},
		{
			reread: 'shows the suggestion of a run that ended meanwhile',
			found: coverSuggestions(ONE_SUGGESTION),
			shows: (target: HTMLElement) => expect(shownImage(target)).toBe('/suggestion-one.png')
		}
	])(
		'a refusal because a suggestion already runs reads the list again and $reread, with no word of its own',
		async ({ found, shows }) => {
			vi.stubGlobal('EventSource', FakeJobEventSource);
			createAlbumCoverSuggestions.mockRejectedValue(
				new ApiError(409, 'Cover suggestions are already being generated', '/api/x')
			);
			const target = await renderAfterPageRead();
			fetchAlbumCoverSuggestions.mockResolvedValueOnce(coverSuggestions()).mockResolvedValue(found);
			await openCoverEditing(target);

			await pressSuggestOnceLoaded(target);

			await reachSuggestionsLoads(fetchAlbumCoverSuggestions, 2);
			shows(target);
			expect(failureAlert(target)).toBeNull();
			expect(target.textContent).not.toContain('already being');
		}
	);

	it.each([
		{
			result: 'its new image',
			found: coverSuggestions({
				...ONE_SUGGESTION,
				job: coverJob({ id: 'ended-run', status: 'completed', progress: 1 })
			}),
			shows: (target: HTMLElement) => {
				expect(shownImage(target)).toBe('/suggestion-one.png');
				expect(failureAlert(target)).toBeNull();
			}
		},
		{
			result: 'its failure line',
			found: coverSuggestions({
				job: coverJob({ id: 'ended-run', status: 'failed', error: 'The model ran out of memory' })
			}),
			shows: (target: HTMLElement) => {
				expect(failureAlert(target)?.textContent).toContain(words['coverProblem.unavailable']);
				expect(target.textContent).not.toContain('The model ran out of memory');
			}
		}
	])(
		"a refused ask whose run already ended shows that run's result: $result",
		async ({ found, shows }) => {
			createAlbumCoverSuggestions.mockRejectedValue(
				new ApiError(409, 'Cover suggestions are already being generated', '/api/x')
			);
			const target = await renderAfterPageRead();
			fetchAlbumCoverSuggestions.mockResolvedValueOnce(coverSuggestions()).mockResolvedValue(found);
			await openCoverEditing(target);

			await pressSuggestOnceLoaded(target);

			await reachSuggestionsLoads(fetchAlbumCoverSuggestions, 2);
			shows(target);
			expect(target.textContent).not.toContain('already being');
		}
	);

	it('hydrates a running cover job once and shows its suggestion after the streamed completion', async () => {
		vi.stubGlobal('EventSource', FakeJobEventSource);
		const target = await renderAfterPageRead();
		fetchAlbumCoverSuggestions
			.mockResolvedValueOnce(
				coverSuggestions({ job: coverJob({ status: 'running', progress: 0.5 }) })
			)
			.mockResolvedValueOnce(
				coverSuggestions({ suggestions: [{ id: 'finished', url: '/finished-suggestion.png' }] })
			);
		await openCoverEditing(target);

		await vi.waitFor(() => expect(FakeJobEventSource.sources).toHaveLength(1));
		expect(get(activeJobs)).toHaveLength(1);
		FakeJobEventSource.sources[0].emit(coverJob({ status: 'completed', progress: 1 }));

		await vi.waitFor(() => expect(shownImage(target)).toBe('/finished-suggestion.png'));
		expect(FakeJobEventSource.sources).toHaveLength(1);
		expect(createAlbumCoverSuggestions).not.toHaveBeenCalled();
	});

	it.each([
		{
			moment: 'loading the suggestions',
			arrange: () => fetchAlbumCoverSuggestions.mockRejectedValue(lostNetwork()),
			suggests: false
		},
		{
			moment: 'making the first suggestion',
			arrange: () => createAlbumCoverSuggestions.mockRejectedValue(lostNetwork()),
			suggests: true
		}
	])('keeps the editor quiet when $moment finds no network', async ({ arrange, suggests }) => {
		const target = await renderAfterPageRead();
		arrange();
		await openCoverEditing(target);
		await reachSuggestionsLoads(fetchAlbumCoverSuggestions, 1);
		if (suggests) {
			await pressSuggestOnceLoaded(target);
			await vi.waitFor(() => expect(createAlbumCoverSuggestions).toHaveBeenCalledTimes(1));
		}
		await tick();

		expect(editor(target)).not.toBeNull();
		expect(target.textContent).not.toContain('Failed to fetch');
		expect(target.querySelector('[role="alert"]')).toBeNull();
		expect(addToast).not.toHaveBeenCalled();
	});

	it.each(['failure before leaving', 'failure after leaving', 'success after leaving'])(
		'1160-F44-disposal: a left album page never reloads after %s',
		async (settlement) => {
			vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
			const pending = deferred<CoverSuggestionsResponse>();
			fetchAlbumCoverSuggestions.mockImplementation(() => pending.promise);
			await renderDetail();
			await reachSuggestionsLoads(fetchAlbumCoverSuggestions, 1);
			const settle = () =>
				settlement.startsWith('success')
					? pending.resolve(coverSuggestions())
					: pending.reject(lostNetwork());
			if (settlement === 'failure before leaving') {
				settle();
				await vi.advanceTimersByTimeAsync(0);
			}
			selectedAlbumId.set(null);
			await tick();
			if (settlement !== 'failure before leaving') settle();
			await vi.advanceTimersByTimeAsync(PAST_EVERY_RELOAD_MS);
			reportResourceStreamReachable(false);
			reportResourceStreamReachable(true);
			await tick();
			expect(fetchAlbumCoverSuggestions).toHaveBeenCalledTimes(1);
		}
	);
});

describeBackClosesOverlay({
	name: 'the cover editing',
	render: async () => {
		vi.stubGlobal('EventSource', FakeJobEventSource);
		albumList.set([coveredAlbum()]);
		fetchAlbumCoverSuggestions.mockResolvedValue(
			coverSuggestions({ ...ONE_SUGGESTION, job: coverJob({ status: 'running' }) })
		);
		return renderDetail();
	},
	open: async (target) => {
		await openCoverEditing(target);
		await vi.waitFor(() => expect(get(activeJobs)).toHaveLength(1));
	},
	isShown: (target) => editor(target) !== null,
	afterBack: () => {
		expect(cancelJob).not.toHaveBeenCalled();
		expect(discardAlbumCoverSuggestions).not.toHaveBeenCalled();
		expect(get(activeJobs)).toHaveLength(1);
	},
	closeWays: [
		{
			way: '×',
			close: async (target) => {
				pressEditorButton(target, 'albumCover.editingClose');
				await editingClosed(target);
			}
		},
		{
			way: 'Escape',
			close: async (target) => {
				document.body.dispatchEvent(
					new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
				);
				await editingClosed(target);
			}
		}
	]
});
