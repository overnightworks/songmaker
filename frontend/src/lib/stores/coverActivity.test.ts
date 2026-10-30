import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
	coverJob,
	coverSuggestions,
	deferred,
	FakeJobEventSource
} from '#lib/test-utils/album-cover-editor.ts';
import {
	beginCoverSave,
	beginCoverSuggestion,
	coverActivity,
	coverStanding,
	discardCoverSuggestions,
	endCoverSave,
	endCoverSuggestion,
	followCoverRun,
	knownAfterSave,
	readCoverActivity,
	savingCoverAlbumIds,
	showCoverActivityFailure,
	watchCoverActivity
} from './coverActivity';
import { NetworkError } from '#lib/api/fetch.ts';
import { activeJobs, removeJob } from './jobs';

const fetchAlbumCoverSuggestions = vi.fn();
const discardAlbumCoverSuggestions = vi.fn();
vi.mock('#lib/api/albums.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/albums.ts')>()),
	fetchAlbumCoverSuggestions: (...args: unknown[]) => fetchAlbumCoverSuggestions(...args),
	discardAlbumCoverSuggestions: (...args: unknown[]) => discardAlbumCoverSuggestions(...args)
}));
vi.mock('#lib/api/jobs.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/jobs.ts')>()),
	cancelJob: async () => coverJob({ status: 'cancelled' })
}));

type Deletion = ReturnType<typeof deferred<unknown>>;

const RUNNING = coverJob({ status: 'running', started_at: '2026-10-22T10:00:00Z' });

let stopWatching: (() => void) | undefined;

function watch(albumId = 'a-local'): void {
	stopWatching = watchCoverActivity(albumId);
}

function backInTheForeground(): void {
	document.dispatchEvent(new Event('visibilitychange'));
}

async function settled(): Promise<void> {
	await vi.waitFor(() => expect(get(coverActivity)?.isLoading).toBe(false));
}

beforeEach(() => {
	vi.stubGlobal('EventSource', FakeJobEventSource);
	fetchAlbumCoverSuggestions.mockReset().mockResolvedValue(coverSuggestions());
	discardAlbumCoverSuggestions.mockReset().mockResolvedValue(undefined);
	activeJobs.set([]);
	FakeJobEventSource.sources.length = 0;
});

afterEach(() => {
	stopWatching?.();
	stopWatching = undefined;
	vi.unstubAllGlobals();
	activeJobs.set([]);
});

describe('the watched album cover state', () => {
	it('reads on mount', async () => {
		watch();
		await settled();

		expect(fetchAlbumCoverSuggestions).toHaveBeenCalledExactlyOnceWith('a-local');
		expect(get(coverActivity)).toMatchObject({ albumId: 'a-local', data: coverSuggestions() });
	});

	it('reads again when the page becomes visible and when it gains focus', async () => {
		watch();
		await settled();

		backInTheForeground();
		await vi.waitFor(() => expect(fetchAlbumCoverSuggestions).toHaveBeenCalledTimes(2));
		window.dispatchEvent(new Event('focus'));
		await vi.waitFor(() => expect(fetchAlbumCoverSuggestions).toHaveBeenCalledTimes(3));
	});

	it('does not read when the page goes to the background', async () => {
		watch();
		await settled();
		vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');

		backInTheForeground();
		await Promise.resolve();

		expect(fetchAlbumCoverSuggestions).toHaveBeenCalledTimes(1);
		vi.restoreAllMocks();
	});

	it('stops reading once the page is left', async () => {
		watch();
		await settled();
		stopWatching?.();
		stopWatching = undefined;

		backInTheForeground();
		window.dispatchEvent(new Event('focus'));
		await Promise.resolve();

		expect(fetchAlbumCoverSuggestions).toHaveBeenCalledTimes(1);
	});

	it('tracks a running job the server reports', async () => {
		fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions({ job: RUNNING }));
		watch();
		await settled();

		expect(get(activeJobs)).toMatchObject([{ albumId: 'a-local', job: { id: 'cover-job' } }]);
		expect(get(coverStanding)).toMatchObject({
			running: true,
			startedAt: RUNNING.started_at,
			waiting: 0
		});
	});

	it('reads again when the run it tracks ends', async () => {
		fetchAlbumCoverSuggestions.mockResolvedValueOnce(coverSuggestions({ job: RUNNING }));
		watch();
		await settled();
		fetchAlbumCoverSuggestions.mockResolvedValue(
			coverSuggestions({ suggestions: [{ id: 'made', url: '/made.png' }] })
		);

		removeJob('cover-job');

		await vi.waitFor(() =>
			expect(get(coverStanding)).toMatchObject({ running: false, waiting: 1 })
		);
		expect(fetchAlbumCoverSuggestions).toHaveBeenCalledTimes(2);
	});

	it('drops the answer of a read that a newer read overtook', async () => {
		const first = deferred<ReturnType<typeof coverSuggestions>>();
		fetchAlbumCoverSuggestions.mockReturnValueOnce(first.promise);
		watch();
		fetchAlbumCoverSuggestions.mockResolvedValue(
			coverSuggestions({ suggestions: [{ id: 'newer', url: '/newer.png' }] })
		);
		await readCoverActivity('a-local');

		first.resolve(coverSuggestions({ suggestions: [] }));
		await Promise.resolve();

		expect(get(coverActivity)?.data?.suggestions).toEqual([{ id: 'newer', url: '/newer.png' }]);
	});

	it('drops the answer for an album that is no longer watched', async () => {
		const stale = deferred<ReturnType<typeof coverSuggestions>>();
		fetchAlbumCoverSuggestions.mockReturnValueOnce(stale.promise);
		watch('a-first');
		stopWatching?.();
		fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions());
		watch('a-second');
		await settled();

		stale.resolve(coverSuggestions({ job: RUNNING }));
		await Promise.resolve();

		expect(get(coverActivity)).toMatchObject({ albumId: 'a-second', runId: null });
		expect(get(activeJobs)).toEqual([]);
	});

	it('keeps every pending save busy until its own album ends it', () => {
		beginCoverSave('a-local');
		beginCoverSave('a-other');
		endCoverSave('a-other');
		expect(get(savingCoverAlbumIds).has('a-local')).toBe(true);
		expect(get(savingCoverAlbumIds).has('a-other')).toBe(false);

		endCoverSave('a-local');
		expect(get(savingCoverAlbumIds).size).toBe(0);
	});

	it('keeps the runs a save captured when another album is watched meanwhile', () => {
		watch('a-other');

		const released = knownAfterSave('a-local', { suggestionIds: ['one'], jobIds: ['job-1'] });

		expect(released).toEqual({ suggestionIds: ['one'], jobIds: ['job-1'] });
	});

	it.each([
		{ outcome: 'succeeds', settle: (deletion: Deletion) => deletion.resolve(undefined) },
		{ outcome: 'fails', settle: (deletion: Deletion) => deletion.reject(new Error('gone')) }
	])(
		'a discard that $outcome reads again, so an older read cannot keep the deleted suggestions',
		async ({ settle }) => {
			fetchAlbumCoverSuggestions.mockResolvedValue(
				coverSuggestions({ suggestions: [{ id: 'one', url: '/one.png' }] })
			);
			watch();
			await settled();
			const olderRead = deferred<ReturnType<typeof coverSuggestions>>();
			fetchAlbumCoverSuggestions.mockReturnValueOnce(olderRead.promise);
			void readCoverActivity('a-local');
			const deleting = deferred<unknown>();
			discardAlbumCoverSuggestions.mockReturnValue(deleting.promise);
			const discarding = discardCoverSuggestions('a-local', {
				suggestionIds: ['one'],
				jobIds: []
			}).catch(() => undefined);

			fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions({ suggestions: [] }));
			settle(deleting);
			await discarding;
			olderRead.resolve(coverSuggestions({ suggestions: [{ id: 'one', url: '/one.png' }] }));

			await vi.waitFor(() => expect(get(coverStanding)?.waiting).toBe(0));
			await settled();
			expect(get(coverStanding)?.waiting).toBe(0);
		}
	);

	it('keeps the shown suggestions when a later read fails', async () => {
		fetchAlbumCoverSuggestions.mockResolvedValue(
			coverSuggestions({ suggestions: [{ id: 'one', url: '/one.png' }] })
		);
		watch();
		await settled();
		fetchAlbumCoverSuggestions.mockRejectedValue(
			new NetworkError('/albums', new TypeError('offline'))
		);

		backInTheForeground();

		await vi.waitFor(() => expect(get(coverActivity)?.unreachable).toBe(true));
		expect(get(coverStanding)?.waiting).toBe(1);
	});

	it('stays loading while a Suggest is on its way, whatever a read answers', async () => {
		watch();
		await settled();
		beginCoverSuggestion('a-local');

		backInTheForeground();
		await vi.waitFor(() => expect(fetchAlbumCoverSuggestions).toHaveBeenCalledTimes(2));
		await Promise.resolve();
		await Promise.resolve();
		expect(get(coverActivity)?.isLoading).toBe(true);

		endCoverSuggestion('a-local');
		await readCoverActivity('a-local');
		expect(get(coverActivity)?.isLoading).toBe(false);
	});

	it.each([
		{
			action: 'a discard that stops a run',
			act: () => discardCoverSuggestions('a-first', { suggestionIds: [], jobIds: ['job-a'] })
		},
		{ action: 'a Suggest', act: async () => beginCoverSuggestion('a-first') },
		{ action: 'a reread', act: () => readCoverActivity('a-first') },
		{ action: 'a Suggest that answers', act: async () => followCoverRun(coverJob(), 'a-first') },
		{
			action: 'a Suggest that fails',
			act: async () =>
				showCoverActivityFailure('a-first', new NetworkError('/albums', new TypeError('offline')), {
					keepData: true
				})
		}
	])('$action on another album lets the watched album’s opening read land', async ({ act }) => {
		watch('a-first');
		await settled();
		stopWatching?.();
		const openingRead = deferred<ReturnType<typeof coverSuggestions>>();
		fetchAlbumCoverSuggestions.mockReturnValueOnce(openingRead.promise);
		watch('a-second');

		await act();
		openingRead.resolve(coverSuggestions({ suggestions: [{ id: 'b', url: '/b.png' }] }));

		await settled();
		expect(get(coverActivity)).toMatchObject({
			albumId: 'a-second',
			data: { suggestions: [{ id: 'b' }] }
		});
	});

	it('a discard that names nothing still frees Suggest from the ask it came after', async () => {
		watch();
		await settled();
		beginCoverSuggestion('a-local');

		await discardCoverSuggestions('a-local', { suggestionIds: [], jobIds: [] });

		await settled();
		expect(get(coverActivity)?.suggesting).toBe(false);
		expect(discardAlbumCoverSuggestions).not.toHaveBeenCalled();
	});
});
