import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);
vi.mock('$app/navigation', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation()
);

import { uploadReference } from './references';

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
});
