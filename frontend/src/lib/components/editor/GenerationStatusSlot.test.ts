import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getByRoleButton } from '$lib/test-utils/accessible-name';
import {
	clearHitboxStyles,
	clearPointer,
	injectHitboxStyles,
	minSquarePx,
	setPointer
} from '$lib/test-utils/hitbox';
import { HITBOX_FREQUENT_PX } from '$lib/constants';

const action = await vi.hoisted(async () => {
	const { writable } = await import('svelte/store');
	return writable<GenerateState>({ kind: 'idle', mode: 'generate' });
});
vi.mock('$lib/stores/generateAction', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/stores/generateAction')>()),
	generateAction: action,
	cancelGeneration: vi.fn()
}));

import { cancelGeneration, type GenerateState } from '$lib/stores/generateAction';
import GenerationStatusSlot from './GenerationStatusSlot.svelte';

const running: Extract<GenerateState, { kind: 'generating' }> = {
	kind: 'generating',
	jobId: 'job1',
	phase: 'Rendering',
	takeCounter: 'Take 1 of 2',
	progress: 36,
	readout: '36% · ~1:40',
	reconnecting: false
};

const queued: Extract<GenerateState, { kind: 'queued' }> = {
	kind: 'queued',
	jobId: 'job1',
	label: 'Queued #3',
	reason: 'Waiting for LoRA training on this GPU.',
	reconnecting: false
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

async function render(state: GenerateState, latestVersionNumber = 8): Promise<void> {
	action.set(state);
	component = mount(GenerationStatusSlot, {
		target: document.body,
		props: { latestVersionNumber }
	});
	await tick();
}

describe('GenerationStatusSlot', () => {
	it.each([
		{ kind: 'idle', mode: 'generate' },
		{ kind: 'disabled', mode: 'generate', reason: 'No models' },
		{ kind: 'failed', mode: 'generate', cause: 'Worker error' }
	] as const)('renders nothing while the generate action is $kind', async (state) => {
		await render(state);
		expect(document.body.querySelector('.status-slot')).toBeNull();
	});

	it.each([
		{
			phase: 'Loading model…',
			readout: null,
			expected: 'v8 · Loading model… Take 1 of 2'
		},
		{
			phase: 'Writing',
			readout: '36% · ~1:40',
			expected: 'v8 · Writing Take 1 of 2 · 36% · ~1:40'
		},
		{
			phase: 'Rendering',
			readout: '36% · ~1:40',
			expected: 'v8 · Rendering Take 1 of 2 · 36% · ~1:40'
		},
		{
			phase: 'Saving take',
			readout: '36%',
			expected: 'v8 · Saving take Take 1 of 2 · 36%'
		},
		{
			phase: 'Generating...',
			readout: '36% · ~1:40',
			expected: 'v8 · Generating... Take 1 of 2 · 36% · ~1:40'
		}
	] as const)(
		'titles the version with its phase and reads out the take as "$expected"',
		async ({ phase, readout, expected }) => {
			await render({ ...running, phase, readout });
			const slot = document.body.querySelector('.status-slot');
			expect(slot?.textContent?.replace(/\s+/g, ' ').trim()).toBe(expected);
			expect(
				document.body.querySelector('[role="progressbar"]')?.getAttribute('aria-valuenow')
			).toBe('36');
		}
	);

	it('omits the take counter for a single take and shows the readout alone on its line', async () => {
		await render({ ...running, takeCounter: null });
		const slot = document.body.querySelector('.status-slot');
		expect(slot?.textContent).not.toContain('Take 1 of 1');
		expect(slot?.querySelector('.status-line')?.textContent).toBe('36% · ~1:40');
	});

	it('leaves out the status line while a single take loads its model', async () => {
		await render({ ...running, phase: 'Loading model…', takeCounter: null, readout: null });
		expect(document.body.querySelector('.status-line')).toBeNull();
	});

	it('shows the queue position in the title, and the reason on its own line', async () => {
		await render(queued);
		const slot = document.body.querySelector('.status-slot');
		expect(slot?.querySelector('.status-title')?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
			'v8 · Queued #3'
		);
		expect(slot?.querySelector('.status-line.reason')?.textContent).toBe(
			'Waiting for LoRA training on this GPU.'
		);
	});

	it('stays hidden while Generate is submitting and no job exists yet', async () => {
		await render({ ...running, jobId: null, takeCounter: null, progress: 0, readout: '0%' });
		expect(document.body.querySelector('.status-slot')).toBeNull();
	});

	it('does not add a second live region for the job the Generate button already announces', async () => {
		await render(running);
		expect(document.body.querySelectorAll('[role="status"]')).toHaveLength(0);
		expect(document.body.querySelector('[role="progressbar"]')).not.toBeNull();
	});

	it('cancels the job through the shared cancelGeneration owner at a 44px hitbox', async () => {
		await render(running);
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
