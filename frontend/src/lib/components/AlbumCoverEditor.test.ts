import { makeAlbum as album, makeSong as song } from '$lib/test-utils/factories';
import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { CoverSuggestionsResponse, JobItem } from '$lib/api/types';
import { ApiError } from '$lib/api/fetch';
import { lostNetwork, serverRefusal } from '$lib/test-utils/network';
import { getByRoleButton, accessibleName } from '$lib/test-utils/accessible-name';
import { describeBackClosesOverlay } from '$lib/test-utils/library-history';
import { reportResourceStreamReachable, resetConnectivityForTests } from '$lib/stores/connectivity';
import { UNREACHABLE_RELOAD_DELAYS_MS } from '$lib/constants';
import { listenForGlobalEscape } from '$lib/test-utils/global-escape';
import { dropLayersFrom, stackedLayers } from '$lib/stores/layers';
import {
	createComponentMount,
	openCollectionMenu,
	requireElement
} from './shell/rail-test-fixtures';
import { albumList, resetLibraryDataForTests, songList } from '$lib/stores/libraryData';
import { selectedAlbumId } from '$lib/stores/player';
import { activeJobs } from '$lib/stores/jobs';

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

class FakeJobEventSource {
	static sources: FakeJobEventSource[] = [];
	onmessage: ((event: MessageEvent) => void) | null = null;
	onerror: ((event: Event) => void) | null = null;

	constructor(readonly url: string) {
		FakeJobEventSource.sources.push(this);
	}

	close(): void {}

	emit(job: JobItem): void {
		this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(job) }));
	}
}

function coverSuggestions(
	overrides: Partial<CoverSuggestionsResponse> = {}
): CoverSuggestionsResponse {
	return { job: null, suggestions: [], used_today: 0, daily_limit: 10, ...overrides };
}

function coverJob(overrides: Partial<JobItem> = {}): JobItem {
	return { id: 'cover-job', type: 'cover', status: 'queued', progress: 0, ...overrides };
}

const SPENT_TODAY = coverSuggestions({ used_today: 10 });
const ONE_SUGGESTION = { suggestions: [{ id: 'one', url: '/suggestion-one.png' }] };
const THREE_SUGGESTIONS = {
	suggestions: [
		{ id: 'one', url: '/suggestion-one.png' },
		{ id: 'two', url: '/suggestion-two.png' },
		{ id: 'three', url: '/suggestion-three.png' }
	]
};
const COVERED = { card: '/cover-card.jpg', detail: '/cover-detail.jpg' };
const UPLOADED = { card: '/uploaded-card.jpg', detail: '/uploaded-detail.jpg' };

function coveredAlbum(cover = COVERED) {
	return album({ id: 'a-local', title: 'Night Drive', cover });
}

function editor(target: HTMLElement): HTMLElement | null {
	return target.querySelector('.cover-editor');
}

async function openCoverEditing(target: HTMLElement): Promise<HTMLElement> {
	await vi.waitFor(() => expect(target.querySelector('button.header-cover')).not.toBeNull());
	requireElement<HTMLButtonElement>(target, 'button.header-cover').click();
	await vi.waitFor(() => expect(editor(target)).not.toBeNull());
	return editor(target) as HTMLElement;
}

async function editingClosed(target: HTMLElement): Promise<void> {
	await vi.waitFor(() => expect(editor(target)).toBeNull());
}

function countLine(target: HTMLElement): string {
	return (target.querySelector('.cover-count')?.textContent ?? '').replace(/\s+/g, ' ').trim();
}

function shownImage(target: HTMLElement): string | null {
	return target.querySelector('.cover-stage img')?.getAttribute('src') ?? null;
}

function failureAlert(target: HTMLElement): HTMLElement | null {
	return target.querySelector('.cover-editor [role="alert"]');
}

function stageLabel(target: HTMLElement): string | null {
	return requireElement(target, '.cover-stage').getAttribute('aria-label');
}

async function pressSuggestOnceLoaded(target: HTMLElement): Promise<void> {
	await vi.waitFor(() =>
		expect(getByRoleButton(requireElement(target, '.cover-editor'), 'Suggest').disabled).toBe(false)
	);
	pressEditorButton(target, 'Suggest');
}

function editorActions(target: HTMLElement): string[] {
	return Array.from(target.querySelectorAll('.cover-actions button')).map(accessibleName);
}

function pressEditorButton(target: HTMLElement, name: string): void {
	getByRoleButton(requireElement(target, '.cover-editor'), name).click();
}

function uploadCoverFile(target: HTMLElement): void {
	const input = requireElement<HTMLInputElement>(target, '.cover-file-input');
	vi.spyOn(input, 'click').mockImplementation(() => undefined);
	pressEditorButton(target, 'Upload');
	const file = new File([new Uint8Array([1])], 'cover.jpg', { type: 'image/jpeg' });
	Object.defineProperty(input, 'files', { configurable: true, value: [file] });
	input.dispatchEvent(new Event('change', { bubbles: true }));
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
const RELOAD_ATTEMPTS = UNREACHABLE_RELOAD_DELAYS_MS.length;
const PAST_EVERY_RELOAD_MS = UNREACHABLE_RELOAD_DELAYS_MS.reduce((a, b) => a + b, 0) * 2;

async function reachSuggestionsLoads(count: number): Promise<void> {
	await vi.waitFor(() => expect(fetchAlbumCoverSuggestions).toHaveBeenCalledTimes(count));
	await tick();
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
	let resolve!: (value: T) => void;
	return { promise: new Promise<T>((done) => (resolve = done)), resolve };
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
	FakeJobEventSource.sources = [];
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
		expect(accessibleName(place)).toBe('Add cover');
		expect(place.textContent).toContain('Add cover');
		expect(editor(target)).toBeNull();
		expect(target.textContent).not.toContain('Choose a cover');
		expect(fetchAlbumCoverSuggestions).not.toHaveBeenCalled();
		expect(createAlbumCoverSuggestions).not.toHaveBeenCalled();
	});

	it('tapping Add cover grows the cover in place with Upload · Suggest and makes nothing', async () => {
		const target = await renderDetail();

		await openCoverEditing(target);
		await vi.waitFor(() => expect(countLine(target)).toBe('10 of 10 left today'));
		expect(editorActions(target)).toEqual(['Upload', 'Suggest', 'Close cover editing']);
		expect(stageLabel(target)).toBeNull();

		pressEditorButton(target, 'Close cover editing');
		await editingClosed(target);
		await openCoverEditing(target);
		await vi.waitFor(() => expect(countLine(target)).toBe('10 of 10 left today'));

		expect(createAlbumCoverSuggestions).not.toHaveBeenCalled();
		expect(discardAlbumCoverSuggestions).not.toHaveBeenCalled();
	});

	it('Suggest makes the first suggestion in place and then reads Suggest another', async () => {
		vi.stubGlobal('EventSource', FakeJobEventSource);
		fetchAlbumCoverSuggestions
			.mockResolvedValueOnce(coverSuggestions({ used_today: 1 }))
			.mockResolvedValueOnce(
				coverSuggestions({ job: coverJob({ status: 'running', progress: 0.4 }), used_today: 2 })
			)
			.mockResolvedValue(coverSuggestions({ ...ONE_SUGGESTION, used_today: 2 }));
		createAlbumCoverSuggestions.mockResolvedValue(coverJob());
		const target = await renderDetail();
		await openCoverEditing(target);

		await pressSuggestOnceLoaded(target);

		await vi.waitFor(() => expect(createAlbumCoverSuggestions).toHaveBeenCalledWith('a-local'));
		await vi.waitFor(() =>
			expect(target.querySelector('.cover-stage [role="progressbar"]')).not.toBeNull()
		);
		await vi.waitFor(() => expect(FakeJobEventSource.sources).toHaveLength(1));
		FakeJobEventSource.sources[0].emit(coverJob({ status: 'completed', progress: 1 }));

		await vi.waitFor(() => expect(shownImage(target)).toBe('/suggestion-one.png'));
		expect(countLine(target)).toBe('1 / 1 · 8 of 10 left today');
		expect(editorActions(target)).toEqual([
			'Upload',
			'Suggest another',
			'Use',
			'Close cover editing'
		]);
		expect(createAlbumCoverSuggestions).toHaveBeenCalledTimes(1);
		expect(target.querySelector('.header-title')?.textContent).toContain('Night Drive');
		expect(target.querySelector('.play-circle')).not.toBeNull();
		expect(target.querySelector('.item-row')).not.toBeNull();
	});

	it.each([
		{
			when: 'known before asking',
			arrange: () => fetchAlbumCoverSuggestions.mockResolvedValue(SPENT_TODAY),
			asks: 0
		},
		{
			when: 'refused while asking',
			arrange: () => {
				fetchAlbumCoverSuggestions
					.mockResolvedValueOnce(coverSuggestions({ used_today: 9 }))
					.mockResolvedValue(SPENT_TODAY);
				createAlbumCoverSuggestions.mockRejectedValue(
					new ApiError(429, 'Daily cover suggestion limit reached', '/api/albums/a-local')
				);
			},
			asks: 1
		}
	])(
		'with no suggestion left today ($when) says so once and counts no suggestion',
		async ({ arrange, asks }) => {
			arrange();
			const target = await renderDetail();

			await openCoverEditing(target);
			if (asks) await pressSuggestOnceLoaded(target);
			await vi.waitFor(() =>
				expect(countLine(target)).toBe('0 of 10 left today Daily cover suggestion limit reached')
			);
			await tick();

			expect(createAlbumCoverSuggestions).toHaveBeenCalledTimes(asks);
			expect(fetchAlbumCoverSuggestions).toHaveBeenCalledTimes(asks + 1);
			expect(getByRoleButton(editor(target) as HTMLElement, 'Suggest').disabled).toBe(true);
			expect(failureAlert(target)).toBeNull();
			expect(addToast).not.toHaveBeenCalled();
		}
	);

	it('at the daily limit the grown Add cover place opens Upload', async () => {
		fetchAlbumCoverSuggestions.mockResolvedValue(SPENT_TODAY);
		const target = await renderDetail();
		await openCoverEditing(target);
		await vi.waitFor(() => expect(countLine(target)).toContain('0 of 10 left today'));
		const input = requireElement<HTMLInputElement>(target, '.cover-file-input');
		const picker = vi.spyOn(input, 'click').mockImplementation(() => undefined);

		getByRoleButton(requireElement(target, '.cover-stage'), 'Add cover').click();

		expect(picker).toHaveBeenCalledTimes(1);
		expect(createAlbumCoverSuggestions).not.toHaveBeenCalled();
	});

	it('names a throttled ask as an ordinary failure, rereads the count and keeps Suggest open', async () => {
		fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions({ used_today: 3 }));
		createAlbumCoverSuggestions.mockRejectedValue(
			new ApiError(429, 'Too many requests, slow down', '/api/albums/a-local')
		);
		const target = await renderDetail();
		await openCoverEditing(target);

		await pressSuggestOnceLoaded(target);
		await vi.waitFor(() =>
			expect(failureAlert(target)?.textContent).toContain('Too many requests, slow down')
		);

		expect(fetchAlbumCoverSuggestions).toHaveBeenCalledTimes(2);
		expect(countLine(target)).toContain('7 of 10 left today');
		expect(getByRoleButton(editor(target) as HTMLElement, 'Suggest').disabled).toBe(false);
	});

	it.each([
		{
			before: 'no suggestion',
			made: [],
			counted: '9 of 10 left today',
			shown: '/cover-detail.jpg',
			label: null
		},
		{
			before: 'two suggestions',
			made: THREE_SUGGESTIONS.suggestions.slice(0, 2),
			counted: '2 / 2 · 7 of 10 left today',
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
					job: coverJob({ status: 'failed', error: 'Cover suggestion could not be generated' }),
					used_today: made.length + 1
				})
			);
			const target = await renderDetail();

			await openCoverEditing(target);
			await vi.waitFor(() =>
				expect(failureAlert(target)?.textContent).toContain('Couldn’t make a cover suggestion')
			);

			expect(countLine(target)).toContain(counted);
			expect(shownImage(target)).toBe(shown);
			expect(stageLabel(target)).toBe(label);
			expect(target.querySelector('.cover-stage [role="alert"]')).toBeNull();
		}
	);

	it('opens a cover already set with a quiet Remove and makes nothing by itself', async () => {
		albumList.set([coveredAlbum()]);
		const target = await renderDetail();

		expect(accessibleName(requireElement(target, 'button.header-cover'))).toBe('Edit cover');
		await openCoverEditing(target);
		await vi.waitFor(() => expect(countLine(target)).toBe('10 of 10 left today'));

		expect(shownImage(target)).toBe('/cover-detail.jpg');
		expect(editorActions(target)).toEqual(['Upload', 'Suggest', 'Remove', 'Close cover editing']);
		expect(stageLabel(target)).toBeNull();
		expect(createAlbumCoverSuggestions).not.toHaveBeenCalled();
	});

	it('with a cover set and a suggestion made the row ends Use · Remove · ×', async () => {
		albumList.set([coveredAlbum()]);
		fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions(ONE_SUGGESTION));
		const target = await renderDetail();

		await openCoverEditing(target);
		await vi.waitFor(() => expect(shownImage(target)).toBe('/suggestion-one.png'));

		expect(editorActions(target)).toEqual([
			'Upload',
			'Suggest another',
			'Use',
			'Remove',
			'Close cover editing'
		]);
	});

	it('browses the suggestions made so far with ‹ › and a swipe on the cover', async () => {
		fetchAlbumCoverSuggestions.mockResolvedValue(
			coverSuggestions({ ...THREE_SUGGESTIONS, used_today: 4 })
		);
		const target = await renderDetail();
		await openCoverEditing(target);

		await vi.waitFor(() => expect(countLine(target)).toBe('3 / 3 · 6 of 10 left today'));
		expect(shownImage(target)).toBe('/suggestion-three.png');
		expect(requireElement(target, '.cover-stage').getAttribute('aria-label')).toBe(
			'Cover suggestion 3 of 3'
		);

		pressEditorButton(target, 'Previous suggestion');
		await tick();
		expect(countLine(target)).toBe('2 / 3 · 6 of 10 left today');
		expect(shownImage(target)).toBe('/suggestion-two.png');

		swipe(target, 60);
		await tick();
		expect(shownImage(target)).toBe('/suggestion-one.png');
		expect(
			getByRoleButton(requireElement(target, '.cover-editor'), 'Previous suggestion').disabled
		).toBe(true);

		swipe(target, 10);
		await tick();
		expect(shownImage(target)).toBe('/suggestion-one.png');

		swipe(target, -60);
		await tick();
		pressEditorButton(target, 'Next suggestion');
		await tick();
		expect(countLine(target)).toBe('3 / 3 · 6 of 10 left today');
		expect(createAlbumCoverSuggestions).not.toHaveBeenCalled();
	});

	it('Suggest another keeps every earlier suggestion and shows the new one once it lands', async () => {
		vi.stubGlobal('EventSource', FakeJobEventSource);
		const two = { suggestions: THREE_SUGGESTIONS.suggestions.slice(0, 2) };
		fetchAlbumCoverSuggestions
			.mockResolvedValueOnce(coverSuggestions({ ...two, used_today: 2 }))
			.mockResolvedValueOnce(
				coverSuggestions({ ...two, job: coverJob({ status: 'running' }), used_today: 3 })
			)
			.mockResolvedValue(coverSuggestions({ ...THREE_SUGGESTIONS, used_today: 3 }));
		createAlbumCoverSuggestions.mockResolvedValue(coverJob());
		const target = await renderDetail();
		await openCoverEditing(target);
		await vi.waitFor(() => expect(countLine(target)).toBe('2 / 2 · 8 of 10 left today'));

		pressEditorButton(target, 'Suggest another');

		await vi.waitFor(() => expect(countLine(target)).toBe('7 of 10 left today'));
		expect(target.querySelector('.cover-stage [role="progressbar"]')).not.toBeNull();
		expect(stageLabel(target)).toBeNull();
		expect(discardAlbumCoverSuggestions).not.toHaveBeenCalled();
		FakeJobEventSource.sources[0].emit(coverJob({ status: 'completed', progress: 1 }));

		await vi.waitFor(() => expect(shownImage(target)).toBe('/suggestion-three.png'));
		pressEditorButton(target, 'Previous suggestion');
		await tick();
		expect(shownImage(target)).toBe('/suggestion-two.png');
	});

	it('Use sets the shown suggestion as the cover, discards the rest and closes the editor', async () => {
		fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions(THREE_SUGGESTIONS));
		selectAlbumCoverSuggestion.mockResolvedValue(coveredAlbum());
		const target = await renderDetail();
		await openCoverEditing(target);
		await vi.waitFor(() => expect(shownImage(target)).toBe('/suggestion-three.png'));
		pressEditorButton(target, 'Previous suggestion');
		await tick();

		pressEditorButton(target, 'Use');

		await editingClosed(target);
		expect(selectAlbumCoverSuggestion).toHaveBeenCalledWith('a-local', { suggestion_id: 'two' });
		expect(discardAlbumCoverSuggestions).toHaveBeenCalledWith('a-local');
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

		pressEditorButton(target, 'Use');
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
			press: (target: HTMLElement) => pressEditorButton(target, 'Close cover editing')
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
		fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions(THREE_SUGGESTIONS));
		const target = await renderDetail();
		await openCoverEditing(target);
		await vi.waitFor(() => expect(shownImage(target)).toBe('/suggestion-three.png'));

		pressEditorButton(target, 'Close cover editing');

		await editingClosed(target);
		expect(discardAlbumCoverSuggestions).toHaveBeenCalledWith('a-local');
		expect(selectAlbumCoverSuggestion).not.toHaveBeenCalled();
		expect(cancelJob).not.toHaveBeenCalled();
		expect(accessibleName(requireElement(target, 'button.header-cover'))).toBe('Add cover');
	});

	it('Escape closes the editor like × and moves no level up', async () => {
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
		expect(discardAlbumCoverSuggestions).toHaveBeenCalledWith('a-local');
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
		{ way: 'another album', leave: () => selectedAlbumId.set('a-other') }
	])('leaving by $way stops the suggestion still running', async ({ leave }) => {
		vi.stubGlobal('EventSource', FakeJobEventSource);
		albumList.set([
			album({ id: 'a-local', title: 'Night Drive' }),
			album({ id: 'a-other', title: 'Other Night' })
		]);
		const running = coverSuggestions({ job: coverJob({ status: 'running' }), used_today: 1 });
		fetchAlbumCoverSuggestions
			.mockResolvedValueOnce(coverSuggestions())
			.mockImplementation(async (albumId: string) =>
				albumId === 'a-local' ? running : coverSuggestions()
			);
		createAlbumCoverSuggestions.mockResolvedValue(coverJob());
		const target = await renderDetail();
		await openCoverEditing(target);
		await pressSuggestOnceLoaded(target);
		await vi.waitFor(() =>
			expect(target.querySelector('.cover-stage [role="progressbar"]')).not.toBeNull()
		);

		await leave(target);

		await editingClosed(target);
		await vi.waitFor(() => expect(cancelJob).toHaveBeenCalledWith('cover-job'));
		expect(get(activeJobs)).toEqual([]);
	});

	it('× stops the running suggestion before it discards, so nothing lands afterwards', async () => {
		fetchAlbumCoverSuggestions.mockResolvedValue(
			coverSuggestions({ ...ONE_SUGGESTION, job: coverJob({ status: 'running' }) })
		);
		const target = await renderDetail();
		await openCoverEditing(target);
		await vi.waitFor(() =>
			expect(target.querySelector('.cover-stage [role="progressbar"]')).not.toBeNull()
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

	it('× while the suggestions still load closes the editor without making a suggestion', async () => {
		const firstLoad = deferred<CoverSuggestionsResponse>();
		fetchAlbumCoverSuggestions.mockReturnValueOnce(firstLoad.promise);
		const target = await renderDetail();
		await openCoverEditing(target);
		await reachSuggestionsLoads(1);
		expect(countLine(target)).toBe('Loading cover suggestion…');

		pressEditorButton(target, 'Close cover editing');
		await editingClosed(target);
		firstLoad.resolve(coverSuggestions());
		await new Promise((settled) => setTimeout(settled, 0));

		expect(createAlbumCoverSuggestions).not.toHaveBeenCalled();
	});

	it.each([
		{
			action: 'Close cover editing',
			arrange: () =>
				discardAlbumCoverSuggestions.mockRejectedValue(
					serverRefusal('Could not discard suggestions')
				),
			toast: 'Could not discard suggestions'
		},
		{
			action: 'Use',
			arrange: () => selectAlbumCoverSuggestion.mockRejectedValue(serverRefusal('Could not save')),
			toast: 'Could not save'
		},
		{
			action: 'Close cover editing',
			arrange: () => discardAlbumCoverSuggestions.mockRejectedValue(lostNetwork()),
			toast: 'The cover suggestion failed. Try again.'
		},
		{
			action: 'Use',
			arrange: () => selectAlbumCoverSuggestion.mockRejectedValue(lostNetwork()),
			toast: 'The cover suggestion failed. Try again.'
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

		pressEditorButton(target, 'Remove');

		await editingClosed(target);
		expect(deleteAlbumCover).toHaveBeenCalledWith('a-local');
		expect(accessibleName(requireElement(target, 'button.header-cover'))).toBe('Add cover');
	});

	it('Upload picks a file, and the uploaded cover closes the editor', async () => {
		albumList.set([coveredAlbum()]);
		uploadAlbumCover.mockResolvedValue(coveredAlbum(UPLOADED));
		const target = await renderDetail();
		await openCoverEditing(target);
		const input = requireElement<HTMLInputElement>(target, '.cover-file-input');
		const picker = vi.spyOn(input, 'click').mockImplementation(() => undefined);

		pressEditorButton(target, 'Upload');
		expect(picker).toHaveBeenCalledTimes(1);
		const file = new File([new Uint8Array([1, 2, 3])], 'cover.jpg', { type: 'image/jpeg' });
		Object.defineProperty(input, 'files', { configurable: true, value: [file] });
		input.dispatchEvent(new Event('change', { bubbles: true }));

		await editingClosed(target);
		expect(target.querySelector('.header-cover img')?.getAttribute('src')).toBe(
			'/uploaded-detail.jpg'
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

	it('Cover in the menu opens the cover editing without making anything', async () => {
		albumList.set([coveredAlbum()]);
		const target = await renderDetail();
		const menu = await openCollectionMenu(target);
		const items = Array.from(menu.querySelectorAll<HTMLButtonElement>('.menu-item'));

		items.find((item) => item.textContent?.trim().startsWith('Cover'))?.click();

		await vi.waitFor(() => expect(editor(target)).not.toBeNull());
		expect(createAlbumCoverSuggestions).not.toHaveBeenCalled();
	});

	it('shows progress only while the suggestion runs and names a run that hit its time limit', async () => {
		vi.stubGlobal('EventSource', FakeJobEventSource);
		fetchAlbumCoverSuggestions
			.mockResolvedValueOnce(
				coverSuggestions({ job: coverJob({ status: 'running', progress: 0.5 }) })
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

		await vi.waitFor(() =>
			expect(
				target.querySelector('.cover-stage [role="progressbar"]')?.getAttribute('aria-valuenow')
			).toBe('50')
		);
		expect(target.querySelector('.cover-stage')?.textContent).toContain('Making your cover…');
		await vi.waitFor(() => expect(FakeJobEventSource.sources).toHaveLength(1));
		FakeJobEventSource.sources[0].emit(
			coverJob({ status: 'failed', error: 'Cover suggestion could not be generated' })
		);

		await vi.waitFor(() =>
			expect(target.querySelector('[role="alert"]')?.textContent).toContain(
				'Couldn’t make a cover suggestion'
			)
		);
		expect(target.querySelector('[role="alert"]')?.textContent).toContain(
			'Cover suggestion could not be generated'
		);
		expect(target.querySelector('[role="progressbar"]')).toBeNull();
		expect(target.querySelector('.suggestion-placeholder')).toBeNull();
		expect(createAlbumCoverSuggestions).not.toHaveBeenCalled();
	});

	it('names a daily limit in the singular, once, without a toast', async () => {
		const named = 'Daily cover suggestion limit reached';
		createAlbumCoverSuggestions.mockRejectedValue(serverRefusal(named));
		const target = await renderDetail();
		await openCoverEditing(target);

		await pressSuggestOnceLoaded(target);

		await vi.waitFor(() => expect(target.querySelector('[role="alert"]')).not.toBeNull());
		const alert = requireElement(target, '[role="alert"]');
		expect(alert.textContent).toContain('Couldn’t make a cover suggestion');
		expect(alert.textContent).toContain(named);
		expect(target.textContent?.split(named)).toHaveLength(2);
		expect(addToast).not.toHaveBeenCalled();
	});

	it.each([
		{
			reread: 'follows the run that still goes',
			found: coverSuggestions({
				job: coverJob({ status: 'running', progress: 0.3 }),
				used_today: 3
			}),
			shows: (target: HTMLElement) =>
				expect(target.querySelector('.cover-stage [role="progressbar"]')).not.toBeNull()
		},
		{
			reread: 'shows the suggestion of a run that ended meanwhile',
			found: coverSuggestions({ ...ONE_SUGGESTION, used_today: 3 }),
			shows: (target: HTMLElement) => expect(shownImage(target)).toBe('/suggestion-one.png')
		}
	])(
		'a refusal because a suggestion already runs reads the list again and $reread, with no word of its own',
		async ({ found, shows }) => {
			vi.stubGlobal('EventSource', FakeJobEventSource);
			fetchAlbumCoverSuggestions
				.mockResolvedValueOnce(coverSuggestions({ used_today: 2 }))
				.mockResolvedValue(found);
			createAlbumCoverSuggestions.mockRejectedValue(
				new ApiError(409, 'Cover suggestions are already being generated', '/api/x')
			);
			const target = await renderDetail();
			await openCoverEditing(target);

			await pressSuggestOnceLoaded(target);

			await vi.waitFor(() => expect(countLine(target)).toContain('7 of 10 left today'));
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
				job: coverJob({ id: 'ended-run', status: 'completed', progress: 1 }),
				used_today: 3
			}),
			shows: (target: HTMLElement) => {
				expect(shownImage(target)).toBe('/suggestion-one.png');
				expect(failureAlert(target)).toBeNull();
			}
		},
		{
			result: 'its failure line, also when it spent the last suggestion of the day',
			found: coverSuggestions({
				job: coverJob({ id: 'ended-run', status: 'failed', error: 'The model ran out of memory' }),
				used_today: 10
			}),
			shows: (target: HTMLElement) =>
				expect(failureAlert(target)?.textContent).toContain('The model ran out of memory')
		}
	])(
		"a refused ask whose run already ended shows that run's result: $result",
		async ({ found, shows }) => {
			fetchAlbumCoverSuggestions
				.mockResolvedValueOnce(coverSuggestions({ used_today: 2 }))
				.mockResolvedValue(found);
			createAlbumCoverSuggestions.mockRejectedValue(
				new ApiError(409, 'Cover suggestions are already being generated', '/api/x')
			);
			const target = await renderDetail();
			await openCoverEditing(target);

			await pressSuggestOnceLoaded(target);

			await reachSuggestionsLoads(2);
			shows(target);
			expect(target.textContent).not.toContain('already being');
		}
	);

	it('the daily limit is the only message for that tap, also after reopening', async () => {
		const olderRunFailed = coverJob({
			id: 'older-run',
			status: 'failed',
			error: 'An older run went wrong'
		});
		fetchAlbumCoverSuggestions
			.mockResolvedValueOnce(coverSuggestions({ job: olderRunFailed, used_today: 9 }))
			.mockResolvedValue(coverSuggestions({ job: olderRunFailed, used_today: 10 }));
		createAlbumCoverSuggestions.mockRejectedValue(
			new ApiError(429, 'Daily cover suggestion limit reached', '/api/albums/a-local')
		);
		const target = await renderDetail();
		await openCoverEditing(target);

		await pressSuggestOnceLoaded(target);
		await vi.waitFor(() =>
			expect(countLine(target)).toBe('0 of 10 left today Daily cover suggestion limit reached')
		);
		expect(failureAlert(target)).toBeNull();

		pressEditorButton(target, 'Close cover editing');
		await editingClosed(target);
		await openCoverEditing(target);
		await reachSuggestionsLoads(3);

		expect(countLine(target)).toBe('0 of 10 left today Daily cover suggestion limit reached');
		expect(failureAlert(target)).toBeNull();
	});

	it('hydrates a running cover job once and shows its suggestion after the streamed completion', async () => {
		vi.stubGlobal('EventSource', FakeJobEventSource);
		fetchAlbumCoverSuggestions
			.mockResolvedValueOnce(
				coverSuggestions({ job: coverJob({ status: 'running', progress: 0.5 }) })
			)
			.mockResolvedValueOnce(
				coverSuggestions({ suggestions: [{ id: 'finished', url: '/finished-suggestion.png' }] })
			);
		const target = await renderDetail();
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
		arrange();
		const target = await renderDetail();
		await openCoverEditing(target);
		await reachSuggestionsLoads(1);
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

	it('reloads the suggestions once the connection is back', async () => {
		vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
		reportResourceStreamReachable(false);
		fetchAlbumCoverSuggestions.mockRejectedValue(lostNetwork());
		const target = await renderDetail();
		await openCoverEditing(target);
		await reachSuggestionsLoads(1);
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
		fetchAlbumCoverSuggestions.mockRejectedValue(lostNetwork());
		const target = await renderDetail();
		await openCoverEditing(target);
		await reachSuggestionsLoads(1);
		for (const [attempt, delay] of UNREACHABLE_RELOAD_DELAYS_MS.entries()) {
			expect(target.querySelector('.cover-suggestions-retry')).toBeNull();
			await vi.advanceTimersByTimeAsync(delay);
			await reachSuggestionsLoads(attempt + 2);
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
		fetchAlbumCoverSuggestions
			.mockRejectedValueOnce(lostNetwork())
			.mockResolvedValue(coverSuggestions({ job: coverJob({ status: 'running' }) }));
		const suggestionJob = deferred<JobItem>();
		createAlbumCoverSuggestions.mockImplementation(() => suggestionJob.promise);
		const target = await renderDetail();
		await openCoverEditing(target);
		await reachSuggestionsLoads(1);

		pressEditorButton(target, 'Suggest');
		await vi.waitFor(() => expect(createAlbumCoverSuggestions).toHaveBeenCalledWith('a-local'));
		await vi.advanceTimersByTimeAsync(PAST_EVERY_RELOAD_MS);

		expect(fetchAlbumCoverSuggestions).toHaveBeenCalledTimes(1);
		suggestionJob.resolve(coverJob());
		await vi.waitFor(() =>
			expect(target.querySelector('.cover-stage')?.textContent).toContain('Making your cover…')
		);
	});
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
	afterBack: async () => {
		await vi.waitFor(() => expect(discardAlbumCoverSuggestions).toHaveBeenCalledWith('a-local'));
		expect(cancelJob.mock.invocationCallOrder[0]).toBeLessThan(
			discardAlbumCoverSuggestions.mock.invocationCallOrder[0]
		);
	},
	closeWays: [
		{
			way: '×',
			close: async (target) => {
				pressEditorButton(target, 'Close cover editing');
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
