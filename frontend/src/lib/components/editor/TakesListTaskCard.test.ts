import { mount, tick, unmount } from 'svelte';
import { SvelteMap } from 'svelte/reactivity';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { makeGeneration, makeSong } from '$lib/test-utils/factories';
import type { GenerationItem, SongItem } from '$lib/api/types';
import type { GenerationActions } from '$lib/contexts/generation-actions';
import { selectedSongId } from '$lib/stores/player';
import { clearSource, resetRecipeSourceForSong, setSourceFromGeneration } from '$lib/stores/recipe';
import TakesListHarness from './tests/TakesListHarness.svelte';

vi.mock('$lib/stores/toast', () => ({ addToast: vi.fn() }));

let list: ReturnType<typeof mount> | undefined;

function takeInVersion(id: string, versionNumber: number): GenerationItem {
	return makeGeneration({
		id,
		song_id: 'song-a',
		generation_number: Number(id.replace(/\D/g, '')),
		version_id: `ver-${versionNumber}`,
		version_number: versionNumber
	});
}

const takes = [takeInVersion('c1', 2), takeInVersion('c2', 2), takeInVersion('a1', 1)];

// The song and the newest version live in reactive cells so a test can play a save.
const saved = new SvelteMap<'song' | 'latest', SongItem | number>();

async function renderList(): Promise<HTMLElement> {
	saved.set('song', makeSong({ id: 'song-a', version_count: 2, generations: takes }));
	saved.set('latest', 2);
	const target = document.createElement('div');
	document.body.append(target);
	list = mount(TakesListHarness, {
		target,
		props: {
			get song() {
				return saved.get('song') as SongItem;
			},
			dirty: false,
			draftVersionNumber: 3,
			get latestVersionNumber() {
				return saved.get('latest') as number;
			},
			onsource: vi.fn(),
			actions: {} as GenerationActions
		}
	});
	await tick();
	return target;
}

function rowIdsWithCard(target: HTMLElement): (string | undefined)[] {
	return [...target.querySelectorAll('.task')].map((card) =>
		card.previousElementSibling?.id.replace('take-', '')
	);
}

beforeEach(() => {
	Element.prototype.scrollIntoView = vi.fn();
	selectedSongId.set('song-a');
	resetRecipeSourceForSong();
});

afterEach(async () => {
	if (list) await unmount(list);
	list = undefined;
	document.body.replaceChildren();
	clearSource();
});

describe('task card in the take list (S4, #1912 acceptance 1, 2, 5, 6, 7)', () => {
	it('renders only directly under the source take', async () => {
		setSourceFromGeneration(takes[1], 'repaint');
		const target = await renderList();
		expect(rowIdsWithCard(target)).toEqual(['c2']);
	});

	it('renders no card without a source', async () => {
		const target = await renderList();
		expect(target.querySelector('.task')).toBeNull();
	});

	it('swaps the card for the other verb and moves it to another take', async () => {
		const target = await renderList();
		setSourceFromGeneration(takes[0], 'repaint');
		await tick();
		setSourceFromGeneration(takes[0], 'cover');
		await tick();
		expect(rowIdsWithCard(target)).toEqual(['c1']);
		expect(target.querySelector('.task .what')?.textContent).toBe('Cover');
		setSourceFromGeneration(takes[1], 'cover');
		await tick();
		expect(rowIdsWithCard(target)).toEqual(['c2']);
	});

	it('closes with the source being cleared', async () => {
		setSourceFromGeneration(takes[0], 'repaint');
		const target = await renderList();
		clearSource();
		await tick();
		expect(target.querySelector('.task')).toBeNull();
	});

	it('unfolds the version holding the source take', async () => {
		const target = await renderList();
		expect(target.querySelector('#take-a1')).toBeNull();
		setSourceFromGeneration(takes[2], 'repaint');
		await tick();
		expect(rowIdsWithCard(target)).toEqual(['a1']);
	});

	it('keeps the card open when saving a draft makes the source take an earlier version', async () => {
		const target = await renderList();
		setSourceFromGeneration(takes[0], 'repaint');
		await tick();
		expect(rowIdsWithCard(target)).toEqual(['c1']);
		saved.set('song', makeSong({ id: 'song-a', version_count: 3, generations: takes }));
		saved.set('latest', 3);
		await tick();
		expect(rowIdsWithCard(target)).toEqual(['c1']);
	});

	it('names the version the take will land in', async () => {
		setSourceFromGeneration(takes[0], 'repaint');
		const target = await renderList();
		expect(target.querySelector('.task-foot .hint')?.textContent).toBe('New take in v2');
	});
});
