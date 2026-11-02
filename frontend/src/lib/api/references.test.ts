import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);
vi.mock('$app/navigation', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation()
);

import { ApiError } from './fetch';
import { listReferences, referenceAudioUrl, uploadReference } from './references';

describe('reference API', () => {
	beforeEach(() => mockFetch.mockReset());

	it('uploads the reference as multipart form data and returns the stored record', async () => {
		const stored = {
			id: 'reference-1',
			filename: 'ref.wav',
			size_bytes: 3,
			duration_sec: null,
			created_at: '2026-11-02T10:00:00+00:00'
		};
		mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(stored) });
		const file = new File(['wav'], 'ref.wav', { type: 'audio/wav' });

		const result = await uploadReference(file);

		const [url, init] = mockFetch.mock.calls[0];
		expect(url).toBe('/api/references');
		expect(init.method).toBe('POST');
		expect((init.body as FormData).get('file')).toBe(file);
		expect(result).toEqual(stored);
	});

	it('lists the stored records and the storage usage as the server answers them', async () => {
		const answer = {
			references: [
				{
					id: 'reference-1',
					filename: 'ref.wav',
					size_bytes: 3,
					duration_sec: 31,
					created_at: '2026-10-27T10:00:00+00:00'
				}
			],
			usage: { files: 1, bytes: 3, file_limit: 50, byte_limit: 500_000_000 }
		};
		mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(answer) });

		const result = await listReferences();

		expect(mockFetch.mock.calls[0][0]).toBe('/api/references');
		expect(result).toEqual(answer);
	});

	describe('with a progress callback', () => {
		let sent: { upload: { onprogress: ((e: ProgressEvent) => void) | null }; onload: () => void }[];
		let answer: { status: number; body: string };

		beforeEach(() => {
			sent = [];
			answer = { status: 200, body: '{"id":"reference-1"}' };
			vi.stubGlobal(
				'XMLHttpRequest',
				class {
					upload = { onprogress: null };
					onload = () => undefined;
					open = () => undefined;
					getResponseHeader = () => null;
					send() {
						sent.push(this);
					}
					get status() {
						return answer.status;
					}
					get responseText() {
						return answer.body;
					}
				}
			);
		});
		afterEach(() => vi.stubGlobal('fetch', mockFetch));

		const file = new File(['wav'], 'ref.wav', { type: 'audio/wav' });

		it('reports progress and resolves with the stored record', async () => {
			const fractions: number[] = [];
			const settled = uploadReference(file, (fraction) => fractions.push(fraction));

			sent[0].upload.onprogress?.({ lengthComputable: true, loaded: 1, total: 4 } as ProgressEvent);
			sent[0].onload();

			await expect(settled).resolves.toEqual({ id: 'reference-1' });
			expect(fractions).toEqual([0.25]);
			expect(mockFetch).not.toHaveBeenCalled();
		});

		it('rejects a refusal with the ApiError carrying the server detail', async () => {
			answer = { status: 409, body: '{"detail":"Reference audio storage limit reached."}' };
			const settled = uploadReference(file, () => undefined);

			sent[0].onload();

			const failure = await settled.catch((e: unknown) => e);
			expect(failure).toBeInstanceOf(ApiError);
			expect(failure).toMatchObject({
				status: 409,
				detail: 'Reference audio storage limit reached.'
			});
		});
	});

	it('addresses a reference recording under the API with the id as one path segment', () => {
		expect(referenceAudioUrl('a/b?c')).toBe('/api/references/a%2Fb%3Fc/audio');
	});
});
