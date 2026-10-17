import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

import {
	fetchSharedCollection,
	sharedCollectionFailure,
	type SharedCollectionFailure,
	type SharedCollectionKind
} from './shared';

beforeEach(() => {
	mockFetch.mockReset();
});

describe('the share client reading a collection', () => {
	function serverAnswers(status: number, body: unknown = {}) {
		return () =>
			Promise.resolve({
				ok: status < 400,
				status,
				headers: { get: () => null },
				json: () => Promise.resolve(body)
			});
	}

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
