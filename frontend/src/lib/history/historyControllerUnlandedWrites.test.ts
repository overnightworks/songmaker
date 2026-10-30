import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { goto } from '$app/navigation';
import {
	attachLandingHandler,
	historyComesToRest,
	installHistoryController,
	navigateTo,
	pushEntry,
	replaceEntry,
	resetHistoryControllerForTests,
	stampNavigatedEntry,
	stepBackOffStandingEntry
} from '#lib/history/historyController.ts';
import { pageStateOfHistoryState } from '#lib/history/routerHistoryState.ts';
import { holdLayer, resetLayersForTests } from '#lib/stores/layers.ts';
import { holdShallowWrites, laterTask, startFakeRouter } from '#lib/test-utils/app-navigation.ts';
import { standingHistoryEntry, watchBack } from '#lib/test-utils/library-history.ts';

// SvelteKit 3 writes a shallow entry a few microtasks after the call. Until it
// has, the controller answers where history stands from what it wrote, and
// starts nothing that would land before it.
describe('writes the router has not landed yet', () => {
	let releaseWrites: () => Promise<void>;
	let backs: ReturnType<typeof watchBack>;

	beforeEach(async () => {
		sessionStorage.clear();
		history.replaceState(null, '', '/');
		resetHistoryControllerForTests();
		startFakeRouter();
		installHistoryController();
		attachLandingHandler(() => undefined);
		await vi.mocked(goto)('/album/a');
		stampNavigatedEntry('goto');
		vi.mocked(goto).mockClear();
		backs = watchBack();
		releaseWrites = holdShallowWrites();
	});

	afterEach(async () => {
		await releaseWrites();
		resetHistoryControllerForTests();
		resetLayersForTests();
		vi.restoreAllMocks();
	});

	const address = (pathname: string): string => `${location.origin}${pathname}`;

	async function stepBack(): Promise<void> {
		const arrived = new Promise((resolve) =>
			window.addEventListener('popstate', resolve, { once: true })
		);
		history.back();
		await arrived;
	}

	it('builds each write of one task on the one before it, and starts a move only after all landed', async () => {
		const first = pushEntry('/album/b', {});
		const second = replaceEntry('/album/b?filter=x', {});
		const third = pushEntry('/album/c', {});
		const moved = navigateTo('/settings', {
			replaceState: false,
			noScroll: true,
			keepFocus: true,
			state: {}
		});

		expect(second).toEqual(first);
		expect(third.below).toBe(address('/album/b?filter=x'));
		expect(goto).not.toHaveBeenCalled();
		void releaseWrites();
		await moved;

		expect(goto).toHaveBeenCalledOnce();
		expect(location.pathname).toBe('/settings');
		expect(standingHistoryEntry()?.below).toBe(address('/album/c'));
		backs.stop();
		await stepBack();
		expect(location.href).toBe(address('/album/c'));
		await stepBack();
		expect(location.href).toBe(address('/album/b?filter=x'));
		await stepBack();
		expect(location.pathname).toBe('/album/a');
	});

	it('stands a link push over the page a shallow push wrote', async () => {
		pushEntry('/album/b', {});
		await releaseWrites();
		await historyComesToRest();

		await vi.mocked(goto)('/settings');
		stampNavigatedEntry('goto');
		await historyComesToRest();

		expect(standingHistoryEntry()?.below).toBe(address('/album/b'));
	});

	it('keeps the library and the id of a newer write through the router start', async () => {
		const library = { index: 3, browse: 'albums' } as unknown as App.PageState['library'];
		const written = replaceEntry('/album/a', { library });

		startFakeRouter();
		stampNavigatedEntry('enter');
		await laterTask();
		expect(standingHistoryEntry()).not.toEqual(written);
		await releaseWrites();
		await historyComesToRest();

		expect(standingHistoryEntry()).toEqual(written);
		expect(pageStateOfHistoryState(history.state)?.library).toEqual(library);
	});

	it.each([
		{
			move: 'a navigation',
			start: () =>
				void navigateTo('/settings', {
					replaceState: false,
					noScroll: true,
					keepFocus: true,
					state: {}
				}),
			started: () => vi.mocked(goto).mock.calls.length
		},
		{
			move: 'a step back',
			start: () => void stepBackOffStandingEntry(),
			started: () => backs.presses()
		}
	])(
		'starts $move issued while a write is held only once it landed',
		async ({ start, started }) => {
			pushEntry('/album/b', {});

			start();
			await laterTask();

			expect(started()).toBe(0);
			await releaseWrites();
			await vi.waitFor(() => expect(started()).toBe(1));
		}
	);

	it('steps back off the entry of a layer that left before the entry landed', async () => {
		const leave = holdLayer('album-menu', () => undefined);

		leave();
		await laterTask();
		expect(backs.presses()).toBe(0);
		await releaseWrites();

		await vi.waitFor(() => expect(backs.presses()).toBe(1));
	});
});
