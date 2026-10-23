import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
	coverJob,
	coverSuggestions,
	deferred,
	FakeJobEventSource
} from '$lib/test-utils/album-cover-editor';
import {
	beginCoverSave,
	coverActivity,
	coverStanding,
	endCoverSave,
	readCoverActivity,
	savingCoverAlbumId,
	watchCoverActivity
} from './coverActivity';
import { activeJobs, removeJob } from './jobs';

const fetchAlbumCoverSuggestions = vi.fn();
vi.mock('$lib/api/albums', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/albums')>()),
	fetchAlbumCoverSuggestions: (...args: unknown[]) => fetchAlbumCoverSuggestions(...args)
}));

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

	it('keeps a save busy until its own album ends it', () => {
		beginCoverSave('a-local');
		endCoverSave('a-other');
		expect(get(savingCoverAlbumId)).toBe('a-local');

		endCoverSave('a-local');
		expect(get(savingCoverAlbumId)).toBeNull();
	});
});
