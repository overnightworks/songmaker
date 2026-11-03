import { afterEach, describe, expect, it, onTestFinished, vi } from 'vitest';

import { ApiError, NetworkError, apiUpload } from './fetch';
import { type FakeUploadRequest, sentUpload, uploadAnswers } from '#lib/test-utils/network.ts';

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('apiUpload', () => {
	const upload = (onProgress: (fraction: number) => void = () => undefined) => {
		const form = new FormData();
		const settled = apiUpload<{ id: string }>('/api/references', form, onProgress);
		return { settled, form, request: sentUpload() };
	};

	it('posts the form with the session cookie, reports the share sent and resolves with the answer', async () => {
		uploadAnswers({ status: 200, body: '{"id":"r1"}' });
		const fractions: number[] = [];
		const { settled, form, request } = upload((fraction) => fractions.push(fraction));
		const sentSoFar = (loaded: number, total: number, lengthComputable = true) =>
			request.upload.onprogress?.({ lengthComputable, loaded, total } as ProgressEvent);

		sentSoFar(25, 100);
		sentSoFar(50, 0, false);
		sentSoFar(100, 100);
		request.onload?.();

		await expect(settled).resolves.toEqual({ id: 'r1' });
		expect(fractions).toEqual([0.25, 1]);
		expect(request).toMatchObject({
			opened: ['POST', '/api/references'],
			withCredentials: true,
			sentBody: form
		});
	});

	it('rejects a refusal as the ApiError apiFetch would raise, with the server detail and Retry-After', async () => {
		uploadAnswers({
			status: 409,
			body: '{"detail":"Reference audio storage limit reached."}',
			retryAfter: '7'
		});
		const { settled, request } = upload();

		request.onload?.();
		const failure = await settled.catch((e: unknown) => e);

		expect(failure).toBeInstanceOf(ApiError);
		expect(failure).toMatchObject({
			status: 409,
			detail: 'Reference audio storage limit reached.',
			path: '/api/references',
			retryAfterSeconds: 7
		});
	});

	it.each([
		{ failed: 'onerror', reason: 'unreachable' },
		{ failed: 'onabort', reason: 'unreachable' }
	] as const)(
		'rejects as a $reason NetworkError when the request fails by $failed',
		async ({ failed, reason }) => {
			uploadAnswers({ status: 0, body: '' });
			const { settled, request } = upload();

			request[failed]?.();

			const failure = await settled.catch((e: unknown) => e);
			expect(failure).toBeInstanceOf(NetworkError);
			expect(failure).toMatchObject({ path: '/api/references', reason });
		}
	);
});

describe('apiUpload silence limit', () => {
	const LIMIT_MS = 30_000;

	function startUpload() {
		vi.useFakeTimers();
		onTestFinished(() => {
			vi.useRealTimers();
		});
		uploadAnswers({ status: 200, body: '{}' });
		const settled = apiUpload('/api/references', new FormData(), () => undefined, LIMIT_MS);
		return { settled, request: sentUpload() };
	}
	const progress = (request: FakeUploadRequest) =>
		request.upload.onprogress?.({ lengthComputable: true, loaded: 1, total: 2 } as ProgressEvent);

	it('stays alive past the limit in total while progress keeps arriving, the last event included', async () => {
		const { settled, request } = startUpload();
		let outcome = 'pending';
		void settled.then(
			() => (outcome = 'resolved'),
			() => (outcome = 'rejected')
		);

		for (let sent = 0; sent < 4; sent += 1) {
			await vi.advanceTimersByTimeAsync(LIMIT_MS - 1);
			progress(request);
		}
		await vi.advanceTimersByTimeAsync(LIMIT_MS - 1);

		expect(outcome).toBe('pending');
		request.onload?.();
		await expect(settled).resolves.toEqual({});
	});

	it('ends as a timeout NetworkError after the limit without progress', async () => {
		const { settled, request } = startUpload();
		await vi.advanceTimersByTimeAsync(LIMIT_MS - 1);
		progress(request);

		const failure = settled.catch((e: unknown) => e);
		await vi.advanceTimersByTimeAsync(LIMIT_MS);

		expect(await failure).toBeInstanceOf(NetworkError);
		expect(await failure).toMatchObject({ path: '/api/references', reason: 'timeout' });
	});
});
