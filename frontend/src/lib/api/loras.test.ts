import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

vi.mock('$lib/stores/auth', () => ({ clearAuth: vi.fn() }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

import {
	listLoras,
	getLora,
	createLora,
	softDeleteLora,
	addLoraSample,
	addLoraSampleFromGeneration,
	patchLoraSample,
	deleteLoraSample,
	listOwnPlayableTakes,
	trainLora
} from './loras';
import { ApiError } from './fetch';

function mockOk(data: unknown) {
	mockFetch.mockResolvedValueOnce({
		ok: true,
		json: () => Promise.resolve(data)
	});
}

function mockError(status: number, detail: string = '') {
	mockFetch.mockResolvedValueOnce({
		ok: false,
		status,
		json: () => Promise.resolve({ detail })
	});
}

beforeEach(() => {
	mockFetch.mockReset();
	document.cookie = '';
});

describe('LoRA API client', () => {
	it('listLoras calls /api/loras and returns list', async () => {
		mockOk({ loras: [{ id: 'l1', name: 'Me', status: 'draft', samples: [] }] });
		const result = await listLoras();
		expect(result).toHaveLength(1);
		expect(mockFetch).toHaveBeenCalledWith(
			'/api/loras',
			expect.objectContaining({ credentials: 'include' })
		);
	});

	it('listLoras with includeDeleted adds query param', async () => {
		mockOk({ loras: [] });
		await listLoras(true);
		const url = mockFetch.mock.calls[0][0];
		expect(url).toBe('/api/loras?include_deleted=true');
	});

	it('getLora hits /api/loras/{id}', async () => {
		mockOk({ id: 'l1', name: 'Me', status: 'draft', samples: [] });
		const lora = await getLora('l1');
		expect(lora.id).toBe('l1');
		expect(mockFetch.mock.calls[0][0]).toBe('/api/loras/l1');
	});

	it('createLora sends POST with name', async () => {
		mockOk({ id: 'l1', name: 'My Voice', status: 'draft', samples: [] });
		await createLora('My Voice');
		const [url, init] = mockFetch.mock.calls[0];
		expect(url).toBe('/api/loras');
		expect(init.method).toBe('POST');
		expect(JSON.parse(init.body)).toEqual({ name: 'My Voice' });
	});

	it('softDeleteLora sends DELETE', async () => {
		mockOk({ status: 'ok' });
		await softDeleteLora('l1');
		const [url, init] = mockFetch.mock.calls[0];
		expect(url).toBe('/api/loras/l1');
		expect(init.method).toBe('DELETE');
	});

	it('addLoraSample sends multipart with file, caption, lyrics', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: () => Promise.resolve({ id: 's1', caption: 'warm', lyrics: 'la', position: 0 })
		});
		const file = new File([new Uint8Array([1, 2, 3])], 'clip.wav', { type: 'audio/wav' });
		const sample = await addLoraSample('l1', file, 'warm', 'la');
		expect(sample.id).toBe('s1');
		const [url, init] = mockFetch.mock.calls[0];
		expect(url).toBe('/api/loras/l1/samples');
		expect(init.method).toBe('POST');
		expect(init.body).toBeInstanceOf(FormData);
		const form = init.body as FormData;
		expect(form.get('caption')).toBe('warm');
		expect(form.get('lyrics')).toBe('la');
		expect(form.get('audio')).toBe(file);
	});

	it('addLoraSample includes position when provided', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: () => Promise.resolve({ id: 's1' })
		});
		const file = new File(['x'], 'a.mp3');
		await addLoraSample('l1', file, 'c', 'l', 3);
		const form = mockFetch.mock.calls[0][1].body as FormData;
		expect(form.get('position')).toBe('3');
	});

	it('lists only the caller-owned playable take catalogue', async () => {
		mockOk({
			takes: [
				{
					generation_id: 'g1',
					song_title: 'Glass River',
					generation_number: 4,
					audio_url: '/audio/u1/g1.mp3',
					caption: 'warm tenor',
					lyrics: 'a line'
				}
			]
		});
		const takes = await listOwnPlayableTakes();
		expect(takes[0]?.song_title).toBe('Glass River');
		expect(mockFetch.mock.calls[0][0]).toBe('/api/loras/own-takes');
	});

	it('copies an own take by generation id without uploading its audio again', async () => {
		mockOk({ id: 's1', caption: 'warm tenor', lyrics: 'a line', position: 0 });
		await addLoraSampleFromGeneration('l1', 'g1');
		const [url, init] = mockFetch.mock.calls[0];
		expect(url).toBe('/api/loras/l1/samples/from-generation');
		expect(init.method).toBe('POST');
		expect(init.body).toBe(JSON.stringify({ generation_id: 'g1' }));
		expect(init.body).not.toBeInstanceOf(FormData);
	});

	it('addLoraSample attaches CSRF token if cookie present', async () => {
		document.cookie = 'csrf_token=abc';
		mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ id: 's1' }) });
		await addLoraSample('l1', new File(['x'], 'a.mp3'), 'c', 'l');
		const headers = mockFetch.mock.calls[0][1].headers as Record<string, string>;
		expect(headers['X-CSRF-Token']).toBe('abc');
	});

	it('addLoraSample throws ApiError on non-ok', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 422,
			json: () => Promise.resolve({ detail: 'Unsupported format' })
		});
		const file = new File(['x'], 'a.wav');
		await expect(addLoraSample('l1', file, 'c', 'l')).rejects.toBeInstanceOf(ApiError);
	});

	it('addLoraSample surfaces detail on ApiError', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 413,
			json: () => Promise.resolve({ detail: 'Too large' })
		});
		const file = new File(['x'], 'a.wav');
		const err = (await addLoraSample('l1', file, 'c', 'l').catch((e) => e)) as ApiError;
		expect(err.status).toBe(413);
		expect(err.detail).toBe('Too large');
	});

	it('addLoraSample handles non-JSON error body', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 500,
			json: () => Promise.reject(new Error('not json'))
		});
		const file = new File(['x'], 'a.wav');
		const err = (await addLoraSample('l1', file, 'c', 'l').catch((e) => e)) as ApiError;
		expect(err).toBeInstanceOf(ApiError);
		expect(err.detail).toBe('');
	});

	it('patchLoraSample sends PATCH with JSON body', async () => {
		mockOk({ id: 's1', caption: 'new', lyrics: 'l', position: 0 });
		await patchLoraSample('l1', 's1', { caption: 'new' });
		const [url, init] = mockFetch.mock.calls[0];
		expect(url).toBe('/api/loras/l1/samples/s1');
		expect(init.method).toBe('PATCH');
		expect(JSON.parse(init.body)).toEqual({ caption: 'new' });
	});

	it('deleteLoraSample sends DELETE to nested path', async () => {
		mockOk({ status: 'ok' });
		await deleteLoraSample('l1', 's1');
		const [url, init] = mockFetch.mock.calls[0];
		expect(url).toBe('/api/loras/l1/samples/s1');
		expect(init.method).toBe('DELETE');
	});

	it('trainLora sends POST to /train', async () => {
		mockOk({ id: 'l1', status: 'queued', samples: [] });
		const result = await trainLora('l1');
		expect(result.status).toBe('queued');
		const [url, init] = mockFetch.mock.calls[0];
		expect(url).toBe('/api/loras/l1/train');
		expect(init.method).toBe('POST');
	});

	it('trainLora surfaces 422 preflight errors', async () => {
		mockError(422, 'At least 3 samples required for training (have 1)');
		const err = (await trainLora('l1').catch((e) => e)) as ApiError;
		expect(err).toBeInstanceOf(ApiError);
		expect(err.status).toBe(422);
		expect(err.detail).toMatch(/3 samples/);
	});
});
