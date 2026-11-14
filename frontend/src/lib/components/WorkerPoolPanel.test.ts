import { mount, tick, unmount } from 'svelte';
import { get } from 'svelte/store';
import { toasts } from '#lib/stores/toast.ts';
import { closeTopLayer, dropLayersFrom } from '#lib/stores/layers.ts';
import { formatDecimal, localClockTime } from '#lib/utils/format.ts';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { WorkerPoolResponse } from '#lib/api/types.ts';
import {
	reportResourceStreamReachable,
	resetConnectivityForTests
} from '#lib/stores/connectivity.ts';
import WorkerPoolPanel from './WorkerPoolPanel.svelte';
import { words } from '#lib/words/en.ts';

let poolResponse: WorkerPoolResponse;
let poolFailure: Response | Error | undefined;

function fetchWorkers(): Promise<Response> {
	if (poolFailure instanceof Error) return Promise.reject(poolFailure);
	return Promise.resolve(poolFailure ?? Response.json(poolResponse));
}

const KEEP_LOADED = words['workerPool.keepLoaded'];
const UNLOAD = words['workerPool.unload'];

let mounted: ReturnType<typeof mount> | undefined;

function findButtonByText(root: HTMLElement, text: string): HTMLButtonElement | undefined {
	return Array.from(root.querySelectorAll<HTMLButtonElement>('button')).find((button) =>
		button.textContent?.replace(/\s+/g, ' ').trim().includes(text)
	);
}

async function openRestartConfirmation(root: HTMLElement) {
	const opener = findButtonByText(root, words['workerPool.restart']);
	if (!opener) throw new Error('Expected restart opener');
	opener.focus();
	opener.click();
	await tick();
	const dialog = root.querySelector<HTMLElement>('[role="dialog"]');
	if (!dialog) throw new Error('Expected confirmation');
	const cancel = findButtonByText(dialog, words['dialog.cancel']);
	if (!cancel) throw new Error('Expected Cancel');
	const restart = findButtonByText(dialog, words['workerPool.restartConfirm']);
	if (!restart) throw new Error('Expected Restart');
	return { opener, dialog, cancel, restart };
}

function workerPool(vramMeasured: boolean | null): WorkerPoolResponse {
	const pool = onlineWorkerPool();
	const state = pool.workers[0].state;
	if (state === null) throw new Error('Expected a heartbeating worker');
	Object.assign(state, { loaded: [], available_modes: [], vram_measured: vramMeasured });
	return pool;
}

async function renderWorkerPool(
	pool = poolResponse,
	availableModes = ['sft', 'turbo']
): Promise<HTMLElement> {
	poolResponse = pool;
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(WorkerPoolPanel, { target, props: { availableModes } });
	await vi.waitFor(() => expect(target.querySelector('.card, .panel-error')).not.toBeNull());
	return target;
}

beforeEach(() => {
	poolFailure = undefined;
	poolResponse = { workers: [] };
	vi.stubGlobal('fetch', fetchWorkers);
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	resetConnectivityForTests();
	vi.useRealTimers();
	vi.unstubAllGlobals();
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

describe('WorkerPoolPanel with no heartbeat', () => {
	it('defect:#1567 names how long the worker has been gone instead of just "no heartbeat"', async () => {
		// The GPU worker's container sat on "Created" for five days without
		// ever registering again (issue #252's live incident). "Offline (no
		// heartbeat)" told the operator nothing about how long that had been
		// true; last_register_at was already on the wire and unused.
		const sixDaysAgo = new Date(Date.now() - 6 * 24 * 60 * 60 * 1000).toISOString();
		const target = await renderWorkerPool(offlineWorkerPool(sixDaysAgo), []);

		expect(target.textContent).toContain('last registered');
		expect(target.textContent).toContain('6d ago');
		expect(target.querySelector('.card-row')?.textContent).not.toContain('no heartbeat');
	});

	it('defect:#1593 explains why Restart cannot help instead of leaving it clickable into a 502', async () => {
		const target = await renderWorkerPool(offlineWorkerPool(new Date().toISOString()), []);

		const restartButton = Array.from(target.querySelectorAll<HTMLButtonElement>('button')).find(
			(button) => button.textContent?.includes(words['workerPool.restart'])
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
	const pool = onlineWorkerPool();
	const worker = pool.workers[0];
	if (worker.state === null) throw new Error('Expected a heartbeating worker');
	worker.status = 'offline';
	Object.assign(worker.state, {
		vram_used_gb: null,
		vram_measured: null,
		gpu_healthy: gpuHealthy,
		gpu_health_detail: gpuHealthDetail
	});
	return pool;
}

describe('WorkerPoolPanel with a heartbeating but GPU-broken worker', () => {
	// Issue #367: a worker whose GPU has gone away keeps heartbeating just
	// fine, so the API correctly marks it "offline" while state stays
	// non-null. The panel must not read state-presence as "Idle" — the red
	// status icon and the row text must agree, and nothing must be
	// clickable.
	it('defect:#1573 names the GPU failure from the heartbeat and disables every action', async () => {
		const target = await renderWorkerPool(
			heartbeatingButOfflineWorkerPool(false, 'Driver/library version mismatch')
		);

		expect(target.textContent).toContain(
			words['workerPool.gpuUnavailableDetail']({ detail: 'Driver/library version mismatch' })
		);
		expect(target.textContent).not.toContain(words['workerPool.statusIdle']);
		expect(target.textContent).not.toContain(words['workerPool.seenJustNow']);

		const buttons = Array.from(target.querySelectorAll<HTMLButtonElement>('button'));
		expect(buttons.length).toBeGreaterThan(0);
		for (const button of buttons) {
			expect(button.disabled).toBe(true);
		}
		expect(target.querySelector('[role="switch"]')).toBeNull();
		expect(findButtonByText(target, UNLOAD)).toBeUndefined();
		const select = target.querySelector<HTMLSelectElement>('select.mode-select');
		expect(select?.disabled).toBe(true);
	});

	it('defect:#1593 names an old worker build that never learned to report GPU health', async () => {
		const target = await renderWorkerPool(heartbeatingButOfflineWorkerPool(null, null));

		expect(target.textContent).toContain(words['workerPool.gpuHealthNotReported']);
		expect(target.textContent).toContain(
			words['workerPool.restartNoGpuHealth']({ worker: 'acestep-worker-0' })
		);
		expect(target.textContent).not.toContain(words['workerPool.statusIdle']);

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

describe('WorkerPoolPanel with a healthy online worker', () => {
	it.each([
		[1, '1 job'],
		[2, '2 jobs'],
		[1200, '1,200 jobs']
	])('counts a queue of %i as "%s"', async (depth, expected) => {
		const pool = onlineWorkerPool();
		const state = pool.workers[0].state;
		if (state === null) throw new Error('Expected a heartbeating worker');
		state.queue_depth = depth;

		const target = await renderWorkerPool(pool);

		expect(target.textContent).toContain(`${words['workerPool.queueLabel']} ${expected}`);
	});

	// The counter-proof to the offline-guard tests above: nothing about
	// this change may make a genuinely healthy worker's actions
	// unreachable. Without this, a guard that fails "always disabled" would
	// pass every offline test and still be a regression.
	it('defect:#1573 leaves Load, Keep loaded, Unload, and Restart usable', async () => {
		const target = await renderWorkerPool(onlineWorkerPool());

		const select = target.querySelector<HTMLSelectElement>('select.mode-select');
		if (!select) throw new Error('Expected a mode-select to be rendered');
		expect(select.disabled).toBe(false);

		select.value = 'turbo';
		select.dispatchEvent(new Event('change', { bubbles: true }));
		await tick();

		const loadButton = findButtonByText(target, words['workerPool.load']);
		if (!loadButton) throw new Error('Expected a Load button to be rendered');
		expect(loadButton.disabled).toBe(false);

		expect(
			target.querySelector(
				`[role="switch"][aria-label="${words['workerPool.keepLoadedModel']({ mode: 'sft' })}"]`
			)
		).toBeEnabled();
		expect(
			target.querySelector(`[aria-label="${words['workerPool.unloadModel']({ mode: 'sft' })}"]`)
		).toBeEnabled();

		const restartButton = findButtonByText(target, words['workerPool.restart']);
		if (!restartButton) throw new Error('Expected a Restart button to be rendered');
		expect(restartButton.disabled).toBe(false);
	});

	it('defect:#1593 shows a held online worker as training with the remaining lease', async () => {
		const target = await renderWorkerPool(trainingWorkerPool(), ['sft']);

		expect(target.textContent).toContain(words['workerPool.statusTraining']({ seconds: '12' }));
		expect(target.textContent).not.toContain(words['workerPool.statusIdle']);
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
			const target = await renderWorkerPool(pool);
			const row = target.querySelector('[role="group"][aria-label="VRAM"]');
			expect(row).toHaveTextContent(
				words[measured === false ? 'workerPool.vramUsedEstimated' : 'workerPool.vramUsed']({
					used: formatDecimal(used, 1),
					total: formatDecimal(24, 1)
				})
			);
			expect(row).not.toHaveTextContent(words['workerPool.vramUnknown']);
			expect(row).toHaveTextContent(words['workerPool.vramLabel']);
			const rowLabels = [
				'workerPool.queueLabel',
				'workerPool.vramLabel',
				'workerPool.lastSeenLabel'
			] as const;
			expect(target.textContent).toMatch(
				new RegExp(rowLabels.map((key) => words[key]).join('.*'), 's')
			);
			const bar = row?.querySelector('.bar');
			const numbers = row?.querySelector('.numbers');
			if (!bar || !numbers) throw new Error('Expected a VRAM bar and numbers');
			expect(bar.compareDocumentPosition(numbers) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
			if (free) expect(row).toHaveTextContent(free);
			else {
				expect(row).not.toHaveTextContent('GB free');
				expect(row).toHaveTextContent(words['workerPool.vramEstimateReason']);
			}
			const load = findButtonByText(target, words['workerPool.load']);
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
		{ missing: 'heartbeat', reason: words['workerPool.vramNoHeartbeat'] },
		{ missing: 'used', reason: words['workerPool.vramNoFields'] },
		{ missing: 'total', reason: words['workerPool.vramNoTotal'] },
		{ missing: 'both', reason: words['workerPool.vramNoFields'] }
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
			const target = await renderWorkerPool(pool);
			const row = target.querySelector('[role="group"][aria-label="VRAM"]');
			expect(row).toHaveTextContent(words['workerPool.vramUnknown']);
			expect(row).toHaveTextContent(reason);
			expect(row).not.toHaveTextContent('GB');
			expect(findButtonByText(target, words['workerPool.load'])).toBeDisabled();
		}
	);
});

describe('WorkerPoolPanel failures', () => {
	it.each([
		{
			failure: 'a server reason',
			err: Response.json({ detail: 'Worker registry is locked' }, { status: 503 }),
			shown: 'Worker registry is locked'
		},
		{
			failure: 'a lost network with no strip',
			err: new TypeError('Failed to fetch'),
			shown: words['workerPool.loadFailed']
		}
	])('defect:#1593 names $failure without browser text', async ({ err, shown }) => {
		poolFailure = err;
		const target = await renderWorkerPool(poolResponse, []);

		expect(target.querySelector('.panel-error')?.textContent).toBe(shown);
		expect(target.textContent).not.toContain('Failed to fetch');
	});

	it('defect:#1593 under the offline strip keeps its workers with no wording of its own and polls again once back online', async () => {
		vi.useFakeTimers();
		poolResponse = offlineWorkerPool('2026-09-01T10:00:00Z');
		const target = await renderWorkerPool(poolResponse, []);
		await vi.advanceTimersByTimeAsync(0);

		reportResourceStreamReachable(false);
		poolFailure = new TypeError('Failed to fetch');
		await vi.advanceTimersByTimeAsync(60_000);
		expect(target.querySelector('.card')).not.toBeNull();
		expect(target.querySelector('.banner-error')).toBeNull();
		expect(target.textContent).not.toContain(words['workerPool.refreshFailed']);

		poolFailure = undefined;
		poolResponse = workerPool(true);
		reportResourceStreamReachable(true);
		await vi.advanceTimersByTimeAsync(0);

		expect(target.textContent).toContain('12.4');
	});
});

describe('WorkerPoolPanel model rows', () => {
	const models = [
		{ mode: 'sft', size_gb: 6 },
		{ mode: 'turbo', size_gb: 6.4 },
		{ mode: 'xl-turbo', size_gb: 12 }
	];

	function modelsPool(count = 3): WorkerPoolResponse {
		const pool = onlineWorkerPool();
		if (!pool.workers[0].state) throw new Error('Expected a heartbeat');
		pool.workers[0].state.loaded = models.slice(0, count);
		pool.workers[0].state.pinned = ['sft', 'xl-turbo'];
		return pool;
	}

	it.each([0, 1, 3])('defect:#1573 renders %i model rows from the heartbeat', async (count) => {
		const target = await renderWorkerPool(modelsPool(count));
		const list = target.querySelector(`[aria-label="${words['workerPool.models']}"]`);
		expect(list).not.toBeNull();
		expect(list).toHaveTextContent(words['workerPool.models']);
		if (count === 0) expect(list).toHaveTextContent(words['workerPool.statusNoModel']);
		else expect(list).not.toHaveTextContent(words['workerPool.statusNoModel']);
		expect(list?.querySelectorAll('[role="group"]')).toHaveLength(count);
		for (const model of models.slice(0, count)) {
			const row = list?.querySelector(`[aria-label="${model.mode}"]`);
			expect(row).toHaveTextContent(
				`${model.mode} ${words['workerPool.modelSize']({ size: formatDecimal(model.size_gb, 0) })}`
			);
			expect(row?.querySelector('[role="switch"]')).toHaveAttribute(
				'aria-checked',
				String(model.mode !== 'turbo')
			);
			expect(
				row?.querySelector(
					`[aria-label="${words['workerPool.unloadModel']({ mode: model.mode })}"]`
				)
			).toBeEnabled();
		}
		expect(
			target.textContent?.match(new RegExp(words['workerPool.keepLoadedHint'], 'g')) ?? []
		).toHaveLength(count > 0 ? 1 : 0);
		expect(target.textContent).not.toContain('Loaded:');
		expect(target.textContent).not.toMatch(/\b(?:Pin|Unpin|Evict)\b/);
	});

	it.each(
		[
			{ action: 'pin_model', mode: 'turbo', label: KEEP_LOADED, kept: false, count: 3 },
			{ action: 'unpin_model', mode: 'sft', label: KEEP_LOADED, kept: true, count: 3 },
			{ action: 'evict_model', mode: 'sft', label: UNLOAD, kept: true, count: 3 },
			{ action: 'evict_model', mode: 'sft', label: UNLOAD, kept: true, count: 1 }
		].flatMap((action) => [false, true].map((refused) => ({ ...action, refused })))
	)(
		'defect:#1573 $action with $count models targets its model, waits for refresh, and handles refusal=$refused',
		async ({ action, mode, label, kept, refused, count }) => {
			const refusal = `${mode} is in use by a running song`;
			const pool = modelsPool(count);
			const target = await renderWorkerPool(pool);
			let finish!: (response: Response) => void;
			const request = new Promise<Response>((resolve) => {
				finish = resolve;
			});
			const requests: { path: string; method?: string; body: unknown }[] = [];
			vi.stubGlobal('fetch', (path: string, init: RequestInit) => {
				if (path === '/api/admin/workers') return fetchWorkers();
				requests.push({ path, method: init.method, body: JSON.parse(String(init.body)) });
				return request;
			});
			const button = target.querySelector<HTMLButtonElement>(`[aria-label="${label} ${mode}"]`);
			if (!button) throw new Error('Expected a model control');
			button.click();
			await tick();
			expect(button).toBeDisabled();
			button.click();
			expect(requests).toEqual([
				{
					path: `/api/admin/workers/acestep-worker-0/${action}`,
					method: 'POST',
					body: { mode }
				}
			]);
			expect(target.querySelector(`[aria-label="${mode}"]`)).not.toBeNull();
			if (label === KEEP_LOADED) expect(button).toHaveAttribute('aria-checked', String(kept));
			const updated = modelsPool(count);
			const state = updated.workers[0].state;
			if (!state) throw new Error('Expected a heartbeat');
			if (action === 'evict_model')
				state.loaded = state.loaded.filter((model) => model.mode !== mode);
			state.pinned = kept
				? state.pinned?.filter((pin) => pin !== mode)
				: [...(state.pinned ?? []), mode];
			if (!refused) poolResponse = updated;
			finish(Response.json(refused ? { detail: refusal } : {}, { status: refused ? 409 : 200 }));
			await vi.waitFor(() => {
				if (refused) {
					expect(target.querySelector('.panel-error')).toHaveTextContent(refusal);
					expect(button).toBeEnabled();
					expect(target.querySelector(`[aria-label="${mode}"]`)).not.toBeNull();
					if (label === KEEP_LOADED) expect(button).toHaveAttribute('aria-checked', String(kept));
				} else if (action === 'evict_model') {
					expect(target.querySelector(`[aria-label="${mode}"]`)).toBeNull();
					if (count === 1) {
						const list = target.querySelector(`[aria-label="${words['workerPool.models']}"]`);
						expect(list).toHaveTextContent(words['workerPool.models']);
						expect(list).toHaveTextContent(words['workerPool.statusNoModel']);
						expect(list?.querySelectorAll('[role="group"]')).toHaveLength(0);
					}
				} else {
					expect(button).toBeEnabled();
					expect(button).toHaveAttribute('aria-checked', String(!kept));
				}
			});
			if (count > 1) {
				expect(target.querySelector('[aria-label="xl-turbo"]')).toHaveTextContent('~12 GB');
				expect(
					target.querySelector(
						`[aria-label="${words['workerPool.keepLoadedModel']({ mode: 'xl-turbo' })}"]`
					)
				).toHaveAttribute('aria-checked', 'true');
			}
		}
	);

	it.each(['loading', 'training'])(
		'defect:#1573 disables model actions during %s',
		async (busy) => {
			const pool = modelsPool();
			const state = pool.workers[0].state;
			if (!state) throw new Error('Expected a heartbeat');
			if (busy === 'loading') state.target_loading = 'base';
			else state.training_hold_seconds = 12;
			const target = await renderWorkerPool(pool);
			const buttons = target.querySelectorAll(
				`[aria-label="${words['workerPool.models']}"] button`
			);
			expect(buttons).toHaveLength(6);
			for (const button of buttons) expect(button).toBeDisabled();
		}
	);
});

describe('WorkerPoolPanel load row', () => {
	it.each([
		{
			name: 'idle',
			loaded: false,
			loading: false,
			offline: false,
			heartbeat: true,
			expected: words['workerPool.statusNoModel']
		},
		{
			name: 'empty loading',
			loaded: false,
			loading: true,
			offline: false,
			heartbeat: true,
			expected: 'None yet — xl-turbo is loading.'
		},
		{
			name: 'loaded loading',
			loaded: true,
			loading: true,
			offline: false,
			heartbeat: true,
			expected: 'sft'
		},
		{
			name: 'offline without state',
			loaded: false,
			loading: false,
			offline: true,
			heartbeat: false,
			expected: words['workerPool.modelsOffline']
		},
		{
			name: 'offline with stale models',
			loaded: true,
			loading: true,
			offline: true,
			heartbeat: true,
			expected: words['workerPool.modelsOffline']
		}
	])('S19-1 S19-2 shows an honest $name list above its load row', async (scenario) => {
		const pool = onlineWorkerPool();
		const worker = pool.workers[0];
		if (!worker.state) throw new Error('Expected heartbeat');
		worker.state.loaded = scenario.loaded ? worker.state.loaded : [];
		worker.state.target_loading = scenario.loading ? 'xl-turbo' : null;
		if (!scenario.heartbeat) worker.state = null;
		worker.status = scenario.offline ? 'offline' : scenario.loading ? 'loading' : 'online';
		const target = await renderWorkerPool(pool);
		const list = target.querySelector(`[aria-label="${words['workerPool.models']}"]`);
		expect(list).toHaveTextContent(words['workerPool.models']);
		expect(list).toHaveTextContent(scenario.expected);
		expect(list?.querySelectorAll('[role="switch"]')).toHaveLength(
			scenario.loaded && !scenario.offline ? 1 : 0
		);
		if (scenario.offline || !scenario.loaded) expect(list).not.toHaveTextContent(KEEP_LOADED);
		if (scenario.offline) expect(list).not.toHaveTextContent('sft');
		const row = list?.nextElementSibling;
		expect(row?.querySelector('select')).not.toBeNull();
		expect(row?.querySelector('button')).toHaveTextContent(words['workerPool.load']);
		expect(row).not.toHaveTextContent(words['workerPool.restartConfirm']);
		expect(row?.nextElementSibling).toHaveTextContent(words['workerPool.restartConfirm']);
	});

	it.each(['idle', 'loading', 'offline', 'training', 'queued', 'full GPU'])(
		'S19-3 permits Load only with a selection and no loading/offline state: %s',
		async (stateName) => {
			const pool = onlineWorkerPool();
			const worker = pool.workers[0];
			if (!worker.state) throw new Error('Expected heartbeat');
			if (stateName === 'loading') worker.state.target_loading = 'xl-turbo';
			if (stateName === 'offline') worker.status = 'offline';
			if (stateName === 'training') worker.state.training_hold_seconds = 12;
			if (stateName === 'queued') worker.state.queue_depth = 10;
			if (stateName === 'full GPU') worker.state.vram_used_gb = 24;
			const target = await renderWorkerPool(pool);
			const load = findButtonByText(target, words['workerPool.load']);
			const select = target.querySelector('select');
			if (!select) throw new Error('Expected selection');
			expect(load).toBeDisabled();
			select.value = 'turbo';
			select.dispatchEvent(new Event('change', { bubbles: true }));
			await tick();
			expect(select.disabled).toBe(['loading', 'offline'].includes(stateName));
			expect(load?.disabled).toBe(['loading', 'offline'].includes(stateName));
			if (stateName === 'training') {
				expect(
					target.querySelector(
						`[aria-label="${words['workerPool.keepLoadedModel']({ mode: 'sft' })}"]`
					)
				).toBeDisabled();
				expect(
					target.querySelector(`[aria-label="${words['workerPool.unloadModel']({ mode: 'sft' })}"]`)
				).toBeDisabled();
			}
		}
	);

	it.each([false, true])(
		'S19-3 sends one load to its worker and recovers after refusal=%s',
		async (refused) => {
			const target = await renderWorkerPool(workerPool(true));
			let finish!: (response: Response) => void;
			const pending = new Promise<Response>((resolve) => {
				finish = resolve;
			});
			const requests: { path: string; method?: string; body: unknown }[] = [];
			vi.stubGlobal('fetch', (path: string, init: RequestInit) => {
				if (path === '/api/admin/workers') return fetchWorkers();
				requests.push({ path, method: init.method, body: JSON.parse(String(init.body)) });
				return pending;
			});
			let sendJob!: (status: string) => void;
			const job = { id: 'load-1593', type: 'load_model_on_worker', status: 'queued' };
			vi.stubGlobal(
				'EventSource',
				class {
					onmessage: ((event: MessageEvent) => void) | null = null;
					constructor() {
						sendJob = (status) =>
							this.onmessage?.(
								new MessageEvent('message', { data: JSON.stringify({ ...job, status }) })
							);
					}
					close() {
						/* The controlled stream has no resources to release. */
					}
				}
			);
			const select = target.querySelector('select');
			const load = findButtonByText(target, words['workerPool.load']);
			if (!select || !load) throw new Error('Expected load controls');
			select.value = 'turbo';
			select.dispatchEvent(new Event('change', { bubbles: true }));
			await tick();
			load.click();
			await tick();
			expect(load).toBeDisabled();
			expect(select).toBeDisabled();
			load.click();
			expect(requests).toEqual([
				{
					path: '/api/admin/workers/acestep-worker-0/load_model',
					method: 'POST',
					body: { mode: 'turbo' }
				}
			]);
			finish(
				Response.json(refused ? { detail: 'Worker refused load' } : job, {
					status: refused ? 503 : 200
				})
			);
			if (refused) {
				await vi.waitFor(() =>
					expect(target.querySelector('.panel-error')).toHaveTextContent('Worker refused load')
				);
			} else {
				await vi.waitFor(() =>
					expect(
						target.querySelector(`[aria-label="${words['workerPool.models']}"]`)
					).toHaveTextContent('None yet — turbo is loading.')
				);
				expect(load).toBeDisabled();
				expect(select).toBeDisabled();
				poolResponse = onlineWorkerPool();
				sendJob('completed');
				await vi.waitFor(() =>
					expect(
						target.querySelector(`[aria-label="${words['workerPool.models']}"]`)
					).toHaveTextContent('sft')
				);
			}
			await vi.waitFor(() => expect(load).toBeEnabled());
			expect(select).toBeEnabled();
		}
	);
});

describe('WorkerPoolPanel restart confirmation', () => {
	it.each(['Cancel', 'Escape', 'Back'])(
		'S18-1 S18-2 cancels with %s, restores focus and reopens without sending',
		async (method) => {
			const target = await renderWorkerPool(onlineWorkerPool());
			const requests: string[] = [];
			vi.stubGlobal('fetch', (path: string) => {
				requests.push(path);
				return fetchWorkers();
			});
			for (let attempt = 0; attempt < 2; attempt++) {
				const { opener, dialog, cancel, restart } = await openRestartConfirmation(target);
				expect(dialog).toHaveAttribute(
					'aria-label',
					words['workerPool.restartTitle']({ worker: 'acestep-worker-0' })
				);
				expect(dialog).toHaveTextContent(words['workerPool.restartWarning']);
				expect(cancel).toHaveFocus();
				cancel.dispatchEvent(
					new KeyboardEvent('keydown', {
						key: 'Tab',
						shiftKey: true,
						bubbles: true,
						cancelable: true
					})
				);
				expect(restart).toHaveFocus();
				restart.dispatchEvent(
					new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
				);
				expect(cancel).toHaveFocus();
				if (method === 'Cancel') cancel.click();
				else if (method === 'Back') dropLayersFrom(0);
				else
					cancel.dispatchEvent(
						new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
					);
				await tick();
				await tick();
				expect(target.querySelector('[role="dialog"]')).toBeNull();
				expect(opener).toHaveFocus();
				expect(closeTopLayer()).toBe(false);
			}
			expect(requests).toEqual([]);
		}
	);

	it.each([false, true])(
		'S18-1 S18-2 S18-3 targets the selected worker once and recovers after refusal=%s',
		async (refused) => {
			const pool = onlineWorkerPool();
			const second = structuredClone(pool.workers[0]);
			second.identity.id = 'acestep-worker-1';
			pool.workers.push(second);
			const target = await renderWorkerPool(pool);
			const requests: { path: string; method?: string }[] = [];
			let finish!: (response: Response) => void;
			vi.stubGlobal('fetch', (path: string, init: RequestInit) => {
				if (path === '/api/admin/workers') return fetchWorkers();
				requests.push({ path, method: init.method });
				return new Promise<Response>((resolve) => {
					finish = resolve;
				});
			});
			const card = target.querySelectorAll<HTMLElement>('.card')[1];
			const { opener, restart } = await openRestartConfirmation(card);
			expect(target.querySelectorAll('[role="dialog"]')).toHaveLength(1);
			expect(card.querySelector('[role="dialog"]')).toHaveAttribute(
				'aria-label',
				words['workerPool.restartTitle']({ worker: 'acestep-worker-1' })
			);
			expect(requests).toEqual([]);
			restart.click();
			await tick();
			expect(opener).toBeDisabled();
			opener.click();
			expect(requests).toEqual([
				{ path: '/api/admin/workers/acestep-worker-1/restart', method: 'POST' }
			]);
			finish(
				Response.json(refused ? { detail: 'Worker refused restart' } : {}, {
					status: refused ? 503 : 200
				})
			);
			await vi.waitFor(() => expect(opener).toBeEnabled());
			if (refused)
				expect(target.querySelector('.panel-error')).toHaveTextContent('Worker refused restart');
			else
				expect(
					get(toasts).some((toast) => toast.message === 'Restart requested for acestep-worker-1')
				).toBe(true);
			const { restart: retry } = await openRestartConfirmation(card);
			expect(card.querySelector('[role="dialog"]')).not.toBeNull();
			expect(requests).toHaveLength(1);
			retry.click();
			await tick();
			expect(requests).toHaveLength(2);
			finish(Response.json({}));
			await vi.waitFor(() => expect(opener).toBeEnabled());
			expect(target.querySelector('.panel-error')).toBeNull();
		}
	);

	it.each(['offline', 'removed', 'forbidden', 'unmounted'])(
		'S18-2 S18-5 respects a worker becoming %s while confirmation is open',
		async (change) => {
			vi.useFakeTimers();
			const target = await renderWorkerPool(onlineWorkerPool());
			const { cancel, restart } = await openRestartConfirmation(target);
			const requests: string[] = [];
			vi.stubGlobal('fetch', (path: string) => {
				if (path === '/api/admin/workers') return fetchWorkers();
				requests.push(path);
				return Promise.resolve(Response.json({}));
			});
			if (change === 'offline') poolResponse.workers[0].status = 'offline';
			if (change === 'removed') poolResponse.workers = [];
			if (change === 'forbidden')
				poolFailure = Response.json({ detail: 'Forbidden' }, { status: 403 });
			if (change === 'unmounted') {
				if (!mounted) throw new Error('Expected mounted panel');
				await unmount(mounted);
				mounted = undefined;
			} else await vi.advanceTimersByTimeAsync(3000);
			if (change === 'offline') {
				expect(restart).toBeDisabled();
				restart.click();
				expect(target).toHaveTextContent(words['workerPool.vramOffline']);
				cancel.click();
				await tick();
			}
			expect(target.querySelector('[role="dialog"]')).toBeNull();
			expect(closeTopLayer()).toBe(false);
			expect(requests).toEqual([]);
		}
	);
});

describe('WorkerPoolPanel last error', () => {
	it.each([
		{
			name: 'timestamp',
			error: '<img src=x onerror=alert(1)> GPU failed',
			timestamp: '2026-10-18T10:02:00Z'
		},
		{ name: 'missing timestamp', error: 'GPU failed', timestamp: null },
		{ name: 'invalid timestamp', error: 'GPU failed', timestamp: 'invalid' },
		{ name: 'no error', error: null, timestamp: '2026-10-18T10:02:00Z' },
		{ name: 'old heartbeat', error: undefined, timestamp: undefined }
	])('S18-4 S18-5 displays $name honestly as text', async ({ error, timestamp }) => {
		vi.useFakeTimers();
		vi.setSystemTime(new Date('2026-10-18T10:05:00Z'));
		const pool = onlineWorkerPool();
		if (!pool.workers[0].state) throw new Error('Expected heartbeat');
		Object.assign(pool.workers[0].state, { last_error: error, last_error_at: timestamp });
		const target = await renderWorkerPool(pool);
		const box = target.querySelector('.last-error');
		if (!error) {
			expect(box).toBeNull();
			return;
		}
		expect(box).toHaveTextContent(words['workerPool.lastError']);
		expect(box).toHaveTextContent(error);
		expect(box).toHaveTextContent('Full logs: docker compose logs acestep-worker-0');
		expect(box?.querySelector('img')).toBeNull();
		expect(box?.previousElementSibling).toHaveClass('load-row');
		expect(box?.nextElementSibling).toHaveTextContent(words['workerPool.restart']);
		if (timestamp && timestamp !== 'invalid') {
			expect(box?.querySelector('time')).toHaveAttribute('datetime', timestamp);
			expect(box?.querySelector('time')).toHaveTextContent(
				`${localClockTime(new Date(timestamp))} · 3m ago`
			);
		} else expect(box?.querySelector('time')).toBeNull();
	});

	it.each([true, false])(
		'S18-7 hides offline VRAM with a heartbeat, measured=%s',
		async (measured) => {
			vi.useFakeTimers();
			const pool = workerPool(measured);
			pool.workers[0].status = 'offline';
			const target = await renderWorkerPool(pool);
			const row = target.querySelector('[aria-label="VRAM"]');
			expect(row).toHaveTextContent(words['workerPool.vramUnknown']);
			expect(row).toHaveTextContent(words['workerPool.vramOffline']);
			expect(row).not.toHaveTextContent('GB');
			expect(row).not.toHaveTextContent('No heartbeat');
			expect(row?.querySelector('.bar span')).toBeNull();
			poolResponse.workers[0].status = 'online';
			await vi.advanceTimersByTimeAsync(3000);
			expect(row).toHaveTextContent('12.4 / 24.0 GB');
			expect(row).not.toHaveTextContent(words['workerPool.vramUnknown']);
		}
	);
});
