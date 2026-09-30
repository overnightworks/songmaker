import { makeGeneration, makeSong } from '$lib/test-utils/factories';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

vi.mock('$lib/api/client', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/api/client')>();
	return {
		...actual,
		fetchPresets: vi.fn().mockResolvedValue([]),
		fetchBuiltinDefaults: vi.fn().mockResolvedValue({}),
		fetchActiveModels: vi.fn().mockResolvedValue([
			{ id: 'turbo', capabilities: {} },
			{ id: 'fast', capabilities: {} }
		]),
		fetchGenerationDefaults: vi.fn().mockResolvedValue({}),
		uploadReferenceAudio: vi.fn(),
		createPreset: vi.fn(),
		fetchVersions: vi.fn().mockResolvedValue([])
	};
});

vi.mock('$app/navigation', async () =>
	(await import('$lib/test-utils/app-navigation')).fakeAppNavigation()
);
vi.mock('$lib/stores/toast', () => ({ addToast: vi.fn() }));

import { goto } from '$app/navigation';
import {
	discardDraft,
	editBpm,
	loadSongData,
	pinnedSeed,
	setDraftBpm,
	setDraftLyrics
} from '$lib/stores/editor';
import { pendingDirtyNavigation } from '$lib/stores/navigation';
import { activeModels } from '$lib/stores/presets';
import {
	clearSource,
	recipeModel,
	setSourceFromGeneration,
	sourceGeneration
} from '$lib/stores/recipe';
import { RECIPE_SAVE_AS_PRESET_LABEL, RECIPE_SOURCE_MODE_HINT } from '$lib/constants';
import { createPreset, uploadReferenceAudio } from '$lib/api/client';
import { ApiError, NetworkError } from '$lib/api/fetch';
import { addToast } from '$lib/stores/toast';
import { getByRoleButton } from '$lib/test-utils/accessible-name';

import RecipePanel from './RecipePanel.svelte';
import recipePanelSource from './RecipePanel.svelte?raw';

const mounted: Array<ReturnType<typeof mount>> = [];

beforeEach(() => {
	loadSongData(
		makeSong({
			slug: 'test',
			title: 'Test',
			lyrics: 'hello',
			prompt: 'rock',
			bpm: 108,
			audio_duration: 195,
			key_scale: 'A',
			generation_params: null,
			generation_count: 0,
			best_scores: null,
			best_rating: null,
			created_at: '',
			share_slug: null
		})
	);
	pinnedSeed.set(null);
	clearSource();
	recipeModel.set('turbo');
	activeModels.set([]);
	vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	discardDraft();
	pendingDirtyNavigation.set(null);
	vi.mocked(goto).mockClear();
});

async function render() {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(RecipePanel, { target, props: { onclose: vi.fn() } }));
	await tick();
	await Promise.resolve();
	await tick();
	return target;
}

describe('RecipePanel', () => {
	it('shows Sound, Text, and Reproduce groups with a Preset row on top', async () => {
		const target = await render();
		const titles = Array.from(target.querySelectorAll('.group-title')).map((el) => el.textContent);
		expect(titles).toEqual(['Sound', 'Text', 'Reproduce']);
		expect(target.querySelector('.preset-row')).not.toBeNull();
	});

	it('edits the draft BPM from the Sound group', async () => {
		const target = await render();
		const bpmInput = target.querySelector<HTMLInputElement>('.recipe-group input[type="number"]');
		if (!bpmInput) throw new Error('Expected a BPM input');
		expect(bpmInput.value).toBe('108');
		bpmInput.value = '140';
		bpmInput.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();
		expect(get(editBpm)).toBe(140);
	});

	it('disables repaint mode tabs until a take is used as a source', async () => {
		const target = await render();
		const repaintButtons = Array.from(
			target.querySelectorAll<HTMLButtonElement>('.repaint-row .segmented button')
		);
		expect(repaintButtons[0].textContent).toBe('Off');
		expect(repaintButtons[0].classList.contains('active')).toBe(true);
		for (const btn of repaintButtons.slice(1)) {
			expect(btn.disabled).toBe(true);
		}

		setSourceFromGeneration(makeGeneration({ version_number: 3, generation_number: 2 }), 'repaint');
		await tick();
		const afterSource = Array.from(
			target.querySelectorAll<HTMLButtonElement>('.repaint-row .segmented button')
		);
		expect(afterSource[1].disabled).toBe(false);
		expect(target.querySelector('.source-bar')?.textContent).toContain('v3');
		expect(get(sourceGeneration)?.id).toBe('g1');
	});

	it.each(['repaint', 'cover'] as const)(
		'says that %s uses the lyrics and style currently in the editor',
		async (mode) => {
			const target = await render();
			setSourceFromGeneration(makeGeneration({ version_number: 3, generation_number: 2 }), mode);
			await tick();

			expect(target.querySelector('.source-mode-hint')?.textContent).toBe(RECIPE_SOURCE_MODE_HINT);
		}
	);

	it('calls onclose from the Collapse button', async () => {
		const target = document.createElement('div');
		document.body.append(target);
		const onclose = vi.fn();
		mounted.push(mount(RecipePanel, { target, props: { onclose } }));
		await tick();
		target.querySelector<HTMLButtonElement>('.collapse-btn')?.click();
		expect(onclose).toHaveBeenCalledTimes(1);
	});

	it('holds Manage presets for the unsaved-changes dialog while the song has a dirty draft (issue #1143)', async () => {
		setDraftLyrics('unsaved edit');
		const target = await render();

		target.querySelector<HTMLAnchorElement>('.preset-manage-link')?.click();

		expect(get(pendingDirtyNavigation)).not.toBeNull();
		expect(vi.mocked(goto)).not.toHaveBeenCalled();
	});

	it('resets the draft to the preset default when Default is selected', async () => {
		setDraftBpm(140);
		const target = await render();
		const presetSelect = target.querySelector<HTMLSelectElement>('.preset-select-label select');
		expect(presetSelect).not.toBeNull();
		expect(presetSelect?.value).toBe('');
	});
});

describe("RecipePanel at the editor's own width", () => {
	// jsdom computes no grid layout, so this pins the stylesheet; the browser
	// gate on #185 opens the panel beside a docked Now Playing.
	it('packs Sound / Text / Reproduce into as many columns as it is wide', () => {
		expect(recipePanelSource).toMatch(
			/\.recipe-groups \{[^}]*grid-template-columns: repeat\(auto-fit, minmax\(13rem, 1fr\)\);/
		);
	});

	const failingActions = [
		{
			action: 'uploading a reference track',
			fallback: 'Upload failed',
			fail: (error: Error) => vi.mocked(uploadReferenceAudio).mockRejectedValueOnce(error),
			run: (target: HTMLElement) => {
				const input = target.querySelector<HTMLInputElement>('.ref-upload input[type="file"]');
				if (!input) throw new Error('Expected the reference upload input');
				Object.defineProperty(input, 'files', { value: [new File(['audio'], 'reference.wav')] });
				input.dispatchEvent(new Event('change', { bubbles: true }));
			}
		},
		{
			action: 'saving a preset',
			fallback: 'Failed to save preset',
			fail: (error: Error) => vi.mocked(createPreset).mockRejectedValueOnce(error),
			run: async (target: HTMLElement) => {
				getByRoleButton(target, RECIPE_SAVE_AS_PRESET_LABEL).click();
				await tick();
				const name = target.querySelector<HTMLInputElement>('.preset-name-input');
				if (!name) throw new Error('Expected the preset name input');
				name.value = 'Night drive';
				name.dispatchEvent(new Event('input', { bubbles: true }));
				target.querySelector<HTMLButtonElement>('.preset-save-confirm')?.click();
			}
		}
	];

	it.each(
		failingActions.flatMap((entry) => [
			{
				...entry,
				failure: 'with no network answer',
				error: new NetworkError('/api/presets', new TypeError('Failed to fetch')),
				shown: entry.fallback
			},
			{
				...entry,
				failure: 'refused by the server',
				error: new ApiError(413, 'That file is too large', '/api/presets'),
				shown: 'That file is too large'
			}
		])
	)('says $shown once when $action fails $failure', async ({ fail, run, error, shown }) => {
		vi.mocked(addToast).mockClear();
		fail(error);
		const target = await render();
		await run(target);
		await vi.waitFor(() => expect(vi.mocked(addToast).mock.calls).toEqual([[shown, 'error']]));
	});
});
