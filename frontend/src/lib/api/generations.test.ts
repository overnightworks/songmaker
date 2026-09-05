import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);
vi.mock('$lib/stores/auth', () => ({ clearAuth: vi.fn() }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

import { coverGeneration, generateSong, repaintGeneration } from './generations';

function acceptRequests(): void {
	mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ status: 'queued' }) });
}

function request(): [string, RequestInit] {
	return mockFetch.mock.calls[0] as [string, RequestInit];
}

beforeEach(() => {
	mockFetch.mockReset();
	acceptRequests();
});

describe('generation API contract', () => {
	it('keeps absent generate options out of the request and preserves supplied values including seed zero', async () => {
		await generateSong('song-1', 2, 'acestep');
		let [url, init] = request();
		expect(url).toBe('/api/songs/song-1/generate');
		expect(init.method).toBe('POST');
		expect(JSON.parse(String(init.body))).toEqual({ count: 2, model: 'acestep' });

		mockFetch.mockClear();
		await generateSong('song-1', 1, 'acestep', 'version-1', 0);
		[url, init] = request();
		expect(url).toBe('/api/songs/song-1/generate');
		expect(JSON.parse(String(init.body))).toEqual({
			count: 1,
			model: 'acestep',
			version_id: 'version-1',
			seed: 0
		});
	});

	it.each([
		[
			'repaint',
			() => repaintGeneration('gen-1', 12, 24, { model: 'acestep' }),
			'/api/generations/gen-1/repaint',
			{ src_generation_id: 'gen-1', repainting_start: 12, repainting_end: 24, model: 'acestep' }
		],
		[
			'cover',
			() => coverGeneration('gen-1', 0.7, { model: 'acestep' }),
			'/api/generations/gen-1/cover',
			{ src_generation_id: 'gen-1', audio_cover_strength: 0.7, model: 'acestep' }
		]
	])('sends the required %s request fields', async (_name, send, url, payload) => {
		await send();
		const [actualUrl, init] = request();
		expect(actualUrl).toBe(url);
		expect(init.method).toBe('POST');
		expect(JSON.parse(String(init.body))).toEqual(payload);
	});

	it('sends every supplied repaint and cover override without inventing count one', async () => {
		await repaintGeneration('gen-1', 12, 24, {
			model: 'acestep',
			lyrics: '',
			prompt: 'warmer',
			seed: 0,
			versionId: 'version-1',
			count: 3,
			repaintMode: 'replace',
			repaintStrength: 0.4,
			repaintLatentCrossfadeFrames: 8,
			repaintWavCrossfadeSec: 1.2
		});
		let [, init] = request();
		expect(JSON.parse(String(init.body))).toEqual({
			src_generation_id: 'gen-1', repainting_start: 12, repainting_end: 24, model: 'acestep',
			lyrics: '', prompt: 'warmer', seed: 0, version_id: 'version-1', count: 3,
			repaint_mode: 'replace', repaint_strength: 0.4, repaint_latent_crossfade_frames: 8,
			repaint_wav_crossfade_sec: 1.2
		});

		mockFetch.mockClear();
		await coverGeneration('gen-1', 0.7, {
			model: 'acestep', lyrics: '', prompt: 'brighter', seed: 0, versionId: 'version-1',
			count: 2, coverNoiseStrength: 0.25
		});
		[, init] = request();
		expect(JSON.parse(String(init.body))).toEqual({
			src_generation_id: 'gen-1', audio_cover_strength: 0.7, model: 'acestep', lyrics: '',
			prompt: 'brighter', seed: 0, version_id: 'version-1', count: 2, cover_noise_strength: 0.25
		});
	});
});
