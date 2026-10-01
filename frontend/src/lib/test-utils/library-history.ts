import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
	currentLibraryHistoryState,
	holdLibraryHistoryUntilRouterStarts,
	libraryHistoryEntry,
	libraryHistoryStepsLanded,
	loadLibraryHistoryPageForTests,
	type LibraryHistoryState
} from '$lib/stores/libraryContext';
import { followShellLayers, initNavigation, resetNavigationForTests } from '$lib/stores/navigation';
import { stampNavigatedEntry } from '$lib/history/historyController';
import { listenForGlobalEscape } from '$lib/test-utils/global-escape';
import { startFakeRouter, writeHistoryEntry } from '$lib/test-utils/app-navigation';

// The one place tests touch the browser history: they seed and read entries,
// and press Back and Forward, through these helpers, so the shape an entry is
// written in stays the business of the seam in libraryContext.ts.

export function replaceHistoryEntry(url: string, entry: unknown = null): void {
	writeHistoryEntry(entry, url, 'replace');
}

export function pushHistoryEntry(url: string, entry: unknown = null): void {
	writeHistoryEntry(entry, url, 'push');
}

// The entry history stands on, as the library reads it. Tests that expect no
// library entry at all compare it with what they seeded.
export function historyEntry(): LibraryHistoryState {
	return libraryHistoryEntry() as LibraryHistoryState;
}

export function historyLength(): number {
	return history.length;
}

// Resolves once the step has landed and the library has reacted to it.
export async function pressBack(): Promise<void> {
	await traverseHistory(() => history.back());
}

export async function pressForward(): Promise<void> {
	await traverseHistory(() => history.forward());
}

// A popstate that lands where history already stands -- what a user's Back
// from an entry above it delivers -- resolving once the library has reacted.
export async function landOnStandingEntry(): Promise<void> {
	window.dispatchEvent(new PopStateEvent('popstate', { state: history.state }));
	await tick();
}

export interface BackWatch {
	presses: () => number;
	stop: () => void;
}

// Counts the Backs the app asks the browser for while holding each step back,
// so a test sees the request without the library reacting to it.
export function watchBack(): BackWatch {
	const back = vi.spyOn(history, 'back').mockImplementation(() => undefined);
	return { presses: () => back.mock.calls.length, stop: () => back.mockRestore() };
}

async function traverseHistory(step: () => void): Promise<void> {
	const landed = new Promise((resolve) =>
		window.addEventListener('popstate', resolve, { once: true })
	);
	step();
	await landed;
	await tick();
}

// A reload onto the entry history stands on, the way the app goes through
// one: the library reads the entry while the router loads it, SvelteKit's
// start writes its own entry over it, and the app layout holds library
// history until the router reports the start -- which the returned function
// does.
export function reloadLibraryPageBeforeRouterStarts(): () => void {
	loadLibraryHistoryPageForTests();
	startFakeRouter();
	const reportStart = holdLibraryHistoryUntilRouterStarts();
	return () => {
		stampNavigatedEntry('enter');
		reportStart();
	};
}

export function reloadLibraryPage(): Promise<void> {
	reloadLibraryPageBeforeRouterStarts()();
	return libraryHistoryStepsLanded();
}

// The entry history will stand on once every queued step has landed.
export function plannedHistoryIndex(): number {
	return (currentLibraryHistoryState() as { index: number }).index;
}

// A library page with the history layer stack running, the way the app layout
// starts it -- the shell's own layers followed and Escape listened for; the
// returned function stops it.
function startLibraryHistory(): () => void {
	replaceHistoryEntry('/');
	const stopFollowingShellLayers = followShellLayers();
	const stopListening = listenForGlobalEscape();
	const stopNavigation = initNavigation();
	return () => {
		stopNavigation();
		stopListening();
		stopFollowingShellLayers();
		resetNavigationForTests();
	};
}

async function expectHistoryAt(index: number): Promise<void> {
	await vi.waitFor(() => expect(historyEntry().index).toBe(index));
	expect(location.pathname).toBe('/');
}

export interface CloseWay {
	way: string;
	close: (target: HTMLElement) => unknown;
	/** For an item that opens a dialog: the planned entry its action saw, read with plannedHistoryIndex. */
	actionSawHistoryAt?: () => number | undefined;
}

export interface OverlayUnderBack {
	name: string;
	/** Renders the page, and whatever the overlay opens over, with the overlay closed. */
	render: () => Promise<HTMLElement>;
	open: (target: HTMLElement) => void | Promise<void>;
	isShown: (target: HTMLElement) => boolean;
	closeWays: CloseWay[];
	/** What Back must leave undone, checked once it closed the overlay: a dialog it cancels never confirms. */
	afterBack?: () => void | Promise<void>;
	/** A layer the overlay opens over, which the next Back closes in turn. */
	over?: { name: string; isShown: () => boolean };
}

// The family every menu, list and sheet a component owns joins (issue #1119):
// opening it adds one entry, Back closes it and nothing below it, and each of
// its own ways to close steps back off that entry, so one Back leaves the page.
export function describeBackClosesOverlay(overlay: OverlayUnderBack): void {
	describe(`${overlay.name} under Back`, () => {
		let stopLibraryHistory: () => void;
		let below: number;

		beforeEach(() => {
			stopLibraryHistory = startLibraryHistory();
		});

		afterEach(() => stopLibraryHistory());

		async function renderOpen(): Promise<HTMLElement> {
			const target = await overlay.render();
			below = historyEntry().index;
			await overlay.open(target);
			await tick();
			expect(overlay.isShown(target)).toBe(true);
			await expectHistoryAt(below + 1);
			return target;
		}

		it('Back closes it and nothing below it', async () => {
			const target = await renderOpen();

			await pressBack();

			expect(overlay.isShown(target)).toBe(false);
			expect(overlay.over?.isShown() ?? true).toBe(true);
			await overlay.afterBack?.();
			await expectHistoryAt(below);
		});

		it('opening it again after Back closed it adds one entry again', async () => {
			const target = await renderOpen();
			await pressBack();

			await overlay.open(target);
			await tick();

			expect(overlay.isShown(target)).toBe(true);
			await expectHistoryAt(below + 1);
		});

		it.each(overlay.closeWays)('closing it by $way leaves no entry behind', async ({ close }) => {
			const target = await renderOpen();

			await close(target);
			await tick();

			expect(overlay.isShown(target)).toBe(false);
			await expectHistoryAt(below);
		});

		const handOvers = overlay.closeWays.filter((way) => way.actionSawHistoryAt !== undefined);
		if (handOvers.length > 0) {
			it.each(handOvers)(
				'$way hands over with its entry already gone',
				async ({ close, actionSawHistoryAt }) => {
					const target = await renderOpen();

					await close(target);

					await vi.waitFor(() => expect(actionSawHistoryAt?.()).toBe(below));
					await expectHistoryAt(below);
				}
			);
		}

		const { over } = overlay;
		if (over) {
			it(`the next Back closes ${over.name}`, async () => {
				await renderOpen();
				await pressBack();

				await pressBack();

				expect(over.isShown()).toBe(false);
				await expectHistoryAt(below - 1);
			});
		}
	});
}
