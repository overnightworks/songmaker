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
import { EDITOR_GENERATE_LAST_SEEN_PROGRESS_LABEL, HITBOX_FREQUENT_PX } from '$lib/constants';
import { clearComponentStyles, injectComponentStyles } from '$lib/test-utils/component-styles';

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
import generationStatusSlotSource from './GenerationStatusSlot.svelte?raw';

const running: Extract<GenerateState, { kind: 'generating' }> = {
	kind: 'generating',
	jobId: 'job1',
	phase: 'Rendering',
	takeCounter: 'Take 1 of 2',
	progress: 36,
	readout: '36% · ~1:40',
	ended: false,
	reconnecting: false
};

const queued: Extract<GenerateState, { kind: 'queued' }> = {
	kind: 'queued',
	jobId: 'job1',
	label: 'Queued #3',
	reason: 'Waiting for LoRA training on this GPU.',
	reconnecting: false
};

const reconnecting: Extract<GenerateState, { kind: 'generating' }> = {
	...running,
	phase: 'Reconnecting…',
	progress: 40,
	readout: 'last seen at 40%',
	reconnecting: true
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
	clearComponentStyles();
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

	it('keeps the card of a finished job waiting for its take, without a cancel', async () => {
		await render({ ...running, progress: 100, ended: true });
		expect(document.body.querySelector('[role="progressbar"]')).not.toBeNull();
		expect(document.body.querySelector('button')).toBeNull();
	});

	describe('while the page is offline', () => {
		function styledSlot(): HTMLElement {
			const slot = document.body.querySelector<HTMLElement>('.status-slot');
			if (!slot) throw new Error('Expected the status slot');
			injectComponentStyles(generationStatusSlotSource, 'GenerationStatusSlot.svelte', slot);
			return slot;
		}

		it('reads "Reconnecting…" with the last seen progress instead of a ticking readout', async () => {
			await render(reconnecting);
			const slot = styledSlot();
			expect(slot.textContent?.replace(/\s+/g, ' ').trim()).toBe(
				'v8 · Reconnecting… Take 1 of 2 · last seen at 40%'
			);
			expect(slot.textContent).not.toContain('~');
		});

		it('holds the bar at its last width in grey', async () => {
			await render(reconnecting);
			const slot = styledSlot();
			const bar = slot.querySelector('[role="progressbar"]');
			expect(bar?.getAttribute('aria-label')).toBe(EDITOR_GENERATE_LAST_SEEN_PROGRESS_LABEL);
			expect(bar?.getAttribute('aria-valuenow')).toBe('40');
			const fill = bar?.querySelector('span');
			if (!fill) throw new Error('Expected the bar fill');
			expect(fill.style.width).toBe('40%');
			expect(getComputedStyle(fill).getPropertyValue('background')).toBe('var(--text-disabled)');
		});

		it.each([
			{ state: 'running', presentation: reconnecting },
			{ state: 'queued', presentation: { ...queued, reconnecting: true } }
		])(
			'greys the cancel of a $state take and names it unavailable, not waiting, while offline',
			async ({ presentation }) => {
				await render(presentation);
				const slot = styledSlot();
				const cancel = getByRoleButton(slot, 'Cancel generation (unavailable while offline)');
				expect(cancel.getAttribute('aria-disabled')).toBe('true');
				expect(getComputedStyle(cancel).color).toBe('var(--text-disabled)');
				cancel.click();
				await tick();
				expect(cancelGeneration).not.toHaveBeenCalled();
			}
		);
	});
});
