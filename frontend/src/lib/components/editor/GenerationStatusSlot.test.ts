import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { JobItem } from '$lib/api/types';
import { getByRoleButton } from '$lib/test-utils/accessible-name';
import {
	clearHitboxStyles,
	clearPointer,
	injectHitboxStyles,
	minSquarePx,
	setPointer
} from '$lib/test-utils/hitbox';
import { HITBOX_FREQUENT_PX } from '$lib/constants';

vi.mock('$lib/api/client', () => ({ cancelJob: vi.fn() }));
vi.mock('$lib/stores/toast', () => ({ addToast: vi.fn() }));

import { cancelJob } from '$lib/api/client';
import { addToast } from '$lib/stores/toast';
import GenerationStatusSlot from './GenerationStatusSlot.svelte';

const runningJob: JobItem = {
	id: 'job1',
	type: 'generate',
	status: 'running',
	progress: 0.36,
	take_index: 1,
	take_count: 2,
	remaining_time_estimate: 100
};

const queuedJob: JobItem = {
	id: 'job1',
	type: 'generate',
	status: 'queued',
	progress: 0,
	queue_position: 3,
	queue_reason: 'Waiting for LoRA training on this GPU.'
};

let component: ReturnType<typeof mount>;

beforeEach(() => {
	vi.resetAllMocks();
	injectHitboxStyles();
	setPointer('coarse');
});

afterEach(async () => {
	await unmount(component);
	document.body.replaceChildren();
	clearHitboxStyles();
	clearPointer();
});

async function render(job: JobItem | null, latestVersionNumber = 8): Promise<void> {
	component = mount(GenerationStatusSlot, {
		target: document.body,
		props: { job, latestVersionNumber }
	});
	await tick();
}

describe('GenerationStatusSlot', () => {
	it.each(['completed', 'partial', 'failed', 'cancelled'] as const)(
		'renders nothing for a %s job',
		async (status) => {
			await render({ ...runningJob, status });
			expect(document.body.querySelector('[role="status"]')).toBeNull();
		}
	);

	it('renders nothing without a job', async () => {
		await render(null);
		expect(document.body.querySelector('[role="status"]')).toBeNull();
	});

	it('shows the version, the take counter, the percent and the ETA while running', async () => {
		await render(runningJob);
		const slot = document.body.querySelector('[role="status"]');
		expect(slot?.textContent?.replace(/\s+/g, ' ').trim()).toContain(
			'v8 · Generating... Take 1 of 2 · 36% · ~1:40'
		);
		expect(document.body.querySelector('[role="progressbar"]')?.getAttribute('aria-valuenow')).toBe(
			'36'
		);
	});

	it('omits the take counter for a single take', async () => {
		await render({ ...runningJob, take_count: 1 });
		expect(document.body.textContent).not.toContain('Take 1 of 1');
		expect(document.body.textContent).toContain('Generating...');
	});

	it('omits the ETA while it is still calculating', async () => {
		await render({ ...runningJob, remaining_time_estimate: 'calculating' });
		expect(document.body.textContent).not.toContain('~');
	});

	it('shows the queue position and the reason on its own line', async () => {
		await render(queuedJob);
		const slot = document.body.querySelector('[role="status"]');
		expect(slot?.textContent?.replace(/\s+/g, ' ').trim()).toContain(
			'v8 · Queued Queued #3 Waiting for LoRA training on this GPU.'
		);
	});

	it('does not invent a missing queue position', async () => {
		await render({ ...queuedJob, queue_position: null });
		expect(document.body.querySelector('[role="status"]')?.textContent).toContain('Queued');
		expect(document.body.querySelector('[role="status"]')?.textContent).not.toContain('#');
	});

	it('cancels the job at a 44px hitbox', async () => {
		await render(runningJob);
		const cancel = getByRoleButton(document.body, 'Cancel generation');
		expect(minSquarePx(cancel, 'Cancel generation')).toEqual({
			width: HITBOX_FREQUENT_PX,
			height: HITBOX_FREQUENT_PX
		});
		cancel.click();
		await tick();
		expect(cancelJob).toHaveBeenCalledExactlyOnceWith('job1');
	});

	it('surfaces a cancellation failure', async () => {
		vi.mocked(cancelJob).mockRejectedValue(new Error('Worker unavailable'));
		await render(runningJob);
		getByRoleButton(document.body, 'Cancel generation').click();
		await tick();
		expect(addToast).toHaveBeenCalledWith('Worker unavailable', 'error');
	});
});
