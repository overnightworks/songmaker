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
		fetchVersions: vi.fn().mockResolvedValue([])
	};
});

vi.mock('$lib/stores/toast', () => ({ addToast: vi.fn() }));

import { editBpm, loadSongData, pinnedSeed, setDraftBpm } from '$lib/stores/editor';
import { activeModels } from '$lib/stores/presets';
import {
	clearSource,
	recipeModel,
	setSourceFromGeneration,
	sourceGeneration
} from '$lib/stores/recipe';
import type { GenerationItem, SongItem } from '$lib/api/types';
import RecipePanel from './RecipePanel.svelte';
import recipePanelSource from './RecipePanel.svelte?raw';

const mounted: Array<ReturnType<typeof mount>> = [];

function makeSong(): SongItem {
	return {
		id: 's1',
		title: 'Test',
		album_id: 'a1',
		album_title: 'Album',
		artist: 'Artist',
		track_number: 1,
		vocal_language: 'en',
		lyrics: 'hello',
		prompt: 'rock',
		bpm: 108,
		audio_duration: 195,
		key_scale: 'A',
		generation_params: null,
		version_count: 1,
		generation_count: 0,
		best_scores: null,
		best_rating: null,
		generations: [],
		created_at: '',
		is_shared: false,
		share_slug: null
	};
}

function makeGeneration(): GenerationItem {
	return {
		id: 'g1',
		song_id: 's1',
		version_id: 'v1',
		version_number: 3,
		generation_number: 2,
		mp3_path: 'g1.mp3',
		wav_path: null,
		seed: 7,
		status: 'completed',
		is_archived: false,
		is_picked: false,
		is_kept: false,
		is_shared: false,
		model_mode: 'turbo',
		whisper_text: null,
		whisper_cues: null,
		version_lyrics: null,
		scores: null,
		generation_params: null,
		audio_duration_sec: null,
		created_at: '2026-01-01T00:00:00+00:00'
	};
}

beforeEach(() => {
	loadSongData(makeSong());
	pinnedSeed.set(null);
	clearSource();
	recipeModel.set('turbo');
	activeModels.set([]);
	vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
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

		setSourceFromGeneration(makeGeneration(), 'repaint');
		await tick();
		const afterSource = Array.from(
			target.querySelectorAll<HTMLButtonElement>('.repaint-row .segmented button')
		);
		expect(afterSource[1].disabled).toBe(false);
		expect(target.querySelector('.source-bar')?.textContent).toContain('v3');
		expect(get(sourceGeneration)?.id).toBe('g1');
	});

	it('calls onclose from the Collapse button', async () => {
		const target = document.createElement('div');
		document.body.append(target);
		const onclose = vi.fn();
		mounted.push(mount(RecipePanel, { target, props: { onclose } }));
		await tick();
		target.querySelector<HTMLButtonElement>('.collapse-btn')?.click();
		expect(onclose).toHaveBeenCalledTimes(1);
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
});
