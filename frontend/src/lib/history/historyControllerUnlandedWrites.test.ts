import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$app/state', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppState()
);

import { goto, pushState, replaceState } from '$app/navigation';
import {
	attachLandingHandler,
	historyComesToRest,
	installHistoryController,
	loadHistoryPageForTests,
	mountAddressOver,
	navigateTo,
	pushEntry,
	replaceEntry,
	resetHistoryControllerForTests,
	stampNavigatedEntry,
	stepBackOffStandingEntry
} from '#lib/history/historyController.ts';
import { pageStateOfHistoryState } from '#lib/history/routerHistoryState.ts';
import {
	closeTopLayer,
	holdLayer,
	resetLayersForTests,
	stackedLayers
} from '#lib/stores/layers.ts';
import {
	fakePage,
	holdShallowWrites,
	laterTask,
	renderNoRouteAddresses,
	reportedNavigations,
	startFakeRouter
} from '#lib/test-utils/app-navigation.ts';
import {
	pressBack,
	pressForward,
	pushHistoryEntry,
	standingHistoryEntry,
	watchBack
} from '#lib/test-utils/library-history.ts';

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
			replace: false,
			reset: false,
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
					replace: false,
					reset: false,
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

describe('a rejected shallow write', () => {
	beforeEach(async () => {
		sessionStorage.clear();
		history.replaceState(null, '', '/');
		resetHistoryControllerForTests();
		startFakeRouter();
		installHistoryController();
		attachLandingHandler(() => undefined);
		await vi.mocked(goto)('/album/a');
		stampNavigatedEntry('goto');
	});

	afterEach(() => {
		resetHistoryControllerForTests();
		vi.restoreAllMocks();
	});

	it('leaves the next move to build on the history that stands, not on the write that failed', async () => {
		renderNoRouteAddresses('/gone');
		pushEntry('/gone', {});
		await historyComesToRest();

		const next = pushEntry('/album/b', {});
		await historyComesToRest();

		expect(next.below).toBe(`${location.origin}/album/a`);
		expect(location.pathname).toBe('/album/b');
	});
});

describe('an address no route matches', () => {
	const NOT_FOUND = '/nonsense';
	const close = vi.fn();

	beforeEach(async () => {
		sessionStorage.clear();
		history.replaceState(null, '', '/');
		resetHistoryControllerForTests();
		startFakeRouter();
		installHistoryController();
		attachLandingHandler(() => undefined);
		await vi.mocked(goto)('/album/a');
		stampNavigatedEntry('goto');
		await historyComesToRest();
		pushHistoryEntry(NOT_FOUND);
		startFakeRouter();
		renderNoRouteAddresses(NOT_FOUND);
		loadHistoryPageForTests();
		stampNavigatedEntry('enter');
		await laterTask();
		vi.mocked(goto).mockClear();
		vi.mocked(pushState).mockClear();
		vi.mocked(replaceState).mockClear();
		close.mockClear();
	});

	afterEach(() => {
		resetHistoryControllerForTests();
		resetLayersForTests();
		vi.restoreAllMocks();
	});

	it('is started without a write the router would refuse', async () => {
		const entries = history.length;

		stampNavigatedEntry('enter');
		await laterTask();

		expect(replaceState).not.toHaveBeenCalled();
		expect(history).toHaveLength(entries);
	});

	it('opens a layer with no entry of its own and no remount, and Escape closes it', async () => {
		const entries = history.length;
		const backs = watchBack();

		holdLayer('account-menu', close);
		await laterTask();
		expect(pushState).not.toHaveBeenCalled();
		expect(goto).not.toHaveBeenCalled();
		expect(history).toHaveLength(entries);

		expect(closeTopLayer()).toBe(true);
		await laterTask();
		expect(close).toHaveBeenCalledOnce();
		expect(backs.presses()).toBe(0);
		backs.stop();
	});

	it('closes the layer when a navigation lands on a valid page', async () => {
		holdLayer('account-menu', close);
		await laterTask();

		await navigateTo('/library', { replace: false, reset: false, state: {} });
		stampNavigatedEntry('goto');

		expect(close).toHaveBeenCalledOnce();
		expect(stackedLayers()).toHaveLength(0);
		expect(location.pathname).toBe('/library');
	});

	it('leaves the page on Back with the layer closed, and again after Forward', async () => {
		holdLayer('account-menu', close);
		await laterTask();

		await pressBack();
		expect(close).toHaveBeenCalledOnce();
		await laterTask();
		expect(location.pathname).toBe('/album/a');

		await pressForward();
		expect(location.pathname).toBe(NOT_FOUND);
		holdLayer('account-menu', close);
		await laterTask();
		await pressBack();
		await laterTask();

		expect(close).toHaveBeenCalledTimes(2);
		expect(location.pathname).toBe('/album/a');
	});

	it('mounts the address history already stands on while the page still describes the error page', () => {
		history.replaceState(null, '', '/album/b');

		mountAddressOver('/album/c');

		expect(goto).toHaveBeenCalledWith(
			`${location.origin}/album/b`,
			expect.objectContaining({ replace: true })
		);
	});

	it('mounts nothing over the error page itself', () => {
		mountAddressOver('/elsewhere');

		expect(goto).not.toHaveBeenCalled();
	});
});

describe('a Back onto an entry written over another address', () => {
	beforeEach(async () => {
		sessionStorage.clear();
		history.replaceState(null, '', '/');
		resetHistoryControllerForTests();
		startFakeRouter();
		installHistoryController();
		attachLandingHandler(() => undefined);
		await vi.mocked(goto)('/album/a');
		stampNavigatedEntry('goto');
	});

	afterEach(() => {
		resetHistoryControllerForTests();
		vi.restoreAllMocks();
	});

	it('loads the page the entry was written over, and reports the address it landed on', async () => {
		pushEntry('/album/b', {});
		await historyComesToRest();
		await vi.mocked(goto)('/settings');
		stampNavigatedEntry('goto');
		await historyComesToRest();

		await pressBack();

		expect(fakePage.url.pathname).toBe('/album/a');
		expect(location.pathname).toBe('/album/b');
		expect(reportedNavigations.at(-1)).toEqual({ type: 'popstate', pathname: '/album/b' });
	});
});
