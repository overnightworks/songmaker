import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, NetworkError } from '#lib/api/fetch.ts';
import type { ReferenceRecordingResponse } from '#lib/api/types.ts';
import { UNREACHABLE_RELOAD_DELAYS_MS } from '#lib/constants.ts';
import {
	reportResourceStreamReachable,
	resetConnectivityForTests
} from '#lib/stores/connectivity.ts';

const mocks = vi.hoisted(() => ({ listReferences: vi.fn() }));

vi.mock('#lib/api/references.ts', () => ({
	listReferences: (...args: unknown[]) => mocks.listReferences(...args)
}));

import ReferencesPage from './+page.svelte';

let mounted: ReturnType<typeof mount> | undefined;

function referenceRecording(
	overrides: Partial<ReferenceRecordingResponse>
): ReferenceRecordingResponse {
	return {
		id: 'reference-1',
		filename: 'voice-memo.mp3',
		size_bytes: 1000,
		duration_sec: 31.4,
		created_at: '2026-10-27T10:00:00Z',
		...overrides
	};
}

async function renderReferencesPage(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(ReferencesPage, { target });
	await tick();
	return target;
}

function listedReferences(target: HTMLElement): { name: string; meta: string }[] {
	return Array.from(target.querySelectorAll('.reference-row')).map((row) => ({
		name: row.querySelector('.reference-name')?.textContent ?? '',
		meta: row.querySelector('.reference-meta')?.textContent ?? ''
	}));
}

beforeEach(() => {
	vi.stubEnv('TZ', 'UTC');
	mocks.listReferences.mockReset();
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	resetConnectivityForTests();
	vi.useRealTimers();
	vi.unstubAllEnvs();
});

describe('references page', () => {
	it('lists each reference with its filename, length and upload day, in the order served', async () => {
		mocks.listReferences.mockResolvedValue([
			referenceRecording({ id: 'a', filename: 'voice-memo.mp3', duration_sec: 31.4 }),
			referenceRecording({
				id: 'b',
				filename: 'storytime-drums.wav',
				duration_sec: 62,
				created_at: '2026-10-14T08:00:00Z'
			})
		]);
		const target = await renderReferencesPage();
		await vi.waitFor(() => expect(listedReferences(target)).toHaveLength(2));

		expect(listedReferences(target)).toEqual([
			{ name: 'voice-memo.mp3', meta: '0:31 · 27 Oct' },
			{ name: 'storytime-drums.wav', meta: '1:02 · 14 Oct' }
		]);
		expect(target.querySelector('h1')?.textContent).toBe('References');
	});

	it('shows a dash for a reference whose length is unknown', async () => {
		mocks.listReferences.mockResolvedValue([referenceRecording({ duration_sec: null })]);
		const target = await renderReferencesPage();
		await vi.waitFor(() => expect(listedReferences(target)).toHaveLength(1));

		expect(listedReferences(target)[0].meta).toBe('— · 27 Oct');
	});

	it('shows the loading line until the read answers', async () => {
		mocks.listReferences.mockReturnValue(new Promise(() => {}));
		const target = await renderReferencesPage();

		expect(target.querySelector('.loading')?.textContent).toBe('Loading references...');
		expect(target.querySelector('.empty')).toBeNull();
	});

	it('says what references are for once the read answered with none', async () => {
		mocks.listReferences.mockResolvedValue([]);
		const target = await renderReferencesPage();

		await vi.waitFor(() =>
			expect(target.querySelector('.empty')?.textContent?.trim()).toBe(
				"No references yet — upload a recording to guide a song's sound."
			)
		);
		expect(target.querySelector('.loading')).toBeNull();
	});

	it('names a read the server refused in its own words and claims no empty list', async () => {
		mocks.listReferences.mockRejectedValue(
			new ApiError(503, 'Reference storage is offline', '/api/references')
		);
		const target = await renderReferencesPage();

		await vi.waitFor(() =>
			expect(target.querySelector('.error')?.textContent).toBe('Reference storage is offline')
		);
		expect(target.querySelector('.empty')).toBeNull();
	});

	it('names the failed read when the server stays unreachable, then lists once back online', async () => {
		vi.useFakeTimers();
		mocks.listReferences.mockRejectedValue(
			new NetworkError('/api/references', new TypeError('Failed to fetch'))
		);
		const target = await renderReferencesPage();
		for (const delay of UNREACHABLE_RELOAD_DELAYS_MS) await vi.advanceTimersByTimeAsync(delay);

		expect(target.querySelector('.error')?.textContent).toBe('Failed to load references');
		expect(target.querySelector('.empty')).toBeNull();

		mocks.listReferences.mockResolvedValue([referenceRecording({})]);
		reportResourceStreamReachable(false);
		reportResourceStreamReachable(true);
		await vi.waitFor(() => expect(listedReferences(target)).toHaveLength(1));

		expect(target.querySelector('.error')).toBeNull();
	});
});
