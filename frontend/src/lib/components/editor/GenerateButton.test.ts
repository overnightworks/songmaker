import { currentUser } from '$lib/stores/auth';
import { mount, tick, unmount } from 'svelte';
import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
	EDITOR_GENERATE_CANCEL_LABEL,
	EDITOR_GENERATE_CANCEL_OFFLINE_LABEL,
	EDITOR_GENERATE_LABEL,
	EDITOR_MISSING_CONTENT_TITLE,
	EDITOR_NO_MODELS_WARNING,
	EDITOR_SELECT_MODEL_TITLE,
	HITBOX_FREQUENT_PX
} from '$lib/constants';
import { seedFromTake } from '$lib/stores/recipe';
import { getByRoleButton } from '$lib/test-utils/accessible-name';
import { clearComponentStyles, injectComponentStyles } from '$lib/test-utils/component-styles';
import { failed, queued, running } from '$lib/test-utils/generate-states';
import {
	clearHitboxStyles,
	clearPointer,
	injectHitboxStyles,
	minSquarePx,
	setPointer
} from '$lib/test-utils/hitbox';

const action = await vi.hoisted(async () => {
	const { writable } = await import('svelte/store');
	return writable<GenerateState>({ kind: 'idle' });
});
vi.mock('$lib/stores/generateAction', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/stores/generateAction')>()),
	generateAction: action,
	generate: vi.fn(),
	cancelGeneration: vi.fn()
}));

import { cancelGeneration, generate, type GenerateState } from '$lib/stores/generateAction';
import GenerateButton from './GenerateButton.svelte';
import generateButtonSource from './GenerateButton.svelte?raw';

let component: ReturnType<typeof mount>;

beforeEach(() => {
	vi.resetAllMocks();
	currentUser.set(null);
	seedFromTake.set(null);
	injectHitboxStyles();
	setPointer('coarse');
});

afterEach(async () => {
	await unmount(component);
	document.body.replaceChildren();
	clearHitboxStyles();
	clearComponentStyles();
	clearPointer();
	currentUser.set(null);
});

async function render(state: GenerateState, props: { reasonInside?: boolean } = {}): Promise<void> {
	action.set(state);
	component = mount(GenerateButton, { target: document.body, props });
	await tick();
}

describe('GenerateButton', () => {
	it.each([null, '0:03', '0:12', '12:34'])(
		'[defect:#1568:H2:H3] reserves a silent elapsed slot for %s',
		async (elapsedLabel) => {
			await render({
				...running,
				phase: 'Loading model…',
				indeterminate: true,
				readout: null,
				elapsedLabel
			});
			const elapsed = document.body.querySelector('.elapsed-time');
			if (!elapsed) throw new Error('Expected an elapsed slot');
			expect(elapsed.getAttribute('aria-hidden')).toBe('true');
			expect(elapsed.textContent?.trim()).toBe(elapsedLabel ?? '');
			injectComponentStyles(generateButtonSource, 'GenerateButton.svelte', elapsed);
			expect(parseFloat(getComputedStyle(elapsed).minWidth)).toBeGreaterThan(0);
			expect(getComputedStyle(elapsed).fontVariantNumeric).toBe('tabular-nums');
		}
	);

	it('generates with a single word and no version (S4, #1923 acceptance 3)', async () => {
		await render({ kind: 'idle' });
		const button = getByRoleButton(document.body, EDITOR_GENERATE_LABEL);
		expect(button.disabled).toBe(false);
		expect(document.body.querySelectorAll('button')).toHaveLength(1);
		button.click();
		expect(generate).toHaveBeenCalledOnce();
	});

	it('C3: shows no seed chip without a seed', async () => {
		await render({ kind: 'idle' });
		expect(document.body.textContent).not.toContain('Seed');
	});

	it.each([
		{ state: 'idle', view: { kind: 'idle' } as GenerateState },
		{ state: 'running', view: running }
	])(
		'C3: shows the seed chip with the take while $state and clears it with ×',
		async ({ view }) => {
			seedFromTake.set({ seed: 4127730, takeNumber: 11 });
			await render(view);
			expect(document.body.querySelector('.seed-chip')?.textContent?.trim()).toBe('Seed · take 11');
			getByRoleButton(document.body, 'Clear seed').click();
			await tick();
			expect(document.body.querySelector('.seed-chip')).toBeNull();
			expect(get(seedFromTake)).toBeNull();
		}
	);

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
		expect(cancelGeneration).toHaveBeenCalledExactlyOnceWith('job1');
		expect(generate).not.toHaveBeenCalled();
	});

	it.each([
		{
			phase: 'Loading model…',
			readout: null,
			elapsedLabel: null,
			expected: 'Take 1 of 2 · Loading model…'
		},
		{
			phase: 'Loading model…',
			readout: null,
			elapsedLabel: '0:12',
			expected: 'Take 1 of 2 · Loading model… 0:12'
		},
		{ phase: 'Writing', readout: '36% · ~1:40', expected: 'Take 1 of 2 · Writing · 36% · ~1:40' },
		{
			phase: 'Rendering',
			readout: '36% · ~1:40',
			expected: 'Take 1 of 2 · Rendering · 36% · ~1:40'
		},
		{ phase: 'Saving take', readout: '36%', expected: 'Take 1 of 2 · Saving take · 36%' },
		{
			phase: 'Generating...',
			readout: '36% · ~1:40',
			expected: 'Take 1 of 2 · Generating... · 36% · ~1:40'
		}
	] as const)(
		'[defect:#1568] names the take, its phase and its readout as "$expected"',
		async ({ phase, readout, expected, elapsedLabel = null }) => {
			await render({ ...running, phase, readout, elapsedLabel, indeterminate: readout === null });
			expect(
				document.body.querySelector('[role="status"]')?.textContent?.replace(/\s+/g, ' ').trim()
			).toBe(expected);
			getByRoleButton(document.body, EDITOR_GENERATE_CANCEL_LABEL).click();
			await tick();
			expect(cancelGeneration).toHaveBeenCalledExactlyOnceWith('job1');
		}
	);

	it('names only the phase and its readout for a single take', async () => {
		await render({ ...running, takeCounter: null });
		expect(
			document.body.querySelector('[role="status"]')?.textContent?.replace(/\s+/g, ' ').trim()
		).toBe('Rendering · 36% · ~1:40');
	});

	it('shows submission progress without offering cancellation before a job exists', async () => {
		await render({
			...running,
			jobId: null,
			phase: 'Generating...',
			takeCounter: null,
			progress: 0,
			readout: '0%'
		});
		expect(document.body.textContent).toContain('0%');
		expect(document.body.querySelector('button')).toBeNull();
	});

	it.each([
		['no active models', EDITOR_NO_MODELS_WARNING],
		['no model selected', EDITOR_SELECT_MODEL_TITLE],
		['missing lyrics or style prompt', EDITOR_MISSING_CONTENT_TITLE]
	] as const)(
		'disables generation as an outline button with its %s reason under ⓘ',
		async (_state, reason) => {
			await render({ kind: 'disabled', reason });
			const button = getByRoleButton(document.body, 'Generate');
			expect(button.disabled).toBe(true);
			expect(button.title).toBe(reason);
			expect(document.body.textContent).toContain(`ⓘ ${reason}`);
			button.click();
			expect(generate).not.toHaveBeenCalled();
		}
	);

	it('carries the disabled reason inside the one outline button in the slim phone bar', async () => {
		await render(
			{ kind: 'disabled', reason: EDITOR_MISSING_CONTENT_TITLE },
			{ reasonInside: true }
		);
		const button = getByRoleButton(document.body, `Generate — ${EDITOR_MISSING_CONTENT_TITLE}`);
		expect(button.disabled).toBe(true);
		expect(button.textContent?.trim()).toBe(`ⓘ ${EDITOR_MISSING_CONTENT_TITLE}`);
		expect(document.body.textContent?.trim()).toBe(button.textContent?.trim());
	});

	it.each([false, true])(
		'keeps its label and shows no ⓘ when disabled without a reason of its own (reason inside: %s)',
		async (reasonInside) => {
			await render({ kind: 'disabled', reason: null }, { reasonInside });
			const button = getByRoleButton(document.body, 'Generate');
			expect(button.disabled).toBe(true);
			expect(button.title).toBe('');
			expect(document.body.textContent?.trim()).toBe('Generate');
		}
	);

	it.each(
		(['admin', 'user'] as const).flatMap((role) =>
			[true, false].map((unavailable) => ({ role, unavailable }))
		)
	)(
		'C1 C4: shows the adjacent worker-pool link only for $role unavailable=$unavailable',
		async ({ role, unavailable }) => {
			currentUser.set({ id: 'u1', username: 'tester', role });
			await render({ ...failed, cause: "Generating isn't available right now.", unavailable });
			const link = document.body.querySelector<HTMLAnchorElement>('a');
			expect(link?.textContent).toBe(
				role === 'admin' && unavailable ? 'Open worker pool' : undefined
			);
			if (link) expect(link.getAttribute('href')).toBe('/settings/users?tab=acestep');
			expect(document.body.querySelector('.failure')?.textContent).toContain(
				"Generating isn't available right now."
			);
		}
	);

	it.each([
		'Too long for the GPU right now — try a shorter duration.',
		"Generating isn't available right now.",
		'Generating failed — try again.'
	])('[defect:#1579] shows the complete failure without an expander: %s', async (cause) => {
		await render({ ...failed, cause });
		const sentence = document.body.querySelector<HTMLElement>('.failure');
		if (!sentence) throw new Error('Expected the failure sentence');
		injectComponentStyles(generateButtonSource, 'GenerateButton.svelte', sentence);
		expect(sentence.textContent).toBe(cause);
		expect(getComputedStyle(sentence).whiteSpace).toBe('pre-wrap');
		expect(getComputedStyle(sentence).overflowWrap).toBe('anywhere');
		expect(getComputedStyle(sentence).overflow).not.toBe('hidden');
		expect(getComputedStyle(sentence).textOverflow).not.toBe('ellipsis');
		expect(document.body.querySelectorAll('button')).toHaveLength(1);
		expect(getByRoleButton(document.body, 'Generate').disabled).toBe(false);
	});

	it.each([
		{ state: 'running', presentation: { ...running, reconnecting: true, offline: true }, fills: 1 },
		{ state: 'queued', presentation: { ...queued, reconnecting: true, offline: true }, fills: 0 }
	])(
		'greys the readout and the cancel of a $state take while the page is offline',
		async ({ presentation, fills }) => {
			await render(presentation);
			const readout = document.body.querySelector<HTMLElement>('[role="status"]');
			if (!readout) throw new Error('Expected the progress readout');
			injectComponentStyles(generateButtonSource, 'GenerateButton.svelte', readout);
			expect(getComputedStyle(readout).color).toBe('var(--text-subtle)');
			const fillBackgrounds = Array.from(
				readout.querySelectorAll<HTMLElement>('.progress-fill'),
				(fill) => getComputedStyle(fill).background
			);
			expect(fillBackgrounds).toEqual(
				Array(fills).fill('color-mix(in srgb, var(--text-disabled) 20%, transparent)')
			);
			const cancel = getByRoleButton(document.body, EDITOR_GENERATE_CANCEL_OFFLINE_LABEL);
			expect(cancel.getAttribute('aria-disabled')).toBe('true');
			expect(getComputedStyle(cancel).color).toBe('var(--text-disabled)');
			cancel.click();
			await tick();
			expect(cancelGeneration).not.toHaveBeenCalled();
		}
	);

	it('keeps the cancel of a take whose stream is refused while the page is online', async () => {
		await render({ ...running, reconnecting: true, offline: false });

		getByRoleButton(document.body, EDITOR_GENERATE_CANCEL_LABEL).click();
		await tick();

		expect(cancelGeneration).toHaveBeenCalledExactlyOnceWith('job1');
	});
});
