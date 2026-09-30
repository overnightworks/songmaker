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

function editorActions(target: HTMLElement): string[] {
	return Array.from(target.querySelectorAll('.cover-actions button')).map(accessibleName);
}

function press(target: HTMLElement, name: string): void {
	getByRoleButton(requireElement(target, '.cover-editor'), name).click();
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

	it('tapping Add cover grows the cover in place and makes the first suggestion', async () => {
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

	it('opens a cover already set with a quiet Remove and makes nothing by itself', async () => {
		albumList.set([coveredAlbum()]);
		const target = await renderDetail();

		expect(accessibleName(requireElement(target, 'button.header-cover'))).toBe('Edit cover');
		await openCoverEditing(target);
		await vi.waitFor(() => expect(countLine(target)).toBe('10 of 10 left today'));

		expect(shownImage(target)).toBe('/cover-detail.jpg');
		expect(editorActions(target)).toEqual([
			'Upload',
			'Suggest another',
			'Use',
			'Remove',
			'Close cover editing'
		]);
		expect(getByRoleButton(requireElement(target, '.cover-editor'), 'Use').disabled).toBe(true);
		expect(createAlbumCoverSuggestions).not.toHaveBeenCalled();
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

		press(target, 'Previous suggestion');
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
		press(target, 'Next suggestion');
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

		press(target, 'Suggest another');

		await vi.waitFor(() => expect(countLine(target)).toBe('3 / 3 · 7 of 10 left today'));
		expect(target.querySelector('.cover-stage [role="progressbar"]')).not.toBeNull();
		expect(discardAlbumCoverSuggestions).not.toHaveBeenCalled();
		FakeJobEventSource.sources[0].emit(coverJob({ status: 'completed', progress: 1 }));

		await vi.waitFor(() => expect(shownImage(target)).toBe('/suggestion-three.png'));
		press(target, 'Previous suggestion');
		await tick();
		expect(shownImage(target)).toBe('/suggestion-two.png');
	});

	it('Use sets the shown suggestion as the cover, discards the rest and closes the editor', async () => {
		fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions(THREE_SUGGESTIONS));
		selectAlbumCoverSuggestion.mockResolvedValue(coveredAlbum());
		const target = await renderDetail();
		await openCoverEditing(target);
		await vi.waitFor(() => expect(shownImage(target)).toBe('/suggestion-three.png'));
		press(target, 'Previous suggestion');
		await tick();

		press(target, 'Use');

		await editingClosed(target);
		expect(selectAlbumCoverSuggestion).toHaveBeenCalledWith('a-local', { suggestion_id: 'two' });
		expect(discardAlbumCoverSuggestions).toHaveBeenCalledWith('a-local');
		expect(target.querySelector('.header-cover img')?.getAttribute('src')).toBe(
			'/cover-detail.jpg'
		);
	});

	it('× discards the unused suggestions and closes the editor', async () => {
		fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions(THREE_SUGGESTIONS));
		const target = await renderDetail();
		await openCoverEditing(target);
		await vi.waitFor(() => expect(shownImage(target)).toBe('/suggestion-three.png'));

		press(target, 'Close cover editing');

		await editingClosed(target);
		expect(discardAlbumCoverSuggestions).toHaveBeenCalledWith('a-local');
		expect(selectAlbumCoverSuggestion).not.toHaveBeenCalled();
		expect(accessibleName(requireElement(target, 'button.header-cover'))).toBe('Add cover');
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

			press(target, action);

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

		press(target, 'Remove');

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

		press(target, 'Upload');
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

	it('Replace… in the menu opens the cover editing without making anything', async () => {
		albumList.set([coveredAlbum()]);
		const target = await renderDetail();
		const menu = await openCollectionMenu(target);
		const items = Array.from(menu.querySelectorAll<HTMLButtonElement>('.menu-item'));
		expect(items.map((item) => item.textContent?.trim())).toEqual([
			'Upload…',
			'Replace…',
			'Remove cover',
			'Rename',
			'Add to playlist',
			'Curate album',
			'Archive album',
			'Delete album'
		]);

		items.find((item) => item.textContent?.trim() === 'Replace…')?.click();

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

	it.each([
		{
			refusal: 'a daily limit',
			error: serverRefusal('Daily cover suggestion limit reached'),
			named: 'Daily cover suggestion limit reached'
		},
		{
			refusal: 'a suggestion that already runs',
			error: new ApiError(409, 'Cover suggestions are already being generated', '/api/x'),
			named: 'A cover suggestion is already being made.'
		}
	])('names $refusal in the singular, once, without a toast', async ({ error, named }) => {
		createAlbumCoverSuggestions.mockRejectedValue(error);
		const target = await renderDetail();
		await openCoverEditing(target);

		await vi.waitFor(() => expect(target.querySelector('[role="alert"]')).not.toBeNull());
		const alert = requireElement(target, '[role="alert"]');
		expect(alert.textContent).toContain('Couldn’t make a cover suggestion');
		expect(alert.textContent).toContain(named);
		expect(target.textContent).not.toContain('Cover suggestions are already being generated');
		expect(target.textContent?.split(named)).toHaveLength(2);
		expect(addToast).not.toHaveBeenCalled();
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
			arrange: () => fetchAlbumCoverSuggestions.mockRejectedValue(lostNetwork())
		},
		{
			moment: 'making the first suggestion',
			arrange: () => createAlbumCoverSuggestions.mockRejectedValue(lostNetwork())
		}
	])('keeps the editor quiet when $moment finds no network', async ({ arrange }) => {
		arrange();
		const target = await renderDetail();
		await openCoverEditing(target);
		await reachSuggestionsLoads(1);
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

		press(target, 'Suggest another');
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
		albumList.set([coveredAlbum()]);
		fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions(ONE_SUGGESTION));
		return renderDetail();
	},
	open: async (target) => {
		await openCoverEditing(target);
	},
	isShown: (target) => editor(target) !== null,
	afterBack: () => expect(discardAlbumCoverSuggestions).not.toHaveBeenCalled(),
	closeWays: [
		{
			way: '×',
			close: async (target) => {
				press(target, 'Close cover editing');
				await editingClosed(target);
			}
		}
	]
});
