import { makeAlbum as album, makeSong as song } from '$lib/test-utils/factories';
import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { CoverSuggestionsResponse, JobItem } from '$lib/api/types';
import { lostNetwork, serverRefusal } from '$lib/test-utils/network';
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
	discardAlbumCoverSuggestions.mockReset();
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

describe('AlbumCoverEditor on the album page', () => {
	it('waits for a deliberate Suggest cover click before creating a job', async () => {
		vi.stubGlobal('EventSource', FakeJobEventSource);
		const target = await renderDetail();
		expect(createAlbumCoverSuggestions).not.toHaveBeenCalled();
		await vi.waitFor(() => expect(target.querySelector('.suggest-cover')).not.toBeNull());

		createAlbumCoverSuggestions.mockResolvedValue(coverJob());
		requireElement<HTMLButtonElement>(target, '.suggest-cover').click();

		await vi.waitFor(() => expect(createAlbumCoverSuggestions).toHaveBeenCalledWith('a-local'));
		await vi.waitFor(() => expect(target.textContent).toContain('Making your cover…'));
	});

	it('shows the API detail when suggesting a cover fails', async () => {
		createAlbumCoverSuggestions.mockRejectedValue(
			serverRefusal('Daily cover suggestion limit reached')
		);
		const target = await renderDetail();
		await vi.waitFor(() => expect(target.querySelector('.suggest-cover')).not.toBeNull());

		requireElement<HTMLButtonElement>(target, '.suggest-cover').click();

		await vi.waitFor(() =>
			expect(target.textContent).toContain('Daily cover suggestion limit reached')
		);
		expect(target.querySelector('[role="alert"]')?.textContent).toContain(
			'Couldn’t make cover suggestions'
		);
		expect(target.querySelector('[role="alert"] button')?.textContent).toBe('Try again');
		expect(target.textContent?.split('Daily cover suggestion limit reached')).toHaveLength(2);
		expect(addToast).not.toHaveBeenCalled();
	});

	it.each([
		{
			moment: 'loading the card',
			arrange: () => fetchAlbumCoverSuggestions.mockRejectedValue(lostNetwork()),
			act: async () => {}
		},
		{
			moment: 'a deliberate Suggest cover',
			arrange: () => createAlbumCoverSuggestions.mockRejectedValue(lostNetwork()),
			act: async (target: HTMLElement) => {
				await vi.waitFor(() => expect(target.querySelector('.suggest-cover')).not.toBeNull());
				requireElement<HTMLButtonElement>(target, '.suggest-cover').click();
				await vi.waitFor(() => expect(createAlbumCoverSuggestions).toHaveBeenCalled());
			}
		}
	])(
		'hides the suggestions card without an error of its own when $moment finds no network',
		async ({ arrange, act }) => {
			arrange();
			const target = await renderDetail();
			await act(target);

			await vi.waitFor(() => expect(target.querySelector('.cover-suggestions')).toBeNull());
			expect(target.textContent).not.toContain('Failed to fetch');
			expect(target.textContent).not.toContain('Couldn’t make cover suggestions');
			expect(target.querySelector('[role="alert"]')).toBeNull();
			expect(addToast).not.toHaveBeenCalled();
			expect(target.textContent).toContain('Night Drive');
		}
	);

	it('keeps the suggestions card hidden while offline and reloads it once the connection is back', async () => {
		vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
		reportResourceStreamReachable(false);
		fetchAlbumCoverSuggestions.mockRejectedValue(lostNetwork());
		const target = await renderDetail();
		await reachSuggestionsLoads(1);
		await vi.advanceTimersByTimeAsync(PAST_EVERY_RELOAD_MS);
		expect(fetchAlbumCoverSuggestions).toHaveBeenCalledTimes(1);
		expect(target.querySelector('.cover-suggestions')).toBeNull();

		fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions(ONE_SUGGESTION));
		reportResourceStreamReachable(true);

		await vi.waitFor(() => expect(target.querySelectorAll('.cover-suggestion')).toHaveLength(1));
		expect(fetchAlbumCoverSuggestions).toHaveBeenCalledTimes(2);
	});

	it('reloads a card that found no network while online and shows it once the server answers', async () => {
		vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
		fetchAlbumCoverSuggestions
			.mockRejectedValueOnce(lostNetwork())
			.mockResolvedValue(coverSuggestions(ONE_SUGGESTION));
		const target = await renderDetail();
		await reachSuggestionsLoads(1);
		expect(target.querySelector('.cover-suggestions')).toBeNull();

		await vi.advanceTimersByTimeAsync(UNREACHABLE_RELOAD_DELAYS_MS[0]);

		await vi.waitFor(() => expect(target.querySelectorAll('.cover-suggestion')).toHaveLength(1));
		expect(fetchAlbumCoverSuggestions).toHaveBeenCalledTimes(2);
	});

	it('offers a quiet Try again once the bounded reloads still find no network while online', async () => {
		vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
		fetchAlbumCoverSuggestions.mockRejectedValue(lostNetwork());
		const target = await renderDetail();
		await reachSuggestionsLoads(1);
		for (const [attempt, delay] of UNREACHABLE_RELOAD_DELAYS_MS.entries()) {
			expect(target.querySelector('.cover-suggestions')).toBeNull();
			await vi.advanceTimersByTimeAsync(delay);
			await reachSuggestionsLoads(attempt + 2);
		}

		await vi.waitFor(() =>
			expect(target.querySelector('.cover-suggestions')?.textContent?.trim()).toBe('Try again')
		);
		expect(target.querySelector('[role="alert"]')).toBeNull();
		await vi.advanceTimersByTimeAsync(PAST_EVERY_RELOAD_MS);
		expect(fetchAlbumCoverSuggestions).toHaveBeenCalledTimes(1 + RELOAD_ATTEMPTS);

		fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions(ONE_SUGGESTION));
		requireElement<HTMLButtonElement>(target, '.cover-suggestions-retry').click();

		await vi.waitFor(() => expect(target.querySelectorAll('.cover-suggestion')).toHaveLength(1));
	});

	it('keeps a delayed previous album response from replacing the current album state', async () => {
		const firstResponse = deferred<CoverSuggestionsResponse>();
		albumList.set([
			album({ id: 'a-local', title: 'Night Drive' }),
			album({ id: 'a-other', title: 'Other Night' })
		]);
		fetchAlbumCoverSuggestions.mockImplementationOnce(() => firstResponse.promise);
		fetchAlbumCoverSuggestions.mockResolvedValueOnce(
			coverSuggestions({
				suggestions: [{ id: 'other-suggestion', url: '/other-suggestion.png' }]
			})
		);
		const target = await renderDetail();

		await vi.waitFor(() => expect(target.textContent).toContain('Loading cover suggestions…'));
		selectedAlbumId.set('a-other');
		await vi.waitFor(() => expect(fetchAlbumCoverSuggestions).toHaveBeenCalledWith('a-other'));
		await vi.waitFor(() => expect(target.querySelector('.cover-suggestion')).not.toBeNull());

		firstResponse.resolve(
			coverSuggestions({ job: coverJob({ status: 'failed', error: 'Old album failure' }) })
		);
		await tick();
		await tick();

		expect(target.textContent).toContain('Other Night');
		expect(target.textContent).not.toContain('Old album failure');
		expect(target.querySelector<HTMLImageElement>('.cover-suggestion img')?.src).toContain(
			'/other-suggestion.png'
		);
	});

	it('hydrates an active cover job once and reloads suggestions after its streamed completion', async () => {
		vi.stubGlobal('EventSource', FakeJobEventSource);
		fetchAlbumCoverSuggestions
			.mockResolvedValueOnce(
				coverSuggestions({ job: coverJob({ status: 'running', progress: 0.5 }) })
			)
			.mockResolvedValueOnce(
				coverSuggestions({ suggestions: [{ id: 'finished', url: '/finished-suggestion.png' }] })
			);
		const target = await renderDetail();

		await vi.waitFor(() => expect(FakeJobEventSource.sources).toHaveLength(1));
		await vi.waitFor(() => expect(target.textContent).toContain('Making your cover…'));
		expect(get(activeJobs)).toHaveLength(1);

		FakeJobEventSource.sources[0].emit(coverJob({ status: 'completed', progress: 1 }));

		await vi.waitFor(() => expect(target.querySelector('.cover-suggestion')).not.toBeNull());
		expect(FakeJobEventSource.sources).toHaveLength(1);
	});

	it('promises one cover while a request is drawing', async () => {
		vi.stubGlobal('EventSource', FakeJobEventSource);
		fetchAlbumCoverSuggestions.mockResolvedValue(
			coverSuggestions({
				job: coverJob({ status: 'running', progress: 0.5 }),
				used_today: 2,
				daily_limit: 10
			})
		);
		const target = await renderDetail();

		await vi.waitFor(() => expect(target.textContent).toContain('Making your cover…'));
		expect(target.textContent).toContain('Creating one suggestion · 2 of 10 today');
		expect(target.querySelectorAll('.suggestion-placeholder')).toHaveLength(1);
	});

	it('describes the pending suggestions without promising a count', async () => {
		fetchAlbumCoverSuggestions.mockResolvedValue(
			coverSuggestions({ suggestions: [{ id: 'one', url: '/suggestion-one.png' }] })
		);
		const target = await renderDetail();

		await vi.waitFor(() => expect(target.querySelector('.cover-suggestion')).not.toBeNull());
		expect(target.textContent).toContain('Made from this album’s metadata');
		expect(target.textContent).not.toContain('Three suggestions');
	});

	it('shows three suggestions, selects one, and updates the shared album owner', async () => {
		fetchAlbumCoverSuggestions.mockResolvedValue(
			coverSuggestions({
				suggestions: [
					{ id: 'one', url: '/suggestion-one.png' },
					{ id: 'two', url: '/suggestion-two.png' },
					{ id: 'three', url: '/suggestion-three.png' }
				]
			})
		);
		selectAlbumCoverSuggestion.mockResolvedValue(
			album({
				id: 'a-local',
				title: 'Night Drive',
				cover: { card: '/cover-card.jpg', detail: '/cover-detail.jpg' }
			})
		);
		const target = await renderDetail();

		await vi.waitFor(() => expect(target.querySelectorAll('.cover-suggestion')).toHaveLength(3));
		requireElement<HTMLButtonElement>(target, '.cover-suggestion button').click();

		await vi.waitFor(() =>
			expect(selectAlbumCoverSuggestion).toHaveBeenCalledWith('a-local', { suggestion_id: 'one' })
		);
		await vi.waitFor(() => expect(target.querySelector('.header-cover img')).not.toBeNull());
		expect(target.querySelector('.cover-suggestions')).toBeNull();
	});

	it('discards all suggestions and returns to the deliberate Suggest cover action', async () => {
		fetchAlbumCoverSuggestions.mockResolvedValue(
			coverSuggestions({ suggestions: [{ id: 'one', url: '/suggestion-one.png' }] })
		);
		discardAlbumCoverSuggestions.mockResolvedValue(undefined);
		const target = await renderDetail();

		await vi.waitFor(() => expect(target.querySelector('.suggestion-discard')).not.toBeNull());
		requireElement<HTMLButtonElement>(target, '.suggestion-discard').click();

		await vi.waitFor(() => expect(discardAlbumCoverSuggestions).toHaveBeenCalledWith('a-local'));
		await vi.waitFor(() =>
			expect(target.querySelector('.suggest-cover')?.textContent).toContain('Suggest cover')
		);
	});

	it('keeps suggestions available when discarding them fails', async () => {
		fetchAlbumCoverSuggestions.mockResolvedValue(
			coverSuggestions({ suggestions: [{ id: 'one', url: '/suggestion-one.png' }] })
		);
		discardAlbumCoverSuggestions.mockRejectedValue(serverRefusal('Could not discard suggestions'));
		const target = await renderDetail();

		await vi.waitFor(() => expect(target.querySelector('.suggestion-discard')).not.toBeNull());
		requireElement<HTMLButtonElement>(target, '.suggestion-discard').click();

		await vi.waitFor(() =>
			expect(addToast).toHaveBeenCalledWith('Could not discard suggestions', 'error')
		);
		expect(target.querySelectorAll('.cover-suggestion')).toHaveLength(1);
		expect(target.querySelector('[role="alert"]')).toBeNull();
	});

	it('keeps suggestions available when choosing one fails', async () => {
		fetchAlbumCoverSuggestions.mockResolvedValue(
			coverSuggestions({ suggestions: [{ id: 'one', url: '/suggestion-one.png' }] })
		);
		selectAlbumCoverSuggestion.mockRejectedValue(serverRefusal('Could not save cover'));
		const target = await renderDetail();

		await vi.waitFor(() => expect(target.querySelector('.cover-suggestion button')).not.toBeNull());
		requireElement<HTMLButtonElement>(target, '.cover-suggestion button').click();

		await vi.waitFor(() => expect(addToast).toHaveBeenCalledWith('Could not save cover', 'error'));
		expect(target.querySelectorAll('.cover-suggestion')).toHaveLength(1);
		expect(target.querySelector('[role="alert"]')).toBeNull();
	});

	it.each([
		{
			action: 'discarding suggestions',
			arrange: () => discardAlbumCoverSuggestions.mockRejectedValue(lostNetwork()),
			button: '.suggestion-discard'
		},
		{
			action: 'choosing a suggestion',
			arrange: () => selectAlbumCoverSuggestion.mockRejectedValue(lostNetwork()),
			button: '.cover-suggestion button'
		}
	])(
		'names the action, never the browser text, when $action finds no network',
		async ({ arrange, button }) => {
			fetchAlbumCoverSuggestions.mockResolvedValue(
				coverSuggestions({ suggestions: [{ id: 'one', url: '/suggestion-one.png' }] })
			);
			arrange();
			const target = await renderDetail();

			await vi.waitFor(() => expect(target.querySelector(button)).not.toBeNull());
			requireElement<HTMLButtonElement>(target, button).click();

			await vi.waitFor(() =>
				expect(addToast).toHaveBeenCalledWith('Cover suggestions failed. Try again.', 'error')
			);
			expect(vi.mocked(addToast).mock.calls.flat()).not.toContain('Failed to fetch');
		}
	);

	it('puts replacement by suggestion beside upload and removal in the existing overflow', async () => {
		albumList.set([
			album({
				id: 'a-local',
				title: 'Night Drive',
				cover: { card: '/cover-card.jpg', detail: '/cover-detail.jpg' }
			})
		]);
		const target = await renderDetail();
		const menu = await openCollectionMenu(target);
		const items = Array.from(menu.querySelectorAll('.menu-item')).map((element) =>
			element.textContent?.trim()
		);

		expect(items).toEqual([
			'Upload…',
			'Replace…',
			'Remove cover',
			'Rename',
			'Add to playlist',
			'Curate album',
			'Archive album',
			'Delete album'
		]);
	});

	it('replaces stale suggestions before a new request and keeps its failure visible', async () => {
		albumList.set([
			album({
				id: 'a-local',
				title: 'Night Drive',
				cover: { card: '/cover-card.jpg', detail: '/cover-detail.jpg' }
			})
		]);
		fetchAlbumCoverSuggestions.mockResolvedValue(
			coverSuggestions({
				suggestions: [
					{ id: 'one', url: '/suggestion-one.png' },
					{ id: 'two', url: '/suggestion-two.png' },
					{ id: 'three', url: '/suggestion-three.png' }
				]
			})
		);
		discardAlbumCoverSuggestions.mockResolvedValue(undefined);
		createAlbumCoverSuggestions.mockRejectedValue(
			serverRefusal('Daily cover suggestion limit reached')
		);
		const target = await renderDetail();

		await vi.waitFor(() => expect(target.querySelectorAll('.cover-suggestion')).toHaveLength(3));
		const menu = await openCollectionMenu(target);
		Array.from(menu.querySelectorAll<HTMLButtonElement>('.menu-item'))
			.find((element) => element.textContent?.trim() === 'Replace…')
			?.click();

		await vi.waitFor(() => expect(discardAlbumCoverSuggestions).toHaveBeenCalledWith('a-local'));
		await vi.waitFor(() => expect(createAlbumCoverSuggestions).toHaveBeenCalledWith('a-local'));
		expect(discardAlbumCoverSuggestions.mock.invocationCallOrder[0]).toBeLessThan(
			createAlbumCoverSuggestions.mock.invocationCallOrder[0]
		);
		await vi.waitFor(() =>
			expect(target.querySelector('[role="alert"]')?.textContent).toContain(
				'Daily cover suggestion limit reached'
			)
		);
		expect(target.querySelectorAll('.cover-suggestion')).toHaveLength(0);
		expect(target.querySelector('[role="alert"] button')?.textContent).toBe('Try again');
	});

	it('starting suggestions from the header menu stops a pending reload of the card', async () => {
		vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
		vi.stubGlobal('EventSource', FakeJobEventSource);
		albumList.set([
			album({
				id: 'a-local',
				title: 'Night Drive',
				cover: { card: '/cover-card.jpg', detail: '/cover-detail.jpg' }
			})
		]);
		fetchAlbumCoverSuggestions
			.mockRejectedValueOnce(lostNetwork())
			.mockResolvedValue(coverSuggestions(ONE_SUGGESTION));
		const suggestionJob = deferred<JobItem>();
		createAlbumCoverSuggestions.mockImplementation(() => suggestionJob.promise);
		const target = await renderDetail();
		await reachSuggestionsLoads(1);

		const menu = await openCollectionMenu(target);
		Array.from(menu.querySelectorAll<HTMLButtonElement>('.menu-item'))
			.find((element) => element.textContent?.trim() === 'Replace…')
			?.click();
		await vi.waitFor(() => expect(createAlbumCoverSuggestions).toHaveBeenCalledWith('a-local'));
		await vi.advanceTimersByTimeAsync(PAST_EVERY_RELOAD_MS);

		expect(fetchAlbumCoverSuggestions).toHaveBeenCalledTimes(1);
		suggestionJob.resolve(coverJob());
		await vi.waitFor(() => expect(target.textContent).toContain('Making your cover…'));
	});

	it('keeps replacement suggestions reachable when the album already has a cover', async () => {
		albumList.set([
			album({
				id: 'a-local',
				title: 'Night Drive',
				cover: { card: '/cover-card.jpg', detail: '/cover-detail.jpg' }
			})
		]);
		fetchAlbumCoverSuggestions.mockResolvedValue(
			coverSuggestions({ suggestions: [{ id: 'replacement', url: '/replacement.png' }] })
		);
		const target = await renderDetail();

		await vi.waitFor(() => expect(target.querySelector('.cover-suggestion')).not.toBeNull());
		expect(target.textContent).toContain('Choose a cover');
	});
});
