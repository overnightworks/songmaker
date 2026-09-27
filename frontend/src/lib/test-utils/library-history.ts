import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { currentLibraryHistoryState } from '$lib/stores/libraryContext';
import { initNavigation, resetNavigationForTests } from '$lib/stores/navigation';

// A library page with the history layer stack running, the way the app layout
// starts it; returns the page's own entry index.
function startLibraryHistory(): { below: number; stop: () => void } {
	history.replaceState(null, '', '/');
	const stopNavigation = initNavigation();
	return {
		below: history.state.index,
		stop: () => {
			stopNavigation();
			resetNavigationForTests();
		}
	};
}

async function pressBack(): Promise<void> {
	const landed = new Promise((resolve) =>
		window.addEventListener('popstate', resolve, { once: true })
	);
	history.back();
	await landed;
	await tick();
}

async function expectHistoryAt(index: number): Promise<void> {
	await vi.waitFor(() => expect(history.state.index).toBe(index));
	expect(location.pathname).toBe('/');
}

// The entry history will stand on once every queued step has landed.
export function plannedHistoryIndex(): number {
	return (currentLibraryHistoryState() as { index: number }).index;
}

export interface CloseWay {
	way: string;
	close: (target: HTMLElement) => void | Promise<void>;
	/** For an item that opens a dialog: the planned entry its action saw, read with plannedHistoryIndex. */
	actionSawHistoryAt?: () => number | undefined;
}

export interface OverlayUnderBack {
	name: string;
	render: () => Promise<HTMLElement>;
	open: (target: HTMLElement) => void | Promise<void>;
	isShown: (target: HTMLElement) => boolean;
	closeWays: CloseWay[];
}

// The family every menu, list and sheet a component owns joins (issue #1119):
// opening it adds one entry, Back closes it and nothing below it, and each of
// its own ways to close steps back off that entry, so one Back leaves the page.
export function describeBackClosesOverlay(overlay: OverlayUnderBack): void {
	describe(`${overlay.name} under Back`, () => {
		let libraryHistory: { below: number; stop: () => void };

		beforeEach(() => {
			libraryHistory = startLibraryHistory();
		});

		afterEach(() => libraryHistory.stop());

		async function renderOpen(): Promise<HTMLElement> {
			const target = await overlay.render();
			await overlay.open(target);
			await tick();
			expect(overlay.isShown(target)).toBe(true);
			await expectHistoryAt(libraryHistory.below + 1);
			return target;
		}

		it('Back closes it and nothing below it', async () => {
			const target = await renderOpen();

			await pressBack();

			expect(overlay.isShown(target)).toBe(false);
			await expectHistoryAt(libraryHistory.below);
		});

		it('opening it again after Back closed it adds one entry again', async () => {
			const target = await renderOpen();
			await pressBack();

			await overlay.open(target);
			await tick();

			expect(overlay.isShown(target)).toBe(true);
			await expectHistoryAt(libraryHistory.below + 1);
		});

		it.each(overlay.closeWays)('closing it by $way leaves no entry behind', async ({ close }) => {
			const target = await renderOpen();

			await close(target);
			await tick();

			expect(overlay.isShown(target)).toBe(false);
			await expectHistoryAt(libraryHistory.below);
		});

		const handOvers = overlay.closeWays.filter((way) => way.actionSawHistoryAt !== undefined);
		if (handOvers.length > 0) {
			it.each(handOvers)(
				'$way hands over with its entry already gone',
				async ({ close, actionSawHistoryAt }) => {
					const target = await renderOpen();

					await close(target);

					expect(actionSawHistoryAt?.()).toBe(libraryHistory.below);
				}
			);
		}
	});
}
