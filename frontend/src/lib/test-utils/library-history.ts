import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { currentLibraryHistoryState } from '$lib/stores/libraryContext';
import { initNavigation, resetNavigationForTests } from '$lib/stores/navigation';

// A library page with the history layer stack running, the way the app layout
// starts it; the returned function stops it.
function startLibraryHistory(): () => void {
	history.replaceState(null, '', '/');
	const stopNavigation = initNavigation();
	return () => {
		stopNavigation();
		resetNavigationForTests();
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
	/** Renders the page, and whatever the overlay opens over, with the overlay closed. */
	render: () => Promise<HTMLElement>;
	open: (target: HTMLElement) => void | Promise<void>;
	isShown: (target: HTMLElement) => boolean;
	closeWays: CloseWay[];
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
			below = history.state.index;
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

					expect(actionSawHistoryAt?.()).toBe(below);
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
