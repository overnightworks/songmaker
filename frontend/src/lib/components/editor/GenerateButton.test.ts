import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
	EDITOR_GENERATE_CANCEL_LABEL,
	EDITOR_GENERATE_FAILURE_COLLAPSE_LABEL,
	EDITOR_GENERATE_FAILURE_EXPAND_LABEL,
	EDITOR_GPU_OFFLINE_TITLE,
	HITBOX_FREQUENT_PX
} from '$lib/constants';
import { getByRoleButton } from '$lib/test-utils/accessible-name';
import {
	clearHitboxStyles,
	clearPointer,
	injectHitboxStyles,
	minSquarePx,
	setPointer
} from '$lib/test-utils/hitbox';

const action = await vi.hoisted(async () => {
	const { writable } = await import('svelte/store');
	return writable<{ state: GenerateState }>({ state: { kind: 'idle', mode: 'generate' } });
});
vi.mock('$lib/stores/generateAction', () => ({ generateAction: action, generate: vi.fn() }));
vi.mock('$lib/api/client', () => ({ cancelJob: vi.fn() }));
vi.mock('$lib/stores/toast', () => ({ addToast: vi.fn() }));

import { cancelJob } from '$lib/api/client';
import { generate, type GenerateState } from '$lib/stores/generateAction';
import { addToast } from '$lib/stores/toast';
import GenerateButton from './GenerateButton.svelte';

const running: Extract<GenerateState, { kind: 'generating' }> = {
	kind: 'generating',
	jobId: 'job1',
	takeIndex: 1,
	takeCount: 2,
	progress: 36,
	remaining: 100
};
const queued: Extract<GenerateState, { kind: 'queued' }> = {
	kind: 'queued',
	jobId: 'job1',
	position: 3,
	reason: 'Waiting for LoRA training on this GPU.'
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

async function render(state: GenerateState): Promise<void> {
	action.set({ state });
	component = mount(GenerateButton, { target: document.body });
	await tick();
}

describe('GenerateButton', () => {
	it.each([
		['generate', 'Generate'],
		['repaint', 'Repaint'],
		['cover', 'Cover']
	] as const)('generates in %s mode with a single word and no version', async (mode, label) => {
		await render({ kind: 'idle', mode });
		const button = getByRoleButton(document.body, label);
		expect(button.disabled).toBe(false);
		expect(document.body.querySelectorAll('button')).toHaveLength(1);
		button.click();
		expect(generate).toHaveBeenCalledOnce();
	});

	it('shows the queue position and reason and cancels the queued job', async () => {
		await render(queued);
		expect(document.body.querySelector('[role="status"]')?.textContent?.trim()).toBe('Queued #3');
		expect(document.body.textContent).toContain(queued.reason);
		const cancel = getByRoleButton(document.body, EDITOR_GENERATE_CANCEL_LABEL);
		expect(minSquarePx(cancel, EDITOR_GENERATE_CANCEL_LABEL)).toEqual({
			width: HITBOX_FREQUENT_PX,
			height: HITBOX_FREQUENT_PX
		});
		cancel.click();
		await tick();
		expect(cancelJob).toHaveBeenCalledExactlyOnceWith('job1');
		expect(generate).not.toHaveBeenCalled();
	});

	it('does not invent a missing queue position', async () => {
		await render({ ...queued, position: null });
		expect(document.body.querySelector('[role="status"]')?.textContent?.trim()).toBe('Queued');
	});

	it.each([
		{ remaining: 100, expected: 'Take 1 of 2 · 36% · ~1:40' },
		{ remaining: 'calculating', expected: 'Take 1 of 2 · 36%' },
		{ remaining: null, expected: 'Take 1 of 2 · 36%' }
	] as const)(
		'renders progress with remaining time $remaining',
		async ({ remaining, expected }) => {
			await render({ ...running, remaining });
			expect(
				document.body.querySelector('[role="status"]')?.textContent?.replace(/\s+/g, ' ').trim()
			).toBe(expected);
			getByRoleButton(document.body, EDITOR_GENERATE_CANCEL_LABEL).click();
			await tick();
			expect(cancelJob).toHaveBeenCalledExactlyOnceWith('job1');
		}
	);

	it('omits the take counter for a single take', async () => {
		await render({ ...running, takeCount: 1 });
		expect(document.body.textContent).toContain('Generating...');
		expect(document.body.textContent).not.toContain('Take 1 of 1');
	});

	it('shows submission progress without offering cancellation before a job exists', async () => {
		await render({
			...running,
			jobId: null,
			takeIndex: null,
			takeCount: null,
			progress: 0,
			remaining: null
		});
		expect(document.body.textContent).toContain('0%');
		expect(document.body.querySelector('button')).toBeNull();
	});

	it('surfaces a cancellation failure', async () => {
		vi.mocked(cancelJob).mockRejectedValue(new Error('Worker unavailable'));
		await render(running);
		getByRoleButton(document.body, EDITOR_GENERATE_CANCEL_LABEL).click();
		await tick();
		expect(addToast).toHaveBeenCalledWith('Worker unavailable', 'error');
	});

	it('disables generation with a visible reason and matching title', async () => {
		await render({ kind: 'disabled', mode: 'generate', reason: EDITOR_GPU_OFFLINE_TITLE });
		const button = getByRoleButton(document.body, 'Generate');
		expect(button.disabled).toBe(true);
		expect(button.title).toBe(EDITOR_GPU_OFFLINE_TITLE);
		expect(document.body.textContent).toContain(`ⓘ ${EDITOR_GPU_OFFLINE_TITLE}`);
		button.click();
		expect(generate).not.toHaveBeenCalled();
	});

	it('expands and collapses the literal worker sentence and retries through Generate', async () => {
		const cause =
			'Generation failed because the worker exhausted GPU memory while processing the second take. Reduce the batch size and try again.';
		await render({ kind: 'failed', mode: 'generate', cause });
		const expand = getByRoleButton(document.body, EDITOR_GENERATE_FAILURE_EXPAND_LABEL);
		const sentence = document.getElementById(expand.getAttribute('aria-controls') ?? '');
		expect(sentence?.textContent).toBe(cause);
		expect(expand.getAttribute('aria-expanded')).toBe('false');
		expect(minSquarePx(expand, EDITOR_GENERATE_FAILURE_EXPAND_LABEL)).toEqual({
			width: HITBOX_FREQUENT_PX,
			height: HITBOX_FREQUENT_PX
		});
		expand.click();
		await tick();
		const collapse = getByRoleButton(document.body, EDITOR_GENERATE_FAILURE_COLLAPSE_LABEL);
		expect(collapse.getAttribute('aria-expanded')).toBe('true');
		expect(sentence?.textContent).toBe(cause);
		collapse.click();
		await tick();
		expect(
			getByRoleButton(document.body, EDITOR_GENERATE_FAILURE_EXPAND_LABEL).getAttribute(
				'aria-expanded'
			)
		).toBe('false');
		getByRoleButton(document.body, 'Generate').click();
		expect(generate).toHaveBeenCalledOnce();
	});
});
