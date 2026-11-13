// When a cover suggestion cannot run, the editor names one of the agent's
// problems in its own words and tone, never the job's stored error: at the
// click, for the run this page followed, and for a stored run on the next load.

import { makeAlbum as album, makeSong as song } from '#lib/test-utils/factories.ts';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '#lib/api/fetch.ts';
import { resetConnectivityForTests } from '#lib/stores/connectivity.ts';
import { albumList, resetLibraryDataForTests, songList } from '#lib/stores/libraryData.ts';
import { selectedAlbumId } from '#lib/stores/player.ts';
import { activeJobs } from '#lib/stores/jobs.ts';
import { words } from '#lib/words/en.ts';
import { accessibleName } from '#lib/test-utils/accessible-name.ts';
import {
	FakeJobEventSource,
	coverJob,
	coverSuggestions,
	editingClosed,
	openCoverEditing,
	editorButton,
	pressEditorButton,
	pressSuggestOnceLoaded
} from '#lib/test-utils/album-cover-editor.ts';
import { createComponentMount, requireElement } from './shell/rail-test-fixtures';

const fetchAlbumCoverSuggestions = vi.fn();
const createAlbumCoverSuggestions = vi.fn();

vi.mock('#lib/api/songs.ts', () => ({
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false })
}));
vi.mock('#lib/api/albums.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/albums.ts')>()),
	fetchAlbumCoverSuggestions: (...args: unknown[]) => fetchAlbumCoverSuggestions(...args),
	createAlbumCoverSuggestions: (...args: unknown[]) => createAlbumCoverSuggestions(...args)
}));
vi.mock('#lib/stores/toast.ts', () => ({ addToast: vi.fn(), addUndoToast: vi.fn() }));

import AlbumDetailView from './AlbumDetailView.svelte';

const { render: renderDetail, cleanup } = createComponentMount(AlbumDetailView);

beforeEach(() => {
	albumList.set([album({ id: 'a-local', title: 'Night Drive' })]);
	songList.set([
		song({ id: 's-local', album_id: 'a-local', album_title: 'Night Drive', generation_count: 1 })
	]);
	selectedAlbumId.set('a-local');
	fetchAlbumCoverSuggestions.mockReset().mockResolvedValue(coverSuggestions());
	createAlbumCoverSuggestions.mockReset();
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

describe('a cover suggestion that cannot run names one of the agent’s problems', () => {
	const BUSY_TEXT = words['coverProblem.busy'];
	const NOT_ENABLED_TEXT = words['coverProblem.notEnabled'];
	const UNAVAILABLE_TEXT = words['coverProblem.unavailable'];
	const BUDGET_SPENT_TEXT = words['coverProblem.budgetSpent'];
	const SIGN_IN_TEXT = words['coverProblem.signInAgain'];
	const LEAKED_ERROR = 'gateway said 500 for key sk-canary';

	function suggestButton(target: HTMLElement): HTMLButtonElement {
		const button = Array.from(
			requireElement(target, '.cover-actions').querySelectorAll<HTMLButtonElement>('button')
		).find((el) => accessibleName(el).startsWith(words['albumCover.suggest']));
		if (!button) throw new Error('Expected the Suggest button');
		return button;
	}

	function problemLine(target: HTMLElement): HTMLElement | null {
		return target.querySelector('.cover-editor .turn-error');
	}

	function refusedWith(status: number, problem: string | null): ApiError {
		const detail = problem === null ? LEAKED_ERROR : { problem };
		return new ApiError(
			status,
			LEAKED_ERROR,
			'/api/albums/a-local/cover-suggestions',
			null,
			detail
		);
	}

	it.each([
		{ problem: 'not_enabled', status: 403, text: NOT_ENABLED_TEXT, tone: 'off', closed: true },
		{ problem: 'sign_in_again', status: 403, text: SIGN_IN_TEXT, tone: 'bad', closed: true },
		{ problem: 'unavailable', status: 503, text: UNAVAILABLE_TEXT, tone: 'wait', closed: false },
		{ problem: null, status: 500, text: UNAVAILABLE_TEXT, tone: 'wait', closed: false },
		{ problem: null, status: 422, text: UNAVAILABLE_TEXT, tone: 'wait', closed: false }
	])(
		'a click answered $status $problem shows its line in its tone, makes no run, and Suggest closed: $closed',
		async ({ problem, status, text, tone, closed }) => {
			createAlbumCoverSuggestions.mockRejectedValue(refusedWith(status, problem));
			const target = await renderDetail();
			await openCoverEditing(target);

			await pressSuggestOnceLoaded(target);

			await vi.waitFor(() => expect(problemLine(target)?.textContent).toContain(text));
			expect(problemLine(target)?.classList.contains(tone)).toBe(true);
			expect(suggestButton(target).disabled).toBe(closed);
			expect(target.querySelector('.cover-editor .bad')).toEqual(
				problem === 'sign_in_again' ? problemLine(target) : null
			);
			expect(FakeJobEventSource.sources).toHaveLength(0);
			expect(target.querySelector('.cover-failure')).toBeNull();
			expect(target.textContent).not.toContain(LEAKED_ERROR);
		}
	);

	it('a click refused for a lost sign-in offers Log in and keeps the rest of the album working', async () => {
		createAlbumCoverSuggestions.mockRejectedValue(refusedWith(403, 'sign_in_again'));
		const target = await renderDetail();
		await openCoverEditing(target);

		await pressSuggestOnceLoaded(target);

		await vi.waitFor(() => expect(problemLine(target)).not.toBeNull());
		const login = requireElement<HTMLAnchorElement>(problemLine(target) as HTMLElement, 'a');
		expect(login.textContent?.trim()).toBe(words['problemLine.logIn']);
		expect(editorButton(target, words['albumCover.upload']).disabled).toBe(false);
		expect(target.textContent).not.toContain(words['problemLine.tryAgain']);
	});

	it.each([
		{ problem: 'unavailable', text: UNAVAILABLE_TEXT, tone: 'wait' },
		{ problem: 'budget_spent', text: BUDGET_SPENT_TEXT, tone: 'wait' },
		{ problem: 'not_enabled', text: NOT_ENABLED_TEXT, tone: 'off' },
		{ problem: 'sign_in_again', text: SIGN_IN_TEXT, tone: 'bad' }
	])(
		'the run this page followed that ended $problem names it in its own words, never the job error',
		async ({ problem, text, tone }) => {
			vi.stubGlobal('EventSource', FakeJobEventSource);
			createAlbumCoverSuggestions.mockResolvedValue(coverJob({ status: 'queued' }));
			const target = await renderDetail();
			await openCoverEditing(target);
			await pressSuggestOnceLoaded(target);
			const ended = coverJob({ status: 'failed', error: LEAKED_ERROR, error_type: problem });
			fetchAlbumCoverSuggestions.mockResolvedValue(coverSuggestions({ job: ended }));
			await vi.waitFor(() => expect(FakeJobEventSource.sources).toHaveLength(1));

			FakeJobEventSource.sources[0].emit(ended);

			await vi.waitFor(() => expect(problemLine(target)?.textContent).toContain(text));
			expect(problemLine(target)?.classList.contains(tone)).toBe(true);
			expect(target.textContent).not.toContain(LEAKED_ERROR);
		}
	);

	it.each(['not_enabled', 'sign_in_again'])(
		'a stored run that ended %s leaves Suggest open on the next load',
		async (problem) => {
			fetchAlbumCoverSuggestions.mockResolvedValue(
				coverSuggestions({
					job: coverJob({ status: 'failed', error: LEAKED_ERROR, error_type: problem })
				})
			);
			const target = await renderDetail();
			await openCoverEditing(target);

			await vi.waitFor(() => expect(suggestButton(target).disabled).toBe(false));
			expect(problemLine(target)).toBeNull();
		}
	);

	it('a busy run counts down the wait it was given across a reopening and opens Suggest at 0:00', async () => {
		vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] });
		const endedAt = Date.parse('2026-11-05T12:00:00Z');
		vi.setSystemTime(endedAt + 2_000);
		fetchAlbumCoverSuggestions.mockResolvedValue(
			coverSuggestions({
				job: coverJob({
					status: 'failed',
					error: LEAKED_ERROR,
					error_type: 'busy',
					retry_after_seconds: 44,
					completed_at: new Date(endedAt).toISOString()
				})
			})
		);
		const target = await renderDetail();
		await openCoverEditing(target);

		await vi.waitFor(() => expect(problemLine(target)?.textContent).toContain(BUSY_TEXT));
		expect(problemLine(target)?.classList.contains('wait')).toBe(true);
		expect(suggestButton(target).disabled).toBe(true);
		expect(accessibleName(suggestButton(target))).toContain('0:42');

		pressEditorButton(target, words['albumCover.editingClose']);
		await editingClosed(target);
		await vi.advanceTimersByTimeAsync(30_000);
		await openCoverEditing(target);
		await vi.waitFor(() => expect(accessibleName(suggestButton(target))).toContain('0:12'));

		await vi.advanceTimersByTimeAsync(12_000);

		await vi.waitFor(() => expect(suggestButton(target).disabled).toBe(false));
		expect(problemLine(target)).toBeNull();
		expect(accessibleName(suggestButton(target))).toBe(words['albumCover.suggest']);
	});
});
