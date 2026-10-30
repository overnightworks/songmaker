import { makeGeneration as generation, makeSong as song } from '#lib/test-utils/factories.ts';
import { mount, tick, unmount } from 'svelte';
import { SvelteMap } from 'svelte/reactivity';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { GenerationItem, SongItem } from '#lib/api/types.ts';
import type { GenerationActions } from '#lib/contexts/generation-actions.ts';
import { TAKE_DELETE_LABEL, TAKE_DELETE_MESSAGE } from '#lib/constants.ts';
import { bulkDeleteTitle } from '#lib/constants/now-playing.ts';
import { ApiError } from '#lib/api/fetch.ts';
import { clearSelection, selectedIds, toggleSelection } from '#lib/stores/selection.ts';
import { get } from 'svelte/store';
import TakesListHarness from './tests/TakesListHarness.svelte';

vi.mock('#lib/api/client.ts', async (importOriginal) => {
	const actual = await importOriginal<typeof import('#lib/api/client.ts')>();
	return { ...actual, bulkDeleteGenerations: vi.fn() };
});
vi.mock('#lib/stores/toast.ts', () => ({ addToast: vi.fn() }));
vi.mock('#lib/stores/navigation.ts', async (importOriginal) => {
	const actual = await importOriginal<typeof import('#lib/stores/navigation.ts')>();
	return { ...actual, persistLibraryHistory: vi.fn() };
});

import { bulkDeleteGenerations } from '#lib/api/client.ts';
import { addToast } from '#lib/stores/toast.ts';

const mounted: Array<ReturnType<typeof mount>> = [];

function takes(count: number): GenerationItem[] {
	return Array.from({ length: count }, (_, index) =>
		generation({ id: `g${index + 1}`, generation_number: index + 1, version_number: 1 })
	);
}

function actions(): GenerationActions {
	return {
		pick: vi.fn(),
		keep: vi.fn(),
		del: vi.fn(),
		rate: vi.fn(),
		share: vi.fn(),
		unshare: vi.fn(),
		addToPlaylist: vi.fn(),
		useSeed: vi.fn(),
		clickVersion: vi.fn()
	} as unknown as GenerationActions;
}

// The song lives in a reactive cell so a test can play the resource event
// that removes a take while the dialog is open.
async function render(count: number) {
	const target = document.createElement('div');
	document.body.append(target);
	const cell = new SvelteMap<'song', SongItem>([['song', song({ generations: takes(count) })]]);
	mounted.push(
		mount(TakesListHarness, {
			target,
			props: {
				get song() {
					return cell.get('song') as SongItem;
				},
				dirty: false,
				draftVersionNumber: 2,
				latestVersionNumber: 1,
				onsource: vi.fn(),
				actions: actions()
			}
		})
	);
	await tick();
	const removeTakes = async (...ids: string[]) => {
		const current = cell.get('song') as SongItem;
		cell.set('song', {
			...current,
			generations: current.generations.filter((g) => !ids.includes(g.id))
		});
		await tick();
	};
	return { target, removeTakes };
}

async function tickTakes(...ids: string[]): Promise<void> {
	ids.forEach(toggleSelection);
	await tick();
}

function deleteButton(target: HTMLElement): HTMLButtonElement {
	const button = target.querySelector<HTMLButtonElement>('.selection-toolbar .destructive');
	if (!button) throw new Error('Expected the Delete N button');
	return button;
}

function dialog(): HTMLElement | null {
	return document.querySelector<HTMLElement>('[role="dialog"]');
}

async function press(label: string): Promise<void> {
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
	vi.mocked(addToast).mockClear();
	vi.stubGlobal(
		'matchMedia',
		vi.fn((query: string) => ({
			matches: false,
			media: query,
			addEventListener: vi.fn(),
			removeEventListener: vi.fn()
		}))
	);
	clearSelection();
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	vi.unstubAllGlobals();
	clearSelection();
});

describe('TakesList bulk delete asks first (S11)', () => {
	it('opens the take-delete confirmation for the ticked count and sends nothing', async () => {
		const { target } = await render(4);
		await tickTakes('g1', 'g2', 'g3');

		deleteButton(target).click();
		await tick();

		expect(dialog()?.textContent).toContain(bulkDeleteTitle(3));
		expect(dialog()?.textContent).toContain(TAKE_DELETE_MESSAGE);
		expect(dialog()?.textContent).toContain(TAKE_DELETE_LABEL);
		expect(bulkDeleteGenerations).not.toHaveBeenCalled();
	});

	it('names one take in the singular', async () => {
		const { target } = await render(2);
		await tickTakes('g1');

		deleteButton(target).click();
		await tick();

		expect(dialog()?.textContent).toContain('Delete 1 take?');
	});

	it('keeps the ticks and select mode and sends nothing on Cancel', async () => {
		const { target } = await render(4);
		await tickTakes('g1', 'g2', 'g3');
		deleteButton(target).click();
		await tick();

		await press('Cancel');

		expect(dialog()).toBeNull();
		expect([...get(selectedIds)]).toEqual(['g1', 'g2', 'g3']);
		expect(target.querySelector('.selection-toolbar')).not.toBeNull();
		expect(bulkDeleteGenerations).not.toHaveBeenCalled();
	});

	it('sends exactly the ticked takes of this song on Delete and ends select mode', async () => {
		vi.mocked(bulkDeleteGenerations).mockResolvedValueOnce(undefined as never);
		const { target } = await render(4);
		await tickTakes('g-other-song', 'g1', 'g3');
		deleteButton(target).click();
		await tick();

		await press(TAKE_DELETE_LABEL);

		expect(bulkDeleteGenerations).toHaveBeenCalledExactlyOnceWith(['g1', 'g3']);
		expect(addToast).toHaveBeenCalledWith('Deleted 2 takes', 'success');
		expect(target.querySelector('.selection-toolbar')).toBeNull();
	});

	it('follows a removed ticked take in the title and sends the takes left', async () => {
		vi.mocked(bulkDeleteGenerations).mockResolvedValueOnce(undefined as never);
		const { target, removeTakes } = await render(4);
		await tickTakes('g1', 'g2', 'g3');
		deleteButton(target).click();
		await tick();

		await removeTakes('g2');
		expect(dialog()?.textContent).toContain(bulkDeleteTitle(2));
		await press(TAKE_DELETE_LABEL);

		expect(bulkDeleteGenerations).toHaveBeenCalledExactlyOnceWith(['g1', 'g3']);
	});

	it('closes the dialog and sends nothing when no ticked take is left', async () => {
		const { target, removeTakes } = await render(4);
		await tickTakes('g1', 'g2');
		deleteButton(target).click();
		await tick();

		await removeTakes('g1', 'g2');

		expect(dialog()).toBeNull();
		expect(bulkDeleteGenerations).not.toHaveBeenCalled();
	});

	it('ends select mode when a removal left no ticked take, so no Delete is left to press', async () => {
		const { target, removeTakes } = await render(4);
		await tickTakes('g1', 'g2');

		await removeTakes('g1', 'g2');

		expect(target.querySelector('.selection-toolbar')).toBeNull();
		expect(bulkDeleteGenerations).not.toHaveBeenCalled();
	});

	it('keeps the ticks and select mode after a failed request', async () => {
		vi.mocked(bulkDeleteGenerations).mockRejectedValueOnce(
			new ApiError(500, 'boom', '/api/generations')
		);
		const { target } = await render(4);
		await tickTakes('g1', 'g2');
		deleteButton(target).click();
		await tick();

		await press(TAKE_DELETE_LABEL);

		expect(addToast).toHaveBeenCalledExactlyOnceWith(expect.any(String), 'error');
		expect([...get(selectedIds)]).toEqual(['g1', 'g2']);
		expect(target.querySelector('.selection-toolbar')).not.toBeNull();
		expect(target.querySelectorAll('.take-row')).toHaveLength(4);
	});
});
