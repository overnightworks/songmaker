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

vi.mock('$lib/stores/generateAction', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/stores/generateAction')>()),
	cancelGeneration: vi.fn()
}));

import { cancelGeneration } from '$lib/stores/generateAction';
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
			expect(document.body.querySelector('.status-slot')).toBeNull();
		}
	);

	it('renders nothing without a job', async () => {
		await render(null);
		expect(document.body.querySelector('.status-slot')).toBeNull();
	});

	it('shows the version, the take counter, the percent and the ETA while running, without repeating "Generating…"', async () => {
		await render(runningJob);
		const slot = document.body.querySelector('.status-slot');
		expect(slot?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
			'v8 · Generating... Take 1 of 2 · 36% · ~1:40'
		);
		expect(document.body.querySelector('[role="progressbar"]')?.getAttribute('aria-valuenow')).toBe(
			'36'
		);
	});

	it('omits the take counter for a single take and shows the percent alone on its line', async () => {
		await render({ ...runningJob, take_count: 1 });
		const slot = document.body.querySelector('.status-slot');
		expect(slot?.textContent).not.toContain('Take 1 of 1');
		expect(slot?.querySelector('.status-line')?.textContent).toBe('36% · ~1:40');
	});

	it('omits the ETA while it is still calculating', async () => {
		await render({ ...runningJob, remaining_time_estimate: 'calculating' });
		expect(document.body.textContent).not.toContain('~');
	});

	it('shows the queue position in the title, and the reason on its own line', async () => {
		await render(queuedJob);
		const slot = document.body.querySelector('.status-slot');
		expect(slot?.querySelector('.status-title')?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
			'v8 · Queued #3'
		);
		expect(slot?.querySelector('.status-line.reason')?.textContent).toBe(
			'Waiting for LoRA training on this GPU.'
		);
	});

	it('does not invent a missing queue position', async () => {
		await render({ ...queuedJob, queue_position: null });
		const slot = document.body.querySelector('.status-slot');
		expect(slot?.querySelector('.status-title')?.textContent).toContain('Queued');
		expect(slot?.querySelector('.status-title')?.textContent).not.toContain('#');
	});

	it('does not add a second live region for the job the Generate button already announces', async () => {
		await render(runningJob);
		expect(document.body.querySelectorAll('[role="status"]')).toHaveLength(0);
		expect(document.body.querySelector('[role="progressbar"]')).not.toBeNull();
	});

	it('cancels the job through the shared cancelGeneration owner at a 44px hitbox', async () => {
		await render(runningJob);
		const cancel = getByRoleButton(document.body, 'Cancel generation');
		expect(minSquarePx(cancel, 'Cancel generation')).toEqual({
			width: HITBOX_FREQUENT_PX,
			height: HITBOX_FREQUENT_PX
		});
		cancel.click();
		await tick();
		expect(cancelGeneration).toHaveBeenCalledExactlyOnceWith('job1');
	});
});
