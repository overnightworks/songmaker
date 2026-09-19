import { makeGeneration as generation, makeSong as song } from '$lib/test-utils/factories';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import type { GenerationItem, SongItem } from '$lib/api/types';

vi.mock('$lib/api/client', () => ({
	fetchSong: vi.fn(),
	pickGeneration: vi.fn(),
	unpickGeneration: vi.fn(),
	keepGeneration: vi.fn(),
	unkeepGeneration: vi.fn(),
	rateGeneration: vi.fn(),
	scoreGeneration: vi.fn()
}));

import type { JobStatus } from '$lib/api/client';
import {
	fetchSong,
	keepGeneration,
	pickGeneration,
	rateGeneration,
	scoreGeneration,
	unkeepGeneration,
	unpickGeneration
} from '$lib/api/client';
import { pinnedSeed } from '$lib/stores/editor';
import { songList } from '$lib/stores/libraryData';
import { toasts } from '$lib/stores/toast';
import { activeJobs } from '$lib/stores/jobs';
import { pinSeed, rate, rescore, rescoringTakeIds, setKeep, setPick } from './takeActions';

const generationDefaults = {
	mp3_path: 'a.mp3',
	seed: 42,
	model_mode: 'sft',
	version_lyrics: 'la la',
	created_at: ''
} satisfies Partial<GenerationItem>;

const songDefaults = {
	slug: 'tide',
	title: 'Tide',
	album_title: 'Nachtstrom',
	lyrics: 'la la',
	prompt: 'dreamy',
	created_at: '',
	generations: [generation(generationDefaults)]
} satisfies Partial<SongItem>;

// The score job's progress arrives over a server-sent event stream jsdom does
// not implement, so the store gets an EventSource that records nothing.
class SilentEventSource {
	close(): void {}
}

function scoreJob(overrides: Partial<JobStatus> = {}): JobStatus {
	return {
		id: 'j1',
		type: 'score',
		status: 'queued',
		progress: 0,
		error: null,
		error_type: null,
		started_at: null,
		completed_at: null,
		...overrides
	};
}

beforeEach(() => {
	songList.set([]);
	toasts.set([]);
	pinnedSeed.set(null);
	activeJobs.set([]);
	vi.stubGlobal('EventSource', SilentEventSource);
	vi.clearAllMocks();
});

afterEach(() => {
	songList.set([]);
	pinnedSeed.set(null);
	activeJobs.set([]);
	vi.unstubAllGlobals();
});

describe('setPick', () => {
	it('picks a generation and refreshes the song into songList', async () => {
		vi.mocked(fetchSong).mockResolvedValue(
			song({
				...structuredClone(songDefaults),
				generations: [generation({ ...generationDefaults, is_picked: true })]
			})
		);

		await setPick('s1', 'g1', true);

		expect(pickGeneration).toHaveBeenCalledWith('g1');
		expect(unpickGeneration).not.toHaveBeenCalled();
		expect(get(songList)[0]?.generations[0]?.is_picked).toBe(true);
	});

	it('unpicks a generation', async () => {
		vi.mocked(fetchSong).mockResolvedValue(song(structuredClone(songDefaults)));

		await setPick('s1', 'g1', false);

		expect(unpickGeneration).toHaveBeenCalledWith('g1');
		expect(pickGeneration).not.toHaveBeenCalled();
	});

	it('toasts and leaves songList unchanged when the API call fails', async () => {
		vi.mocked(pickGeneration).mockRejectedValue(new Error('boom'));
		songList.set([song(structuredClone(songDefaults))]);

		await setPick('s1', 'g1', true);

		expect(fetchSong).not.toHaveBeenCalled();
		expect(get(songList)).toEqual([song(structuredClone(songDefaults))]);
		expect(get(toasts)).toEqual([expect.objectContaining({ message: 'boom', type: 'error' })]);
	});
});

describe('setKeep', () => {
	it('keeps a generation and refreshes the song into songList', async () => {
		vi.mocked(fetchSong).mockResolvedValue(
			song({
				...structuredClone(songDefaults),
				generations: [generation({ ...generationDefaults, is_kept: true })]
			})
		);

		await setKeep('s1', 'g1', true);

		expect(keepGeneration).toHaveBeenCalledWith('g1');
		expect(get(songList)[0]?.generations[0]?.is_kept).toBe(true);
	});

	it('unkeeps a generation', async () => {
		vi.mocked(fetchSong).mockResolvedValue(song(structuredClone(songDefaults)));

		await setKeep('s1', 'g1', false);

		expect(unkeepGeneration).toHaveBeenCalledWith('g1');
	});

	it('toasts on failure', async () => {
		vi.mocked(keepGeneration).mockRejectedValue(new Error('nope'));

		await setKeep('s1', 'g1', true);

		expect(get(toasts)).toEqual([expect.objectContaining({ message: 'nope', type: 'error' })]);
	});
});

describe('rate', () => {
	it('rates a generation, refreshes songList, and confirms via toast', async () => {
		vi.mocked(fetchSong).mockResolvedValue(song(structuredClone(songDefaults)));

		await rate('s1', 'g1', 80, 'great take');

		expect(rateGeneration).toHaveBeenCalledWith('g1', 80, 'great take');
		expect(get(songList)).toEqual([song(structuredClone(songDefaults))]);
		expect(get(toasts)).toEqual([
			expect.objectContaining({ message: 'Rating saved', type: 'success' })
		]);
	});

	it('defaults notes to an empty string', async () => {
		vi.mocked(fetchSong).mockResolvedValue(song(structuredClone(songDefaults)));

		await rate('s1', 'g1', 50);

		expect(rateGeneration).toHaveBeenCalledWith('g1', 50, '');
	});

	it('toasts on failure and leaves songList unchanged', async () => {
		vi.mocked(rateGeneration).mockRejectedValue(new Error('rating failed'));
		songList.set([song(structuredClone(songDefaults))]);

		await rate('s1', 'g1', 80);

		expect(fetchSong).not.toHaveBeenCalled();
		expect(get(toasts)).toEqual([
			expect.objectContaining({ message: 'rating failed', type: 'error' })
		]);
	});
});

describe('pinSeed', () => {
	it('pins the seed for the next generation and confirms via toast', () => {
		pinSeed(48113);

		expect(get(pinnedSeed)).toBe(48113);
		expect(get(toasts)).toEqual([
			expect.objectContaining({ message: 'Seed 48113 pinned for next generation', type: 'success' })
		]);
	});
});

describe('rescore', () => {
	it('marks the take as re-scoring until its scoring job leaves the queue', async () => {
		vi.mocked(scoreGeneration).mockResolvedValue(scoreJob());

		await rescore('s1', 'g1');

		expect(scoreGeneration).toHaveBeenCalledWith('g1');
		expect(get(rescoringTakeIds).has('g1')).toBe(true);
		expect(get(toasts)).toEqual([
			expect.objectContaining({ message: 'Re-scoring this take…', type: 'info' })
		]);

		activeJobs.set([]);
		expect(get(rescoringTakeIds).has('g1')).toBe(false);
	});

	it('leaves other takes unmarked while one is re-scoring', async () => {
		vi.mocked(scoreGeneration).mockResolvedValue(scoreJob());

		await rescore('s1', 'g1');

		expect(get(rescoringTakeIds).has('g2')).toBe(false);
	});

	it('asks for one scoring job however often the take is clicked mid-request', async () => {
		let acceptRequest: (job: JobStatus) => void = () => {};
		vi.mocked(scoreGeneration).mockReturnValue(
			new Promise<JobStatus>((resolve) => {
				acceptRequest = resolve;
			})
		);

		const first = rescore('s1', 'g1');
		const second = rescore('s1', 'g1');
		const third = rescore('s1', 'g1');

		expect(scoreGeneration).toHaveBeenCalledTimes(1);
		expect(get(rescoringTakeIds).has('g1')).toBe(true);

		acceptRequest(scoreJob());
		await Promise.all([first, second, third]);

		expect(scoreGeneration).toHaveBeenCalledTimes(1);
		expect(get(rescoringTakeIds).has('g1')).toBe(true);
	});

	it('lets the take be re-scored again after a rejected request', async () => {
		vi.mocked(scoreGeneration).mockRejectedValueOnce(new Error('queue is full'));

		await rescore('s1', 'g1');
		expect(get(rescoringTakeIds).has('g1')).toBe(false);

		vi.mocked(scoreGeneration).mockResolvedValueOnce(scoreJob());
		await rescore('s1', 'g1');

		expect(scoreGeneration).toHaveBeenCalledTimes(2);
		expect(get(rescoringTakeIds).has('g1')).toBe(true);
	});

	it('toasts the error and marks nothing when the job is rejected', async () => {
		vi.mocked(scoreGeneration).mockRejectedValue(new Error('queue is full'));

		await rescore('s1', 'g1');

		expect(get(rescoringTakeIds).size).toBe(0);
		expect(get(toasts)).toEqual([
			expect.objectContaining({ message: 'queue is full', type: 'error' })
		]);
	});
});
