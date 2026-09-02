import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

const mockClearAuth = vi.fn();
const mockGoto = vi.fn();

vi.mock('$lib/stores/auth', () => ({ clearAuth: (...args: unknown[]) => mockClearAuth(...args) }));
vi.mock('$app/navigation', () => ({ goto: (...args: unknown[]) => mockGoto(...args) }));

import {
	listWorkers,
	getRegistry,
	loadModelOnWorker,
	evictModelOnWorker,
	downloadModel,
	restartWorker,
	pinModelOnWorker,
	unpinModelOnWorker
} from './admin';

function mockOk(data: unknown) {
	mockFetch.mockResolvedValueOnce({
		ok: true,
		json: () => Promise.resolve(data)
	});
}

beforeEach(() => {
	mockFetch.mockReset();
	mockClearAuth.mockReset();
	mockGoto.mockReset();
});

describe('admin worker pool API', () => {
	it('listWorkers calls GET /api/admin/workers', async () => {
		mockOk({
			workers: [
				{
					identity: {
						id: 'acestep-worker-0',
						host: 'acestep-worker-0',
						port: 9000,
						gpu_id: 0,
						vram_total_gb: 24.0,
						registered_at: '2026-04-07T00:00:00Z',
						last_register_at: '2026-04-07T00:00:00Z'
					},
					state: {
						loaded: [{ mode: 'sft', size_gb: 6.0 }],
						target_loading: null,
						loading_started_at: null,
						queue_depth: 0,
						vram_used_gb: 12.0,
						vram_total_gb: 24.0,
						available_modes: ['sft', 'turbo', 'xl-sft'],
						pinned: [],
						last_heartbeat_at: '2026-04-07T00:00:02Z'
					},
					status: 'online'
				}
			]
		});
		const result = await listWorkers();
		expect(result.workers).toHaveLength(1);
		expect(result.workers[0].identity.id).toBe('acestep-worker-0');
		expect(result.workers[0].state?.loaded).toEqual([{ mode: 'sft', size_gb: 6.0 }]);
		expect(result.workers[0].state?.pinned).toEqual([]);
		expect(result.workers[0].status).toBe('online');
		expect(mockFetch).toHaveBeenCalledWith(
			'/api/admin/workers',
			expect.objectContaining({ credentials: 'include' })
		);
	});

	it('getRegistry calls GET /api/admin/registry', async () => {
		mockOk({
			models: [
				{
					mode: 'sft',
					availability: 'downloaded',
					loaded_on: ['acestep-worker-0'],
					loading_on: []
				},
				{ mode: 'xl-base', availability: 'not_downloaded', loaded_on: [], loading_on: [] }
			]
		});
		const result = await getRegistry();
		expect(result.models).toHaveLength(2);
		expect(result.models[0].mode).toBe('sft');
		expect(result.models[0].availability).toBe('downloaded');
		expect(result.models[1].availability).toBe('not_downloaded');
		expect(mockFetch).toHaveBeenCalledWith(
			'/api/admin/registry',
			expect.objectContaining({ credentials: 'include' })
		);
	});

	it('loadModelOnWorker POSTs mode and returns JobItem', async () => {
		mockOk({ id: 'j1', type: 'load_model_on_worker', status: 'queued', progress: 0 });
		const result = await loadModelOnWorker('acestep-worker-0', 'xl-sft');
		expect(result.id).toBe('j1');
		expect(result.type).toBe('load_model_on_worker');
		const [url, init] = mockFetch.mock.calls[0];
		expect(url).toBe('/api/admin/workers/acestep-worker-0/load_model');
		expect(init.method).toBe('POST');
		expect(init.headers['Content-Type']).toBe('application/json');
		expect(JSON.parse(init.body)).toEqual({ mode: 'xl-sft' });
	});

	it('evictModelOnWorker POSTs mode', async () => {
		mockOk({});
		await evictModelOnWorker('acestep-worker-0', 'sft');
		const [url, init] = mockFetch.mock.calls[0];
		expect(url).toBe('/api/admin/workers/acestep-worker-0/evict_model');
		expect(init.method).toBe('POST');
		expect(JSON.parse(init.body)).toEqual({ mode: 'sft' });
	});

	it('downloadModel POSTs to registry endpoint and returns JobItem', async () => {
		mockOk({ id: 'j1', type: 'download_model_on_worker', status: 'queued', progress: 0 });
		const result = await downloadModel('xl-base');
		expect(result.id).toBe('j1');
		expect(result.type).toBe('download_model_on_worker');
		const [url, init] = mockFetch.mock.calls[0];
		expect(url).toBe('/api/admin/registry/xl-base/download');
		expect(init.method).toBe('POST');
	});

	it('restartWorker POSTs to /restart', async () => {
		mockOk({});
		await restartWorker('acestep-worker-0');
		const [url, init] = mockFetch.mock.calls[0];
		expect(url).toBe('/api/admin/workers/acestep-worker-0/restart');
		expect(init.method).toBe('POST');
	});

	it('pinModelOnWorker POSTs mode', async () => {
		mockOk({});
		await pinModelOnWorker('acestep-worker-0', 'sft');
		const [url, init] = mockFetch.mock.calls[0];
		expect(url).toBe('/api/admin/workers/acestep-worker-0/pin_model');
		expect(init.method).toBe('POST');
		expect(JSON.parse(init.body)).toEqual({ mode: 'sft' });
	});

	it('unpinModelOnWorker POSTs mode', async () => {
		mockOk({});
		await unpinModelOnWorker('acestep-worker-0', 'sft');
		const [url, init] = mockFetch.mock.calls[0];
		expect(url).toBe('/api/admin/workers/acestep-worker-0/unpin_model');
		expect(init.method).toBe('POST');
		expect(JSON.parse(init.body)).toEqual({ mode: 'sft' });
	});
});
