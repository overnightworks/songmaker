import { makeGeneration, makeSong } from '$lib/test-utils/factories';
import { modifiedClicks } from '$lib/test-utils/modified-clicks';
import { flushSync, mount, tick, unmount } from 'svelte';
import { SvelteMap } from 'svelte/reactivity';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import type { GenerationItem, SongItem } from '$lib/api/types';
import type { GenerationActions } from '$lib/contexts/generation-actions';
import {
	TAKE_DELETE_LABEL,
	TAKE_OVERFLOW_LABEL,
	TAKES_EMPTY,
	takesDraftBanner
} from '$lib/constants';
import {
	EARLIER_VERSIONS_LABEL,
	bulkDeleteTitle,
	currentVersionHeadLabel,
	foldedGroupLabel,
	openVersionLabel,
	selectedCountLabel
} from '$lib/constants/now-playing';
import { selectedSongId } from '$lib/stores/player';
import { clearSelection, selectedIds, selectionMode, toggleSelection } from '$lib/stores/selection';
import { toggleTakeGroup, groupTakes } from '$lib/stores/takeFolds';
import TakesListHarness from './tests/TakesListHarness.svelte';

vi.mock('$lib/api/client', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/api/client')>();
	return { ...actual, bulkDeleteGenerations: vi.fn() };
});
vi.mock('$lib/stores/toast', () => ({ addToast: vi.fn() }));
vi.mock('$lib/stores/navigation', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/stores/navigation')>();
	return { ...actual, persistLibraryHistory: vi.fn(), jumpToTake: vi.fn() };
});

import { bulkDeleteGenerations } from '$lib/api/client';
import { jumpToTake } from '$lib/stores/navigation';

const mounted: Array<ReturnType<typeof mount>> = [];
let songCounter = 0;

function takeOn(
	id: string,
	versionNumber: number | null,
	overrides: Partial<GenerationItem> = {}
): GenerationItem {
	return makeGeneration({
		id,
		generation_number: Number(id.replace(/\D/g, '')),
		version_id: versionNumber === null ? null : `ver-${versionNumber}`,
		version_number: versionNumber,
		...overrides
	});
}

// v3 current (c1, c2 picked), v2 (a1, a2 kept, a3 archived), v1 (o1 archived).
function storytime(): GenerationItem[] {
	return [
		takeOn('c1', 3),
		takeOn('c2', 3, { is_picked: true }),
		takeOn('a1', 2),
		takeOn('a2', 2, { is_kept: true }),
		takeOn('a3', 2, { is_archived: true }),
		takeOn('o1', 1, { is_archived: true })
	];
}

function generationActionMocks(): GenerationActions {
	return {
		pick: vi.fn(),
		keep: vi.fn(),
		del: vi.fn(),
		rate: vi.fn(),
		share: vi.fn(),
		unshare: vi.fn(),
		addToPlaylist: vi.fn(),
		pinSeed: vi.fn(),
		clickVersion: vi.fn()
	} as unknown as GenerationActions;
}

interface RenderOptions {
	generations?: GenerationItem[];
	latestVersionNumber?: number;
	versionCount?: number;
	dirty?: boolean;
	draftVersionNumber?: number;
	loadStatus?: 'loading' | 'ready' | 'error';
}

// The song lives in a reactive cell so a test can play a Save's response or a
// resync that replaces the takes under the mounted list.
async function render(options: RenderOptions = {}) {
	const target = document.createElement('div');
	document.body.append(target);
	const generationActions = generationActionMocks();
	const cell = new SvelteMap<'song', SongItem>([
		[
			'song',
			makeSong({
				id: 'song-a',
				version_count: options.versionCount ?? 3,
				generations: options.generations ?? storytime()
			})
		]
	]);
	const latest = new SvelteMap<'number', number>([['number', options.latestVersionNumber ?? 3]]);
	const component = mount(TakesListHarness, {
		target,
		props: {
			get song() {
				return cell.get('song') as SongItem;
			},
			loadStatus: options.loadStatus ?? 'ready',
			dirty: options.dirty ?? false,
			draftVersionNumber: options.draftVersionNumber ?? 4,
			get latestVersionNumber() {
				return latest.get('number') as number;
			},
			onsource: vi.fn(),
			actions: generationActions
		}
	});
	mounted.push(component);
	await tick();
	const replaceTakes = async (generations: GenerationItem[]) => {
		cell.set('song', { ...(cell.get('song') as SongItem), generations });
		await tick();
	};
	const saveNewVersion = async (versionNumber: number) => {
		cell.set('song', { ...(cell.get('song') as SongItem), version_count: versionNumber });
		latest.set('number', versionNumber);
		await tick();
	};
	return { target, generationActions, replaceTakes, saveNewVersion, component };
}

function rowIds(target: HTMLElement): string[] {
	return [...target.querySelectorAll('.take-row')].map((row) => row.id.replace('take-', ''));
}

function foldToggle(target: HTMLElement, label: string): HTMLButtonElement {
	const toggle = [...target.querySelectorAll<HTMLButtonElement>('button[aria-expanded]')].find(
		(button) => button.textContent?.includes(label)
	);
	if (!toggle) throw new Error(`Expected a fold row "${label}"`);
	return toggle;
}

const V2_ROW = foldedGroupLabel(2, 3, 1);
const V1_ROW = foldedGroupLabel(1, 1, 1);

async function clickThenTick(element: HTMLElement): Promise<void> {
	element.click();
	await tick();
}

async function ctrlTickTakes(...ids: string[]): Promise<void> {
	ids.forEach(toggleSelection);
	await tick();
}

function toolbarCount(target: HTMLElement): string | null {
	return target.querySelector('.toolbar-count')?.textContent ?? null;
}

function confirmDialog(): HTMLElement | null {
	return document.querySelector<HTMLElement>('[role="dialog"]');
}

async function pressInDialog(label: string): Promise<void> {
	const button = [...document.querySelectorAll<HTMLButtonElement>('[role="dialog"] button')].find(
		(candidate) => candidate.textContent?.trim() === label
	);
	if (!button) throw new Error(`Expected a ${label} button in the dialog`);
	button.click();
	await tick();
	await Promise.resolve();
	await tick();
}

beforeEach(() => {
	vi.mocked(bulkDeleteGenerations).mockReset();
	vi.mocked(jumpToTake).mockReset();
	vi.stubGlobal(
		'matchMedia',
		vi.fn((query: string) => ({
			matches: false,
			media: query,
			addEventListener: vi.fn(),
			removeEventListener: vi.fn()
		}))
	);
	songCounter += 1;
	selectedSongId.set(`song-${songCounter}`);
	clearSelection();
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	vi.unstubAllGlobals();
	clearSelection();
});

describe('TakesList folds the earlier versions (S3)', () => {
	it('opens the current version and folds every earlier one without a single take row', async () => {
		const { target } = await render();

		expect(target.querySelector('.version-head')?.textContent).toContain(
			currentVersionHeadLabel(3, 2)
		);
		expect(target.textContent).toContain(EARLIER_VERSIONS_LABEL);
		expect(foldToggle(target, V2_ROW).getAttribute('aria-expanded')).toBe('false');
		expect(foldToggle(target, V1_ROW).getAttribute('aria-expanded')).toBe('false');
		expect(rowIds(target)).toEqual(['c1', 'c2']);
	});

	it('shows the album pick on the folded row and gives way to the Open link when unfolded', async () => {
		const generations = [...storytime(), takeOn('a4', 2, { is_picked: true })];
		const { target, generationActions } = await render({ generations });

		expect(foldToggle(target, foldedGroupLabel(2, 4, 1)).textContent).toContain('Take 4');
		await clickThenTick(foldToggle(target, foldedGroupLabel(2, 4, 1)));

		const toggle = foldToggle(target, foldedGroupLabel(2, 4, 1));
		expect(toggle.textContent).not.toContain('Take 4');
		const open = [...target.querySelectorAll<HTMLButtonElement>('button')].find((button) =>
			button.textContent?.includes(openVersionLabel(2))
		);
		expect(open?.closest('[aria-expanded]')).toBeNull();
		await clickThenTick(open as HTMLElement);
		expect(generationActions.clickVersion).toHaveBeenCalledExactlyOnceWith('ver-2');
	});

	it('unfolds in place, keeps the toggle focused and folds again on a second press', async () => {
		const { target } = await render();
		const toggle = foldToggle(target, V2_ROW);
		toggle.focus();

		await clickThenTick(toggle);
		expect(toggle.getAttribute('aria-expanded')).toBe('true');
		expect(rowIds(target)).toEqual(['c1', 'c2', 'a1', 'a2', 'a3']);
		expect(document.activeElement).toBe(toggle);

		await clickThenTick(toggle);
		expect(toggle.getAttribute('aria-expanded')).toBe('false');
		expect(rowIds(target)).toEqual(['c1', 'c2']);
		expect(document.activeElement).toBe(toggle);
	});

	it('shows an archived take as a compact row with no play, pick, keep, score or origin', async () => {
		const generations = [
			takeOn('c1', 3),
			takeOn('a3', 2, {
				is_archived: true,
				audio_duration_sec: 61,
				scores: { bpm_accuracy: 0.9 } as GenerationItem['scores'],
				generation_params: { task_type: 'repaint', user_lora_id: 'l1' }
			})
		];
		const { target } = await render({ generations });
		await clickThenTick(foldToggle(target, foldedGroupLabel(2, 1, 1)));

		const row = target.querySelector<HTMLElement>('#take-a3');
		expect(row?.textContent).toContain('archived');
		expect(row?.textContent).toContain('1:01');
		expect(row?.querySelector('.play-btn, .pick-btn, .keep-btn, .score-badge')).toBeNull();
		expect(row?.querySelector('.take-origin, .take-voice')).toBeNull();
		expect(row?.querySelector('[aria-label="' + TAKE_OVERFLOW_LABEL + '"]')).not.toBeNull();
	});

	it('shows the empty current version with its head, the empty text and the folded rows', async () => {
		const generations = [takeOn('a1', 2)];
		const { target } = await render({ generations, latestVersionNumber: 3 });

		expect(target.querySelector('.version-head')?.textContent).toContain(
			currentVersionHeadLabel(3, 0)
		);
		expect(target.querySelector('.version-head')?.textContent).not.toContain('Open v');
		expect(target.textContent).toContain(TAKES_EMPTY);
		expect(foldToggle(target, foldedGroupLabel(2, 1, 0))).toBeTruthy();
	});

	it('keeps the draft banner above the head, with the empty text, for a dirty empty current version', async () => {
		const { target } = await render({
			generations: [takeOn('a1', 2)],
			dirty: true,
			draftVersionNumber: 3
		});

		expect(target.querySelector('.draft-banner')?.textContent?.trim()).toBe(takesDraftBanner(3, 3));
		expect(target.textContent).toContain(TAKES_EMPTY);
	});

	it('shows no head, no Open link and no Earlier versions label for a song with no saved version', async () => {
		const { target } = await render({
			generations: [],
			versionCount: 0,
			latestVersionNumber: 0,
			dirty: true,
			draftVersionNumber: 1
		});

		expect(target.querySelector('.draft-banner')?.textContent?.trim()).toBe(
			'Draft — unsaved changes. Generate creates v1.'
		);
		expect(target.querySelector('.version-head')).toBeNull();
		expect(target.textContent).not.toContain(EARLIER_VERSIONS_LABEL);
		expect(target.textContent).not.toContain('Open v');
	});
});

describe('Imported (Q1 a)', () => {
	const importedOnly = () => [takeOn('i1', null), takeOn('i2', null)];

	it('starts unfolded when no version of the song holds a take, and stays folded once folded by hand', async () => {
		const { target, component } = await render({ generations: importedOnly() });
		expect(rowIds(target)).toEqual(['i1', 'i2']);

		await clickThenTick(foldToggle(target, foldedGroupLabel(null, 2, 0)));
		expect(rowIds(target)).toEqual([]);

		await unmount(component);
		mounted.pop();
		const again = await render({ generations: importedOnly() });
		expect(rowIds(again.target)).toEqual([]);
	});

	it('folds like an earlier version, last, with no Open link, once a version holds a take', async () => {
		const { target } = await render({ generations: [...storytime(), ...importedOnly()] });

		const labels = [...target.querySelectorAll('button[aria-expanded]')].map((b) =>
			b.textContent?.trim()
		);
		expect(labels.at(-1)).toContain(foldedGroupLabel(null, 2, 0));
		expect(rowIds(target)).toEqual(['c1', 'c2']);
		await clickThenTick(foldToggle(target, foldedGroupLabel(null, 2, 0)));
		expect(rowIds(target)).toEqual(['c1', 'c2', 'i1', 'i2']);
		expect(
			foldToggle(target, foldedGroupLabel(null, 2, 0))
				.closest('.version-section')
				?.querySelector('.version-link')
		).toBeNull();
	});

	it('does not fold on its own when a generated take arrives later', async () => {
		const { target, replaceTakes } = await render({ generations: importedOnly() });

		await replaceTakes([...importedOnly(), takeOn('c1', 3)]);

		expect(rowIds(target)).toEqual(['c1', 'i1', 'i2']);
	});
});

describe('the selection stays within the rendered takes (rules 6 and 7, cells 16-18/21-24/26/27)', () => {
	it('never counts a ticked take of a folded version', async () => {
		const { target } = await render();

		toggleSelection('c1');
		toggleSelection('a1');
		await tick();

		expect(toolbarCount(target)).toBe(selectedCountLabel(1));
		expect([...get(selectedIds)]).toEqual(['c1']);
	});

	it('clears the ticks inside a version when it folds and shows them unticked on unfolding', async () => {
		const { target } = await render();
		await clickThenTick(foldToggle(target, V2_ROW));
		await ctrlTickTakes('a1');
		await ctrlTickTakes('a2');
		await ctrlTickTakes('c1');
		expect(toolbarCount(target)).toBe(selectedCountLabel(3));

		await clickThenTick(foldToggle(target, V2_ROW));
		expect(toolbarCount(target)).toBe(selectedCountLabel(1));
		await clickThenTick(foldToggle(target, V2_ROW));

		expect([...get(selectedIds)]).toEqual(['c1']);
		expect(target.querySelector('#take-a1.selected')).toBeNull();
	});

	it('ends select mode when folding clears the last tick', async () => {
		const { target } = await render();
		await clickThenTick(foldToggle(target, V2_ROW));
		await ctrlTickTakes('a1');

		await clickThenTick(foldToggle(target, V2_ROW));

		expect(get(selectionMode)).toBe(false);
		expect(target.querySelector('.selection-toolbar')).toBeNull();
	});

	it('selects all unkept among the rendered takes, archived ones included, never a folded version', async () => {
		const { target } = await render();
		await clickThenTick(foldToggle(target, V2_ROW));
		await ctrlTickTakes('c1');

		const selectAll = target.querySelector<HTMLButtonElement>('.select-all');
		await clickThenTick(selectAll as HTMLElement);

		expect([...get(selectedIds)].sort()).toEqual(['a1', 'a3', 'c1']);
	});

	it('prunes a dormant selection to the rendered takes when the list mounts again', async () => {
		const { component } = await render();
		await unmount(component);
		mounted.pop();
		toggleSelection('c1');
		toggleSelection('a1');

		const again = await render();

		expect([...get(selectedIds)]).toEqual(['c1']);
		expect(toolbarCount(again.target)).toBe(selectedCountLabel(1));
	});

	it('clears the ticks of a folded version in the same way while the takes are still loading', async () => {
		const { target } = await render({ loadStatus: 'loading' });
		await clickThenTick(foldToggle(target, V2_ROW));
		await ctrlTickTakes('c1');
		await ctrlTickTakes('a1');

		await clickThenTick(foldToggle(target, V2_ROW));
		await clickThenTick(foldToggle(target, V2_ROW));

		expect([...get(selectedIds)]).toEqual(['c1']);
		expect(target.querySelector('#take-a1.selected')).toBeNull();
	});

	it('drops a ticked take that a reload of the song no longer holds', async () => {
		const { target, replaceTakes } = await render();
		await ctrlTickTakes('c1');
		await ctrlTickTakes('c2');

		await replaceTakes(storytime().filter((gen) => gen.id !== 'c1'));

		expect(toolbarCount(target)).toBe(selectedCountLabel(1));
	});

	it('clears the ticks of the old current version when a new version folds it', async () => {
		const { target, saveNewVersion } = await render();
		await ctrlTickTakes('c1');

		await saveNewVersion(4);

		expect(foldToggle(target, foldedGroupLabel(3, 2, 0)).getAttribute('aria-expanded')).toBe(
			'false'
		);
		expect(get(selectionMode)).toBe(false);
		expect(rowIds(target)).toEqual([]);
	});
});

describe('Delete sends rendered takes only, checked at confirm time (rule 8, cells 30/31/33-35)', () => {
	it('sends only the rendered ticked takes when a version folds under an open dialog', async () => {
		vi.mocked(bulkDeleteGenerations).mockResolvedValueOnce(undefined as never);
		const { target } = await render();
		await clickThenTick(foldToggle(target, V2_ROW));
		await ctrlTickTakes('a1');
		await ctrlTickTakes('c1');
		await clickThenTick(target.querySelector('.selection-toolbar .destructive') as HTMLElement);
		expect(confirmDialog()?.textContent).toContain(bulkDeleteTitle(2));

		toggleTakeGroup('v2', groupTakes(storytime(), 3));
		await tick();
		expect(confirmDialog()?.textContent).toContain(bulkDeleteTitle(1));
		await pressInDialog(TAKE_DELETE_LABEL);

		expect(bulkDeleteGenerations).toHaveBeenCalledExactlyOnceWith(['c1']);
	});

	it('closes the dialog and sends nothing when folding left nothing ticked', async () => {
		const { target } = await render();
		await clickThenTick(foldToggle(target, V2_ROW));
		await ctrlTickTakes('a1');
		await clickThenTick(target.querySelector('.selection-toolbar .destructive') as HTMLElement);

		await clickThenTick(foldToggle(target, V2_ROW));

		expect(confirmDialog()).toBeNull();
		expect(bulkDeleteGenerations).not.toHaveBeenCalled();
	});

	it('sends nothing and ends select mode when the fold lands in the instant of the confirm', async () => {
		const { target } = await render();
		await clickThenTick(foldToggle(target, V2_ROW));
		await ctrlTickTakes('a1');
		await clickThenTick(target.querySelector('.selection-toolbar .destructive') as HTMLElement);

		toggleTakeGroup('v2', groupTakes(storytime(), 3));
		const confirm = [
			...document.querySelectorAll<HTMLButtonElement>('[role="dialog"] button')
		].find((button) => button.textContent?.trim() === TAKE_DELETE_LABEL);
		confirm?.click();
		await tick();

		expect(bulkDeleteGenerations).not.toHaveBeenCalled();
		expect(confirmDialog()).toBeNull();
		expect(get(selectionMode)).toBe(false);
	});

	async function askToDelete(target: HTMLElement, id: string): Promise<void> {
		const trigger = target.querySelector<HTMLButtonElement>(
			`#take-${id} [aria-label="${TAKE_OVERFLOW_LABEL}"]`
		);
		await clickThenTick(trigger as HTMLElement);
		const item = [...document.querySelectorAll<HTMLButtonElement>('button')].find(
			(button) => button.textContent?.trim() === TAKE_DELETE_LABEL
		);
		await clickThenTick(item as HTMLElement);
	}

	it('sends a single take that is rendered', async () => {
		const { target, generationActions } = await render();

		await askToDelete(target, 'c1');
		await pressInDialog(TAKE_DELETE_LABEL);

		expect(generationActions.del).toHaveBeenCalledExactlyOnceWith('c1');
	});

	it('sends nothing and closes the dialog when the single take folded away under it', async () => {
		const { target, generationActions } = await render();
		await clickThenTick(foldToggle(target, V2_ROW));
		await askToDelete(target, 'a1');

		toggleTakeGroup('v2', groupTakes(storytime(), 3));
		flushSync();
		await pressInDialog(TAKE_DELETE_LABEL);

		expect(generationActions.del).not.toHaveBeenCalled();
		expect(confirmDialog()).toBeNull();
	});

	it('sends nothing when the single take left the loaded takes under the dialog', async () => {
		const { target, generationActions, replaceTakes } = await render();
		await askToDelete(target, 'c1');

		await replaceTakes(storytime().filter((gen) => gen.id !== 'c1'));
		await pressInDialog(TAKE_DELETE_LABEL);

		expect(generationActions.del).not.toHaveBeenCalled();
		expect(confirmDialog()).toBeNull();
	});
});

describe('folds belong to the song they were made on (rule 12, cells 36/39)', () => {
	it('keeps the open versions while no take list is mounted and no other song is shown', async () => {
		selectedSongId.set('song-a');
		const { target, component } = await render();
		await clickThenTick(foldToggle(target, V2_ROW));
		await unmount(component);
		mounted.pop();

		selectedSongId.set(null);
		selectedSongId.set('song-a');
		const again = await render();

		expect(foldToggle(again.target, V2_ROW).getAttribute('aria-expanded')).toBe('true');
	});

	it('folds everything again on returning to the song after another song was shown', async () => {
		selectedSongId.set('song-a');
		const { target, component } = await render();
		await clickThenTick(foldToggle(target, V2_ROW));
		await unmount(component);
		mounted.pop();

		selectedSongId.set('song-b');
		selectedSongId.set('song-a');
		const again = await render();

		expect(foldToggle(again.target, V2_ROW).getAttribute('aria-expanded')).toBe('false');
	});
});

describe('a link to a take inside a folded version (rule 10, cells 43/44)', () => {
	function repaintOf(sourceId: string): GenerationItem {
		return takeOn('c1', 3, {
			generation_params: { task_type: 'repaint' },
			src_generation_id: sourceId,
			src_generation_number: 1,
			src_generation_version_number: 2
		});
	}

	const scrollIntoView = vi.fn(function (this: Element) {
		return this.id;
	});

	beforeEach(() => {
		scrollIntoView.mockClear();
		Element.prototype.scrollIntoView = scrollIntoView;
	});

	it('unfolds that version and hands the take to the navigation owner on a plain click', async () => {
		const generations = [repaintOf('a1'), ...storytime().slice(1)];
		const { target } = await render({ generations });
		const link = target.querySelector<HTMLAnchorElement>('#take-c1 .take-origin a');
		const click = new MouseEvent('click', { bubbles: true, cancelable: true });

		link?.dispatchEvent(click);

		expect(click.defaultPrevented).toBe(true);
		expect(target.querySelector('#take-a1')).not.toBeNull();
		expect(foldToggle(target, V2_ROW).getAttribute('aria-expanded')).toBe('true');
		expect(jumpToTake).toHaveBeenCalledWith('a1');
		expect(scrollIntoView.mock.results.map((result) => result.value)).toEqual(['take-a1']);
	});

	it.each(modifiedClicks)(
		'leaves the click to the browser, unfolds nothing and writes nothing for %o',
		async (modifier) => {
			const generations = [repaintOf('a1'), ...storytime().slice(1)];
			const { target } = await render({ generations });
			const link = target.querySelector<HTMLAnchorElement>('#take-c1 .take-origin a');
			const click = new MouseEvent('click', { bubbles: true, cancelable: true, ...modifier });

			link?.dispatchEvent(click);

			expect(click.defaultPrevented).toBe(false);
			expect(target.querySelector('#take-a1')).toBeNull();
			expect(jumpToTake).not.toHaveBeenCalled();
		}
	);

	it('toggles the tick instead in select mode and leaves the version folded', async () => {
		const generations = [repaintOf('a1'), ...storytime().slice(1)];
		const { target } = await render({ generations });
		toggleSelection('c2');
		await tick();

		await clickThenTick(
			target.querySelector<HTMLButtonElement>('#take-c1 button.take-origin') as HTMLElement
		);

		expect(get(selectedIds).has('c1')).toBe(true);
		expect(target.querySelector('#take-a1')).toBeNull();
		expect(jumpToTake).not.toHaveBeenCalled();
	});
});
