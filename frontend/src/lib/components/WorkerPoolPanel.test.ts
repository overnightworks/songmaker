import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { WorkerPoolResponse } from '$lib/api/types';
import { ApiError } from '$lib/api/fetch';
import { lostNetwork } from '$lib/test-utils/network';
import { WORKER_POOL_LOAD_FAILED, WORKER_POOL_REFRESH_FAILED } from '$lib/constants';
import { reportResourceStreamReachable, resetConnectivityForTests } from '$lib/stores/connectivity';

const api = vi.hoisted(() => ({
	listWorkers: vi.fn()
}));

vi.mock('$lib/api/client', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/api/client')>();
	return { ...actual, ...api };
});

import WorkerPoolPanel from './WorkerPoolPanel.svelte';

let mounted: ReturnType<typeof mount> | undefined;

// Button text is split across template lines (e.g. "{isPinned ? 'Unpin' :
// 'Pin'} {loadedDetail.mode}"), so textContent carries the whitespace
// between them -- normalize before matching, both when asserting a button
// exists and when asserting one doesn't.
function findButtonByText(root: HTMLElement, text: string): HTMLButtonElement | undefined {
	return Array.from(root.querySelectorAll<HTMLButtonElement>('button')).find((button) =>
		button.textContent?.replace(/\s+/g, ' ').trim().includes(text)
	);
}

function workerPool(vramMeasured: boolean | null): WorkerPoolResponse {
	return {
		workers: [
			{
				identity: {
					id: 'acestep-worker-0',
					host: 'worker',
					port: 8100,
					gpu_id: 0,
					vram_total_gb: 24,
					registered_at: '2026-09-01T10:00:00Z',
					last_register_at: '2026-09-01T10:00:00Z'
				},
				state: {
					loaded: [],
					target_loading: null,
					loading_started_at: null,
					loading_last_log_line: null,
					queue_depth: 0,
					vram_used_gb: 12.4,
					vram_total_gb: 24,
					vram_measured: vramMeasured,
					available_modes: [],
					pinned: [],
					last_heartbeat_at: '2026-09-01T10:00:00Z'
				},
				status: 'online'
			}
		]
	};
}

async function renderVramPool(pool: WorkerPoolResponse): Promise<HTMLElement> {
	api.listWorkers.mockResolvedValue(pool);
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(WorkerPoolPanel, { target, props: { availableModes: ['sft', 'turbo'] } });
	await tick();
	await Promise.resolve();
	await tick();
	return target;
}

beforeEach(() => {
	api.listWorkers.mockReset();
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	resetConnectivityForTests();
	vi.useRealTimers();
});

function offlineWorkerPool(lastRegisterAt: string): WorkerPoolResponse {
	return {
		workers: [
			{
				identity: {
					id: 'acestep-worker-0',
					host: 'worker',
					port: 8100,
					gpu_id: 0,
					vram_total_gb: 24,
					registered_at: '2026-08-24T11:10:00Z',
					last_register_at: lastRegisterAt
				},
				state: null,
				status: 'offline'
			}
		]
	};
}

async function renderOffline(lastRegisterAt: string): Promise<HTMLElement> {
	api.listWorkers.mockResolvedValue(offlineWorkerPool(lastRegisterAt));
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(WorkerPoolPanel, { target, props: { availableModes: [] } });
	await tick();
	await Promise.resolve();
	await tick();
	return target;
}

describe('WorkerPoolPanel with no heartbeat', () => {
	it('defect:#1567 names how long the worker has been gone instead of just "no heartbeat"', async () => {
		// The GPU worker's container sat on "Created" for five days without
		// ever registering again (issue #252's live incident). "Offline (no
		// heartbeat)" told the operator nothing about how long that had been
		// true; last_register_at was already on the wire and unused.
		const sixDaysAgo = new Date(Date.now() - 6 * 24 * 60 * 60 * 1000).toISOString();
		const target = await renderOffline(sixDaysAgo);

		expect(target.textContent).toContain('last registered');
		expect(target.textContent).toContain('6d ago');
		expect(target.querySelector('.card-row')?.textContent).not.toContain('no heartbeat');
	});

	it('explains why Restart cannot help instead of leaving it clickable into a 502', async () => {
		const target = await renderOffline(new Date().toISOString());

		const restartButton = Array.from(target.querySelectorAll<HTMLButtonElement>('button')).find(
			(button) => button.textContent?.includes('Restart')
		);
		if (!restartButton) throw new Error('Expected a Restart button to be rendered');

		expect(restartButton.disabled).toBe(true);
		// The hint must name which worker's container is meant -- there can be
		// several -- not just say "its container" in the abstract.
		expect(restartButton.title).toContain('acestep-worker-0');
		expect(target.textContent).toContain('no worker process is running');
		expect(target.textContent).toContain('worker "acestep-worker-0"');
	});
});

function heartbeatingButOfflineWorkerPool(
	gpuHealthy: boolean | null,
	gpuHealthDetail: string | null
): WorkerPoolResponse {
	return {
		workers: [
			{
				identity: {
					id: 'acestep-worker-0',
					host: 'worker',
					port: 8100,
					gpu_id: 0,
					vram_total_gb: 24,
					registered_at: '2026-08-24T11:10:00Z',
					last_register_at: '2026-09-02T09:00:00Z'
				},
				state: {
					loaded: [{ mode: 'sft', size_gb: 6 }],
					target_loading: null,
					loading_started_at: null,
					loading_last_log_line: null,
					queue_depth: 0,
					vram_used_gb: null,
					vram_total_gb: 24,
					vram_measured: null,
					available_modes: ['sft'],
					pinned: [],
					last_heartbeat_at: new Date().toISOString(),
					gpu_healthy: gpuHealthy,
					gpu_health_detail: gpuHealthDetail
				},
				status: 'offline'
			}
		]
	};
}

async function renderHeartbeatingButOffline(
	gpuHealthy: boolean | null,
	gpuHealthDetail: string | null
): Promise<HTMLElement> {
	api.listWorkers.mockResolvedValue(heartbeatingButOfflineWorkerPool(gpuHealthy, gpuHealthDetail));
	const target = document.createElement('div');
	document.body.append(target);
	// Non-empty availableModes on purpose: the mode-select must be disabled
	// because this worker is offline, not merely because there is nothing
	// to select. An empty list here would let a regression in the offline
	// guard hide behind an unrelated "no models" disablement.
	mounted = mount(WorkerPoolPanel, { target, props: { availableModes: ['sft', 'turbo'] } });
	await tick();
	await Promise.resolve();
	await tick();
	return target;
}

describe('WorkerPoolPanel with a heartbeating but GPU-broken worker', () => {
	// Issue #367: a worker whose GPU has gone away keeps heartbeating just
	// fine, so the API correctly marks it "offline" while state stays
	// non-null. The panel must not read state-presence as "Idle" — the red
	// status icon and the row text must agree, and nothing must be
	// clickable.
	it('names the GPU failure from the heartbeat and disables every action', async () => {
		const target = await renderHeartbeatingButOffline(false, 'Driver/library version mismatch');

		expect(target.textContent).toContain('GPU unavailable — Driver/library version mismatch');
		expect(target.textContent).not.toContain('Idle');
		expect(target.textContent).not.toContain('just now');

		const buttons = Array.from(target.querySelectorAll<HTMLButtonElement>('button'));
		expect(buttons.length).toBeGreaterThan(0);
		for (const button of buttons) {
			expect(button.disabled).toBe(true);
		}
		// No Pin/Evict buttons for its loaded "sft" either, even though this
		// worker's heartbeat reports one loaded -- being offline hides them,
		// it doesn't just leave them disabled.
		expect(findButtonByText(target, 'Pin sft')).toBeUndefined();
		expect(findButtonByText(target, 'Evict sft')).toBeUndefined();
		const select = target.querySelector<HTMLSelectElement>('select.mode-select');
		expect(select?.disabled).toBe(true);
	});

	it('names an old worker build that never learned to report GPU health', async () => {
		const target = await renderHeartbeatingButOffline(null, null);

		expect(target.textContent).toContain('GPU health not reported');
		expect(target.textContent).toContain('container running worker');
		expect(target.textContent).not.toContain('Idle');

		const buttons = Array.from(target.querySelectorAll<HTMLButtonElement>('button'));
		expect(buttons.length).toBeGreaterThan(0);
		for (const button of buttons) {
			expect(button.disabled).toBe(true);
		}
		const select = target.querySelector<HTMLSelectElement>('select.mode-select');
		expect(select?.disabled).toBe(true);
	});
});

function onlineWorkerPool(): WorkerPoolResponse {
	return {
		workers: [
			{
				identity: {
					id: 'acestep-worker-0',
					host: 'worker',
					port: 8100,
					gpu_id: 0,
					vram_total_gb: 24,
					registered_at: '2026-08-24T11:10:00Z',
					last_register_at: '2026-09-02T09:00:00Z'
				},
				state: {
					loaded: [{ mode: 'sft', size_gb: 6 }],
					target_loading: null,
					loading_started_at: null,
					loading_last_log_line: null,
					queue_depth: 0,
					vram_used_gb: 12.4,
					vram_total_gb: 24,
					vram_measured: true,
					available_modes: ['sft'],
					pinned: [],
					last_heartbeat_at: new Date().toISOString(),
					gpu_healthy: true,
					gpu_health_detail: null
				},
				status: 'online'
			}
		]
	};
}

function trainingWorkerPool(): WorkerPoolResponse {
	const pool = onlineWorkerPool();
	const state = pool.workers[0].state;
	if (state === null) throw new Error('Expected a heartbeating worker');
	state.training_hold_seconds = 12;
	return pool;
}

async function renderOnline(): Promise<HTMLElement> {
	api.listWorkers.mockResolvedValue(onlineWorkerPool());
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(WorkerPoolPanel, { target, props: { availableModes: ['sft', 'turbo'] } });
	await tick();
	await Promise.resolve();
	await tick();
	return target;
}

describe('WorkerPoolPanel with a healthy online worker', () => {
	// The counter-proof to the offline-guard tests above: nothing about
	// this change may make a genuinely healthy worker's actions
	// unreachable. Without this, a guard that fails "always disabled" would
	// pass every offline test and still be a regression.
	it('leaves the mode-select, Load, Pin, Evict, and Restart all usable', async () => {
		const target = await renderOnline();

		const select = target.querySelector<HTMLSelectElement>('select.mode-select');
		if (!select) throw new Error('Expected a mode-select to be rendered');
		expect(select.disabled).toBe(false);

		select.value = 'turbo';
		select.dispatchEvent(new Event('change', { bubbles: true }));
		await tick();

		const loadButton = findButtonByText(target, 'Load');
		if (!loadButton) throw new Error('Expected a Load button to be rendered');
		expect(loadButton.disabled).toBe(false);

		const pinButton = findButtonByText(target, 'Pin sft');
		if (!pinButton) throw new Error('Expected a Pin button for the loaded model');
		expect(pinButton.disabled).toBe(false);

		const evictButton = findButtonByText(target, 'Evict sft');
		if (!evictButton) throw new Error('Expected an Evict button for the loaded model');
		expect(evictButton.disabled).toBe(false);

		const restartButton = findButtonByText(target, 'Restart');
		if (!restartButton) throw new Error('Expected a Restart button to be rendered');
		expect(restartButton.disabled).toBe(false);
	});

	it('shows a held online worker as training with the remaining lease', async () => {
		api.listWorkers.mockResolvedValue(trainingWorkerPool());
		const target = document.createElement('div');
		document.body.append(target);
		mounted = mount(WorkerPoolPanel, { target, props: { availableModes: ['sft'] } });
		await tick();
		await Promise.resolve();
		await tick();

		expect(target.textContent).toContain('Training (12s remaining)');
		expect(target.textContent).not.toContain('Idle');
		expect(target.querySelector('.status-online')).not.toBeNull();
	});
});

describe('WorkerPoolPanel VRAM measurement', () => {
	it.each([
		{ name: 'measured', measured: true, used: 18.5, loading: false, free: '5.5 GB free' },
		{ name: 'estimated', measured: false, used: 6, loading: false, free: null },
		{ name: 'loading measured', measured: true, used: 9.1, loading: true, free: '14.9 GB free' },
		{ name: 'loading estimated', measured: false, used: 6, loading: true, free: null },
		{ name: 'legacy null flag', measured: null, used: 18.5, loading: false, free: '5.5 GB free' },
		{
			name: 'legacy absent flag',
			measured: undefined,
			used: 18.5,
			loading: false,
			free: '5.5 GB free'
		},
		{ name: 'full GPU', measured: true, used: 24, loading: false, free: '0.0 GB free' },
		{ name: 'over capacity', measured: true, used: 25.3, loading: false, free: '0.0 GB free' }
	])(
		'defect:#1567 shows $name and preserves Load availability',
		async ({ measured, used, loading, free }) => {
			const pool = workerPool(measured ?? null);
			const state = pool.workers[0].state;
			if (!state) throw new Error('Expected a heartbeating worker');
			if (measured === undefined) delete state.vram_measured;
			state.vram_used_gb = used;
			state.target_loading = loading ? 'turbo' : null;
			pool.workers[0].status = loading ? 'loading' : 'online';
			const target = await renderVramPool(pool);
			const row = target.querySelector('[role="group"][aria-label="VRAM"]');
			expect(row).toHaveTextContent(
				`${measured === false ? '~' : ''}${used.toFixed(1)} / 24.0 GB${measured === false ? ' est.' : ''}`
			);
			expect(row).not.toHaveTextContent('unknown');
			expect(row).toHaveTextContent('VRAM:');
			expect(target.textContent).toMatch(/Queue:.*VRAM:.*Last seen:/s);
			if (free) expect(row).toHaveTextContent(free);
			else {
				expect(row).not.toHaveTextContent('GB free');
				expect(row).toHaveTextContent(
					'No GPU reading — the sizes of the loaded models, not a measurement'
				);
			}
			const load = findButtonByText(target, 'Load');
			if (!load) throw new Error('Expected a Load button');
			expect(load.disabled).toBe(true);
			const select = target.querySelector('select');
			if (!select) throw new Error('Expected a model selector');
			select.value = 'turbo';
			select.dispatchEvent(new Event('change', { bubbles: true }));
			await tick();
			expect(load.disabled).toBe(loading);
		}
	);

	it.each([
		{ missing: 'heartbeat', reason: 'No heartbeat — nothing to read' },
		{ missing: 'used', reason: 'Worker build does not report VRAM fields' },
		{ missing: 'total', reason: 'Worker does not report total VRAM' },
		{ missing: 'both', reason: 'Worker build does not report VRAM fields' }
	])(
		'defect:#1567 shows unknown when missing $missing without borrowing identity capacity',
		async ({ missing, reason }) => {
			const pool = workerPool(true);
			if (missing === 'heartbeat') {
				pool.workers[0].state = null;
				pool.workers[0].status = 'offline';
			} else {
				const state = pool.workers[0].state;
				if (!state) throw new Error('Expected a heartbeating worker');
				if (missing !== 'total') state.vram_used_gb = null;
				if (missing !== 'used') state.vram_total_gb = null;
			}
			const target = await renderVramPool(pool);
			const row = target.querySelector('[role="group"][aria-label="VRAM"]');
			expect(row).toHaveTextContent('unknown');
			expect(row).toHaveTextContent(reason);
			expect(row).not.toHaveTextContent('GB');
			expect(findButtonByText(target, 'Load')).toBeDisabled();
		}
	);
});

describe('WorkerPoolPanel failures', () => {
	async function renderPanel(): Promise<HTMLElement> {
		const target = document.createElement('div');
		document.body.append(target);
		mounted = mount(WorkerPoolPanel, { target, props: { availableModes: [] } });
		await tick();
		await Promise.resolve();
		await tick();
		return target;
	}

	it.each([
		{
			failure: 'a server reason',
			err: new ApiError(503, 'Worker registry is locked', '/api/admin/workers'),
			shown: 'Worker registry is locked'
		},
		{ failure: 'a lost network with no strip', err: lostNetwork(), shown: WORKER_POOL_LOAD_FAILED }
	])('names $failure without browser text', async ({ err, shown }) => {
		api.listWorkers.mockRejectedValue(err);
		const target = await renderPanel();

		expect(target.querySelector('.panel-error')?.textContent).toBe(shown);
		expect(target.textContent).not.toContain('Failed to fetch');
	});

	it('under the offline strip keeps its workers with no wording of its own and polls again once back online', async () => {
		vi.useFakeTimers();
		api.listWorkers.mockResolvedValue(offlineWorkerPool('2026-09-01T10:00:00Z'));
		const target = await renderPanel();
		await vi.advanceTimersByTimeAsync(0);

		reportResourceStreamReachable(false);
		api.listWorkers.mockRejectedValue(lostNetwork());
		await vi.advanceTimersByTimeAsync(60_000);
		expect(target.querySelector('.card')).not.toBeNull();
		expect(target.querySelector('.banner-error')).toBeNull();
		expect(target.textContent).not.toContain(WORKER_POOL_REFRESH_FAILED);

		api.listWorkers.mockResolvedValue(workerPool(true));
		reportResourceStreamReachable(true);
		await vi.advanceTimersByTimeAsync(0);

		expect(target.textContent).toContain('12.4');
	});
});
