import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

import { hangsUntilAborted } from '#lib/test-utils/network.ts';
import { ApiError, NetworkError } from './fetch';
import {
	fetchSharedCollection,
	fetchSharedStream,
	sharedCollectionFailure,
	type SharedCollectionFailure,
	type SharedCollectionKind
} from './shared';

function serverAnswers(status: number, body: unknown = {}) {
	return () =>
		Promise.resolve({
			ok: status < 400,
			status,
			headers: { get: () => null },
			json: () => Promise.resolve(body)
		});
}

beforeEach(() => {
	mockFetch.mockReset();
});

describe('the share client reading a collection', () => {
	const SHARE_ADDRESSES: Array<{ kind: SharedCollectionKind; address: string }> = [
		{ kind: 'album', address: '/shared/some-slug' },
		{ kind: 'playlist', address: '/shared/playlist/some-slug' },
		{ kind: 'song', address: '/shared/song/some-slug' },
		{ kind: 'take', address: '/shared/gen/some-slug' }
	];

	it.each(SHARE_ADDRESSES)(
		'925_M2_C1: a $kind share reads $address and returns its payload',
		async ({ kind, address }) => {
			mockFetch.mockImplementation(serverAnswers(200, { title: `a ${kind}` }));

			const payload = await fetchSharedCollection(kind, 'some-slug');

			expect(payload).toEqual({ title: `a ${kind}` });
			expect(mockFetch.mock.calls[0][0]).toBe(address);
		}
	);

	const FAILED_READS: Array<{
		happens: string;
		answer: () => Promise<unknown>;
		failure: SharedCollectionFailure;
	}> = [
		{ happens: 'a 404', answer: serverAnswers(404), failure: 'missing' },
		{ happens: 'a 401', answer: serverAnswers(401), failure: 'error' },
		{ happens: 'a 429', answer: serverAnswers(429), failure: 'error' },
		{ happens: 'a 500', answer: serverAnswers(500), failure: 'error' },
		{ happens: 'a 503', answer: serverAnswers(503), failure: 'error' },
		{
			happens: 'an unreachable server',
			answer: () => Promise.reject(new TypeError('Failed to fetch')),
			failure: 'error'
		}
	];

	it.each(FAILED_READS)('925_M2_C2: $happens reads as $failure', async ({ answer, failure }) => {
		mockFetch.mockImplementation(answer);

		const reason = await fetchSharedCollection('album', 'some-slug').catch((e: unknown) => e);

		expect(sharedCollectionFailure(reason)).toBe(failure);
	});
});

describe('the share client building a stream', () => {
	const STREAM_ADDRESSES = [
		{ kind: 'album', address: '/shared/some-slug/stream' },
		{ kind: 'playlist', address: '/shared/playlist/some-slug/stream' }
	] as const;

	afterEach(() => {
		vi.useRealTimers();
	});

	it.each(STREAM_ADDRESSES)(
		'925_M2_S1: a $kind stream POSTs $address and returns the manifest',
		async ({ kind, address }) => {
			mockFetch.mockImplementation(serverAnswers(200, { snapshot_id: 'snap-1' }));

			const manifest = await fetchSharedStream(kind, 'some-slug');

			const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
			expect([manifest, url, init.method]).toEqual([{ snapshot_id: 'snap-1' }, address, 'POST']);
		}
	);

	it.each(STREAM_ADDRESSES)(
		'925_M2_S1: a refused $kind build rejects with its ApiError',
		async ({ kind }) => {
			mockFetch.mockImplementation(serverAnswers(503));

			const failure = await fetchSharedStream(kind, 'some-slug').catch((e: unknown) => e);

			expect(failure).toBeInstanceOf(ApiError);
			expect(failure).toMatchObject({ status: 503 });
		}
	);

	it.each(STREAM_ADDRESSES)(
		'925_M2_S2: a $kind stream build is kept alive for its 120 second budget',
		async ({ kind }) => {
			vi.useFakeTimers();
			mockFetch.mockImplementation(hangsUntilAborted);

			const outcome = fetchSharedStream(kind, 'some-slug').catch((e: unknown) => e);
			const signal = (mockFetch.mock.calls[0][1] as RequestInit).signal as AbortSignal;
			await vi.advanceTimersByTimeAsync(119_999);
			expect(signal.aborted).toBe(false);
			await vi.advanceTimersByTimeAsync(1);

			expect(signal.aborted).toBe(true);
			expect(await outcome).toBeInstanceOf(NetworkError);
			expect(await outcome).toMatchObject({ reason: 'timeout' });
		}
	);
});
