import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { makeGeneration, makeSong } from '$lib/test-utils/factories';
import type { GenerationItem } from '$lib/api/types';
import type { GenerationActions } from '$lib/contexts/generation-actions';
import { selectedSongId } from '$lib/stores/player';
import { clearSource, resetRecipeSourceForSong, setSourceFromGeneration } from '$lib/stores/recipe';
import TakesListHarness from './tests/TakesListHarness.svelte';

vi.mock('$lib/stores/toast', () => ({ addToast: vi.fn() }));

let list: ReturnType<typeof mount> | undefined;

function takeOn(id: string, versionNumber: number): GenerationItem {
	return makeGeneration({
		id,
		song_id: 'song-a',
		generation_number: Number(id.replace(/\D/g, '')),
		version_id: `ver-${versionNumber}`,
		version_number: versionNumber
	});
}

const takes = [takeOn('c1', 2), takeOn('c2', 2), takeOn('a1', 1)];

async function render(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	list = mount(TakesListHarness, {
		target,
		props: {
			song: makeSong({ id: 'song-a', version_count: 2, generations: takes }),
			dirty: false,
			draftVersionNumber: 3,
			latestVersionNumber: 2,
			onsource: vi.fn(),
			actions: {} as GenerationActions
		}
	});
	await tick();
	return target;
}

function cardRowIds(target: HTMLElement): (string | undefined)[] {
	return [...target.querySelectorAll('.task')].map((card) =>
		card.previousElementSibling?.id.replace('take-', '')
	);
}

beforeEach(() => {
	selectedSongId.set('song-a');
	resetRecipeSourceForSong();
});

afterEach(async () => {
	if (list) await unmount(list);
	list = undefined;
	document.body.replaceChildren();
	clearSource();
});

describe('task card in the take list', () => {
	it('renders only directly under the source take', async () => {
		setSourceFromGeneration(takes[1], 'repaint');
		const target = await render();
		expect(cardRowIds(target)).toEqual(['c2']);
	});

	it('renders no card without a source', async () => {
		const target = await render();
		expect(target.querySelector('.task')).toBeNull();
	});

	it('swaps the card for the other verb and moves it to another take', async () => {
		const target = await render();
		setSourceFromGeneration(takes[0], 'repaint');
		await tick();
		setSourceFromGeneration(takes[0], 'cover');
		await tick();
		expect(cardRowIds(target)).toEqual(['c1']);
		expect(target.querySelector('.task .what')?.textContent).toBe('Cover');
		setSourceFromGeneration(takes[1], 'cover');
		await tick();
		expect(cardRowIds(target)).toEqual(['c2']);
	});

	it('closes with the source being cleared', async () => {
		setSourceFromGeneration(takes[0], 'repaint');
		const target = await render();
		clearSource();
		await tick();
		expect(target.querySelector('.task')).toBeNull();
	});

	it('unfolds the version holding the source take', async () => {
		const target = await render();
		expect(target.querySelector('#take-a1')).toBeNull();
		setSourceFromGeneration(takes[2], 'repaint');
		await tick();
		expect(cardRowIds(target)).toEqual(['a1']);
	});

	it('names the version the take will land in', async () => {
		setSourceFromGeneration(takes[0], 'repaint');
		const target = await render();
		expect(target.querySelector('.task-foot .hint')?.textContent).toBe('New take in v2');
	});
});
