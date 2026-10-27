import type { NavigationTarget } from '@sveltejs/kit';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { goto } from '$app/navigation';
import {
	allocateEntryId,
	attachLandingHandler,
	historyStandsStill,
	installHistoryController,
	land,
	landedEntry,
	loadHistoryPageForTests,
	mountRouteOfLandedAddress,
	navigateTo,
	pageBelowStandingPage,
	pageStateOfHistoryState,
	pushEntry,
	remountOverStandingEntry,
	replaceEntry,
	resetHistoryControllerForTests,
	stampNavigatedEntry,
	standingPageEntryId,
	stepBackOr,
	stepBackOrGoTo,
	stepBackTo,
	type HistoryEntry
} from '$lib/history/historyController';
import { holdLayer, resetLayersForTests, stackedLayers } from '$lib/stores/layers';
import {
	fakePage,
	followBeforeNavigate,
	holdRouteLoads,
	reportedNavigations,
	startFakeRouter
} from '$lib/test-utils/app-navigation';
import { watchBack } from '$lib/test-utils/library-history';

type Ledger = Parameters<typeof land>[0];
type Landing = ReturnType<typeof land>;

function ledger(overrides: Partial<Ledger> = {}): Ledger {
	return { layers: [], stepBacks: [], current: { id: 6 }, ...overrides };
}

function landAll(start: Ledger, landings: (HistoryEntry | null)[]): Landing[] {
	const outcomes: Landing[] = [];
	let state = start;
	for (const landed of landings) {
		const outcome = land(state, landed);
		outcomes.push(outcome);
		state = outcome.ledger;
	}
	return outcomes;
}

function memoryStorage(): Pick<Storage, 'getItem' | 'setItem'> {
	const items = new Map<string, string>();
	return {
		getItem: (key) => items.get(key) ?? null,
		setItem: (key, value) => void items.set(key, value)
	};
}

function storageQuotaExceeded(): DOMException {
	return new DOMException('The quota has been exceeded.', 'QuotaExceededError');
}

function storageAccessDenied(): DOMException {
	return new DOMException('Access is denied for this document.', 'SecurityError');
}

function sessionStorageRefusingWritesAfter(acceptedWrites: number): void {
	const acceptWrite = Storage.prototype.setItem;
	let writes = 0;
	vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (
		this: Storage,
		key: string,
		value: string
	) {
		writes += 1;
		if (writes > acceptedWrites) throw storageQuotaExceeded();
		acceptWrite.call(this, key, value);
	});
}

async function popstateAfterBack(): Promise<void> {
	const landed = new Promise((resolve) =>
		window.addEventListener('popstate', resolve, { once: true })
	);
	history.back();
	await landed;
}

describe('landing reducer', () => {
	it('an own step lands on the expected id', () => {
		const outcome = land(ledger({ stepBacks: [6] }), { id: 6 });

		expect(outcome).toMatchObject({ settled: [6], dropLayers: [], apply: false });
		expect(outcome.ledger.stepBacks).toEqual([]);
	});

	it.each([
		{ first: 'on the own target', landings: [{ id: 6 }, { id: 4 }] },
		{ first: 'past the own target', landings: [{ id: 4 }, { id: 3 }] }
	])(
		'a user Back interleaved with an own step converges on the last landing (first $first)',
		({ landings }) => {
			const outcomes = landAll(ledger({ current: { id: 6 }, stepBacks: [6] }), landings);
			expect(outcomes.flatMap((outcome) => outcome.settled)).toEqual([6]);
			expect(outcomes.at(-1)).toMatchObject({
				apply: true,
				ledger: { layers: [], stepBacks: [], current: landings.at(-1) }
			});
		}
	);

	it('a multi-entry jump drops exactly the layers above the landing', () => {
		const below = { layer: 'now-playing', entry: 5 };
		const middle = { layer: 'rail-drawer', entry: 7 };
		const top = { layer: 'album-menu', entry: 8 };

		const outcome = land(ledger({ current: { id: 4 }, layers: [below, middle, top] }), {
			id: 5,
			layer: 'now-playing'
		});

		expect(outcome.dropLayers).toEqual([top, middle]);
		expect(outcome).toMatchObject({ apply: false });
		expect(outcome.ledger.layers).toEqual([below]);
	});

	it('an id-less landing is foreign and lowest', () => {
		const layers = [
			{ layer: 'now-playing', entry: 2 },
			{ layer: 'album-menu', entry: 3 }
		];

		const outcome = land(ledger({ current: { id: 1 }, layers, stepBacks: [1, 2] }), null);

		expect(outcome).toMatchObject({
			dropLayers: [...layers].reverse(),
			settled: [1, 2],
			apply: true
		});
		expect(outcome.ledger).toEqual({ layers: [], stepBacks: [], current: null });
	});

	it.each([
		{ after: 'a reload', layers: [] },
		{ after: 'Forward past an open layer', layers: [{ layer: 'now-playing', entry: 7 }] }
	])('a stale layer entry after $after is unowned and lands without applying', ({ layers }) => {
		const stale = { id: 9, layer: 'album-menu' };
		const outcome = land(ledger({ layers }), stale);
		expect(outcome).toMatchObject({ apply: false, dropLayers: [], ledger: { current: { id: 6 } } });
	});
});

describe('entry ids', () => {
	it('the allocator stays monotonic across a simulated reload', () => {
		const tab = memoryStorage();
		const beforeReload = [allocateEntryId(tab), allocateEntryId(tab)];

		const afterReload = allocateEntryId(tab);

		expect(beforeReload).toEqual([1, 2]);
		expect(afterReload).toBe(3);
	});

	it('refuses a counter that is not a count', () => {
		const tab = memoryStorage();
		tab.setItem('songmaker:history-entry-id', 'twelve');

		expect(() => allocateEntryId(tab)).toThrow(/not a count/);
	});

	it.each([
		{
			stored: 'under SvelteKit states key',
			state: { 'sveltekit:history': 3, 'sveltekit:states': { entry: { id: 5, layer: 'menu' } } },
			entry: { id: 5, layer: 'menu' }
		},
		{ stored: 'raw beside the states key', state: { entry: { id: 5 } }, entry: null },
		{ stored: 'without an id', state: { 'sveltekit:states': { entry: { id: 0 } } }, entry: null },
		{ stored: 'nowhere', state: null, entry: null }
	])("the popstate reader reads the entry under SvelteKit's states key ($stored)", (fixture) => {
		expect(landedEntry(new PopStateEvent('popstate', { state: fixture.state }))).toEqual(
			fixture.entry
		);
	});
});

describe('history adapter', () => {
	const landings: Landing[] = [];
	let detachLandingHandler: () => void;
	let landingHeard: (() => void) | null = null;

	function nextLanding(): Promise<void> {
		return new Promise((resolve) => {
			landingHeard = resolve;
		});
	}

	function attachRecordingHandler(): void {
		detachLandingHandler = attachLandingHandler((landing) => {
			landings.push(landing);
			landingHeard?.();
		});
	}

	// A page load, the way the app starts one: the controller starts afresh,
	// the root layout installs it, and the library attaches its handler.
	function loadPage(): void {
		resetHistoryControllerForTests();
		installHistoryController();
		attachRecordingHandler();
	}

	beforeEach(() => {
		sessionStorage.clear();
		history.replaceState(null, '', '/');
		landings.length = 0;
		loadPage();
	});

	afterEach(() => {
		resetHistoryControllerForTests();
		resetLayersForTests();
		vi.restoreAllMocks();
	});

	async function traverse(step: () => void): Promise<void> {
		const landed = nextLanding();
		step();
		await landed;
	}

	function standingEntry(): unknown {
		return pageStateOfHistoryState(history.state)?.entry;
	}

	function seedForeignEntry(url: string): void {
		history.replaceState(null, '', url);
	}

	// Where a page's own Back goes in these tests when no page lies below.
	const FALLBACK = '/settings';

	function addressOf(path: string): string {
		return new URL(path, location.href).href;
	}

	// The page the app is entered on by a load of a fresh document, into a tab
	// that then holds `tabLength` entries, from the page `referrer` names.
	function enterApp(url: string, tabLength: number, referrer = ''): void {
		seedForeignEntry(url);
		vi.spyOn(document, 'referrer', 'get').mockReturnValue(referrer);
		const length = vi.spyOn(history, 'length', 'get').mockReturnValue(tabLength);
		loadHistoryPageForTests();
		startFakeRouter();
		stampNavigatedEntry('enter');
		length.mockRestore();
	}

	it('a push stamps a fresh id and a replace keeps the id and the layer mark', () => {
		const page = pushEntry('/album/a', {});
		const layer = pushEntry('/album/a', {}, 'album-menu');

		const replaced = replaceEntry('/album/a', {});

		expect(layer.id).toBeGreaterThan(page.id);
		expect(replaced).toEqual(layer);
		expect(history.state['sveltekit:states'].entry).toEqual(layer);
	});

	it("a page's own Back goes to the page it was pushed over, after a rename too", () => {
		pushEntry('/album/a', {});

		replaceEntry('/album/a-renamed', {});

		expect(pageBelowStandingPage()).toBe(addressOf('/'));
	});

	it('an own step-back resolves when it lands on its target', async () => {
		const page = pushEntry('/album/a', {});
		pushEntry('/album/a', {}, 'album-menu');

		await stepBackTo(page.id);

		expect(landings).toHaveLength(1);
		expect(landings[0]).toMatchObject({ settled: [page.id], apply: false });
	});

	it('steps off a stale layer entry Forward lands on after a reload', async () => {
		const page = pushEntry('/album/a', {});
		pushEntry('/album/a', {}, 'album-menu');
		loadPage();
		await stepBackTo(page.id);

		const steppedBack = nextLanding().then(nextLanding);
		history.forward();
		await steppedBack;

		expect(landings.slice(1).map(({ settled }) => settled)).toEqual([[], [page.id]]);
		expect(history.state['sveltekit:states'].entry).toEqual(page);
	});

	it('keeps stamping and pushing entries when session storage refuses writes', () => {
		sessionStorageRefusingWritesAfter(0);
		seedForeignEntry('/album/a');

		const first = replaceEntry('/album/a', {});
		const pushed = pushEntry('/album/b', {});

		expect(first).toEqual({ id: 1 });
		expect(pushed.id).toBe(2);
		expect(standingEntry()).toEqual(pushed);
	});

	it('ids stay monotonic after session storage starts refusing writes', () => {
		sessionStorageRefusingWritesAfter(2);

		const ids = ['/album/a', '/album/b', '/album/c', '/album/d'].map(
			(url) => pushEntry(url, {}).id
		);

		expect(ids).toEqual([1, 2, 3, 4]);
	});

	it.each([
		{ after: 'a reload lands on', viaForward: false },
		{ after: 'Forward lands on after a reload', viaForward: true }
	])(
		'ids stay above the entry $after while session storage refuses writes',
		async ({ viaForward }) => {
			sessionStorageRefusingWritesAfter(0);
			['/album/a', '/album/b', '/album/c'].forEach((url) => pushEntry(url, {}));
			if (viaForward) await traverse(() => history.back());
			loadPage();
			if (viaForward) await traverse(() => history.forward());

			expect(pushEntry('/album/c', {}, 'now-playing').id).toBe(4);
		}
	);

	const reachingSessionStorage = () => vi.spyOn(window, 'sessionStorage', 'get');
	const readingSessionStorage = () => vi.spyOn(Storage.prototype, 'getItem');
	const writingSessionStorage = () => vi.spyOn(Storage.prototype, 'setItem');

	it.each([
		{ denied: 'reaching', spyOn: reachingSessionStorage, loadedOnto: null, ids: [1, 2] },
		{ denied: 'reading', spyOn: readingSessionStorage, loadedOnto: null, ids: [1, 2] },
		{ denied: 'writing', spyOn: writingSessionStorage, loadedOnto: null, ids: [1, 2] },
		{ denied: 'reaching', spyOn: reachingSessionStorage, loadedOnto: 3, ids: [4, 5] }
	])(
		'loads onto entry $loadedOnto and keeps stamping entries when the browser denies $denied session storage',
		async ({ spyOn, loadedOnto, ids }) => {
			if (loadedOnto !== null) {
				history.replaceState({ 'sveltekit:states': { entry: { id: loadedOnto } } }, '', '/album/c');
			}
			spyOn().mockImplementation(() => {
				throw storageAccessDenied();
			});
			vi.resetModules();

			const loaded = await import('$lib/history/historyController');
			const pushed = ['/album/a', '/album/b'].map((url) => loaded.pushEntry(url, {}).id);

			expect(pushed).toEqual(ids);
		}
	);

	it('a session storage write failing for another reason is not swallowed', () => {
		vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
			throw new TypeError('broken storage');
		});

		expect(() => pushEntry('/album/a', {})).toThrow(/broken storage/);
	});

	it('an id-less entry on top gets its first id', () => {
		seedForeignEntry('/album/a');

		const stamped = replaceEntry('/album/a', {});

		expect(stamped).toEqual({ id: expect.any(Number) });
		expect(standingEntry()).toEqual(stamped);
	});

	it('an id-less entry below stamped entries stays foreign', async () => {
		seedForeignEntry('/album/a');
		pushEntry('/album/b', {});
		const landed = nextLanding();
		history.back();
		await landed;

		const stamped = replaceEntry('/album/a', {});

		expect(stamped).toBeNull();
		expect(standingEntry()).toBeUndefined();
	});

	it('stepBackTo on the first entry resolves at once', async () => {
		seedForeignEntry('/no-access');
		vi.spyOn(history, 'length', 'get').mockReturnValue(1);
		const first = replaceEntry('/no-access', {});
		vi.restoreAllMocks();
		const back = vi.spyOn(history, 'back');

		await stepBackTo((first as HistoryEntry).id - 1);

		expect(back).not.toHaveBeenCalled();
		expect(landings).toEqual([]);
	});

	it('a navigation pushes a fresh id over the page it leaves, and a replacing one keeps the entry it writes over', async () => {
		const page = pushEntry('/album/a', {});

		await navigateTo('/album/a/song', {
			replaceState: true,
			noScroll: true,
			keepFocus: true,
			state: {}
		});
		const replaced = standingEntry();
		await navigateTo('/settings', {
			replaceState: false,
			noScroll: true,
			keepFocus: true,
			state: {}
		});

		expect(replaced).toEqual(page);
		expect((standingEntry() as HistoryEntry).id).toBeGreaterThan(page.id);
		expect(pageBelowStandingPage()).toBe(addressOf('/album/a/song'));
	});

	it.each([
		{ by: 'a link', type: 'link' as const },
		{ by: 'a goto from elsewhere', type: 'goto' as const }
	])(
		'an entry $by writes without an id gets one on top, over the page it left',
		async ({ type }) => {
			pushEntry('/album/a', {});
			await vi.mocked(goto)('/settings');

			stampNavigatedEntry(type);

			expect(standingPageEntryId()).toEqual(expect.any(Number));
			expect(pageBelowStandingPage()).toBe(addressOf('/album/a'));
		}
	);

	it('a Back while no handler was attached is heard once a handler attaches, and only once', async () => {
		const album = pushEntry('/album/a', {});
		pushEntry('/album/b', {});
		detachLandingHandler();
		await popstateAfterBack();

		const heard: Landing[] = [];
		detachLandingHandler = attachLandingHandler((landing) => heard.push(landing));
		detachLandingHandler();
		detachLandingHandler = attachLandingHandler((landing) => heard.push(landing));

		expect(heard).toHaveLength(1);
		expect(heard[0]).toMatchObject({ apply: true, ledger: { current: album } });
	});

	it('Back closes the open layer while no handler is attached, and leaves the page where it is', async () => {
		const page = pushEntry('/settings/voices', {});
		let menuOpen = true;
		holdLayer('account-menu', () => (menuOpen = false));
		detachLandingHandler();
		await popstateAfterBack();

		expect(menuOpen).toBe(false);
		expect(stackedLayers()).toEqual([]);
		expect(standingEntry()).toEqual(page);
		expect(location.pathname).toBe('/settings/voices');
	});

	it("a page's own Back steps back onto the page of the tab it was opened from", async () => {
		const signIn = pushEntry('/login', {});
		pushEntry('/no-access', {});
		vi.mocked(goto).mockClear();

		await stepBackOrGoTo('/login');

		expect(standingEntry()).toEqual(signIn);
		expect(goto).not.toHaveBeenCalled();
	});

	// One question decides both where a page's own Back goes and what the
	// phone's ‹ calls it (#1389): the page below, or the fallback written over
	// the page. Either way the tab holds no more entries than before, and the
	// page Back lands on names where its own Back goes next.
	it.each([
		{
			standing: 'a page pushed over another',
			arrange: () => void pushEntry('/album/a', {}),
			lands: '/',
			next: null
		},
		{
			standing: 'a page pushed over a page pushed over another',
			arrange: () => {
				pushEntry('/album/a', {});
				pushEntry('/album/b', {});
			},
			lands: '/album/a',
			next: '/'
		},
		{
			standing: 'an entry without an id',
			arrange: () => seedForeignEntry('/album/a'),
			lands: FALLBACK,
			next: null
		},
		{
			standing: 'an entry that does not know the page below it',
			arrange: () => {
				seedForeignEntry('/album/a');
				replaceEntry('/album/a', {});
			},
			lands: FALLBACK,
			next: null
		},
		{
			standing: "the tab's first entry",
			arrange: () => enterApp('/album/a', 1),
			lands: FALLBACK,
			next: null
		},
		{
			standing: 'the page the app was entered on from one of its own pages',
			arrange: () => {
				seedForeignEntry('/login');
				history.pushState(null, '', '/no-access');
				enterApp('/no-access', 2, addressOf('/login'));
			},
			lands: '/login',
			next: null
		}
	])("a page's own Back on $standing lands on $lands", async ({ arrange, lands, next }) => {
		arrange();
		const tabLength = history.length;
		const reported = reportedNavigations.length;

		await stepBackOrGoTo(FALLBACK);
		for (const { type } of reportedNavigations.slice(reported)) stampNavigatedEntry(type);

		expect(location.pathname).toBe(lands);
		expect(history).toHaveLength(tabLength);
		expect(pageBelowStandingPage()).toBe(next === null ? null : addressOf(next));
	});

	it("a page's own Back keeps its target while a layer covers the page", () => {
		pushEntry('/album/a', {});

		holdLayer('album-menu', () => undefined);

		expect(pageBelowStandingPage()).toBe(addressOf('/'));
	});

	it.each([
		{ opened: 'as the only entry of its tab', tabLength: 1 },
		{ opened: 'by a tab that came from another site', tabLength: 3 }
	])(
		"a page's own Back on the page the app was entered on $opened goes to the fallback, written over it",
		async ({ tabLength }) => {
			enterApp('/no-access', tabLength);
			const back = vi.spyOn(history, 'back');
			vi.mocked(goto).mockClear();

			await stepBackOrGoTo('/login');

			expect(back).not.toHaveBeenCalled();
			expect(goto).toHaveBeenCalledWith('/login', { replaceState: true });
			expect(location.pathname).toBe('/login');
		}
	);

	// A list the library shows from its own stores is no plain route: the page
	// hands its Back the write that opens it, which runs only where no page of
	// the tab's own lies below (#1389).
	it.each([
		{
			standing: 'a page pushed over another',
			arrange: () => void pushEntry('/album/a', {}),
			lands: '/'
		},
		{ standing: "the tab's first entry", arrange: () => enterApp('/album/a', 1), lands: FALLBACK }
	])(
		"a page's own Back on $standing, given the write that opens its list, lands on $lands",
		async ({ arrange, lands }) => {
			arrange();
			const tabLength = history.length;

			await stepBackOr(async () => void replaceEntry(FALLBACK, {}));

			expect(location.pathname).toBe(lands);
			expect(history).toHaveLength(tabLength);
		}
	);

	it('refuses a second install', () => {
		expect(() => installHistoryController()).toThrow(/already installed/);
	});

	it('refuses a second landing handler while one is attached', () => {
		expect(() => attachLandingHandler(() => undefined)).toThrow(/already attached/);
	});

	it('the page entry under an open layer is the page the layer covers', () => {
		const page = pushEntry('/album/a', {});

		holdLayer('album-menu', () => undefined);

		expect(standingEntry()).toEqual({ id: expect.any(Number), layer: 'album-menu' });
		expect(standingPageEntryId()).toBe(page.id);
	});

	it('a page push closes the layers below it', () => {
		pushEntry('/album/a', {});
		let menuOpen = true;
		holdLayer('album-menu', () => (menuOpen = false));

		const song = pushEntry('/album/a/song', {});

		expect(menuOpen).toBe(false);
		expect(stackedLayers()).toEqual([]);
		expect(standingEntry()).toEqual(song);
	});

	it("Forward onto a closed layer's entry steps off it", async () => {
		const wall = pushEntry('/', {});
		const album = pushEntry('/album/a', {});
		holdLayer('album-menu', () => undefined);
		await traverse(() => history.back());
		expect(stackedLayers()).toEqual([]);

		await traverse(() => history.forward());
		await vi.waitFor(() => expect(standingEntry()).toEqual(album));
		await traverse(() => history.back());

		expect(standingEntry()).toEqual(wall);
	});

	it('a router push after a Back gets an id on top, over the page Back landed on', async () => {
		pushEntry('/album/a', {});
		const song = pushEntry('/album/a/song', {});
		await traverse(() => history.back());

		await vi.mocked(goto)('/settings');
		stampNavigatedEntry('link');

		expect((standingEntry() as HistoryEntry).id).toBeGreaterThan(song.id);
		expect(pageBelowStandingPage()).toBe(addressOf('/album/a'));
	});

	it('a router replace after a Back stays foreign below stamped entries', async () => {
		pushEntry('/album/a', {});
		pushEntry('/album/a/song', {});
		history.replaceState(null, '', '/album/b');
		pushEntry('/album/b/song', {});
		await traverse(() => history.back());

		await vi.mocked(goto)('/album/c', { replaceState: true });
		stampNavigatedEntry('goto');

		expect(standingEntry()).toBeUndefined();
	});

	it('the router start gets back the id and the page below the entry was loaded with', () => {
		const loaded = pushEntry('/album/a', {});
		loadHistoryPageForTests();
		startFakeRouter();

		stampNavigatedEntry('enter');

		expect(standingEntry()).toEqual(loaded);
		expect(pageBelowStandingPage()).toBe(addressOf('/'));
		expect(location.pathname).toBe('/album/a');
	});

	// The router starts listening for popstate only after the page it started on
	// is mounted, and its handling would abort a navigation the controller's
	// part of a landing released before it.
	it('hears a landing after the router once the router start has run to its end', async () => {
		pushEntry('/album/a', {});
		pushEntry('/album/b', {});
		const heard: string[] = [];
		const routerHears = (): number => heard.push('router');
		stampNavigatedEntry('enter');
		window.addEventListener('popstate', routerHears);
		await historyStandsStill();
		detachLandingHandler();
		detachLandingHandler = attachLandingHandler(() => heard.push('controller'));

		await popstateAfterBack();
		window.removeEventListener('popstate', routerHears);

		expect(heard).toEqual(['router', 'controller']);
	});

	it('the router start steps off a layer entry a reload came back onto', async () => {
		const page = pushEntry('/settings/voices', {});
		pushEntry('/settings/voices', {}, 'account-menu');
		resetHistoryControllerForTests();
		loadHistoryPageForTests();
		startFakeRouter();
		installHistoryController();
		attachRecordingHandler();

		const steppedOff = nextLanding();
		stampNavigatedEntry('enter');
		await steppedOff;

		expect(standingEntry()).toEqual(page);
		expect(location.pathname).toBe('/settings/voices');
	});

	it('A1 (#1921): a second landing on the unowned layer entry presses Back once in total', () => {
		pushEntry('/settings/voices', {});
		pushEntry('/settings/voices', {}, 'account-menu');
		resetHistoryControllerForTests();
		loadHistoryPageForTests();
		const back = watchBack();
		installHistoryController();
		attachRecordingHandler();

		window.dispatchEvent(new PopStateEvent('popstate', { state: history.state }));
		expect(back.presses()).toBe(1);
		back.stop();
	});
});

describe('route convergence after a landing', () => {
	let stopConverging: () => void;

	beforeEach(async () => {
		sessionStorage.clear();
		history.replaceState(null, '', '/');
		resetHistoryControllerForTests();
		startFakeRouter();
		installHistoryController();
		attachLandingHandler(() => undefined);
		stopConverging = followBeforeNavigate(mountRouteOfLandedAddress);
		await vi.mocked(goto)('/album/a');
		stampNavigatedEntry('goto');
	});

	afterEach(() => {
		stopConverging();
		resetHistoryControllerForTests();
		vi.restoreAllMocks();
	});

	function standingEntry(): unknown {
		return pageStateOfHistoryState(history.state)?.entry;
	}

	async function backFromSettings(): Promise<void> {
		await vi.mocked(goto)('/settings');
		stampNavigatedEntry('goto');
		await popstateAfterBack();
	}

	it('Back onto an entry written over another page mounts the route of its own address', async () => {
		const albumB = pushEntry('/album/b', {});

		await backFromSettings();

		expect(fakePage.url.pathname).toBe('/album/b');
		expect(location.pathname).toBe('/album/b');
		expect(standingEntry()).toEqual(albumB);
		expect(fakePage.state).toEqual({ entry: albumB });
		expect(reportedNavigations.at(-1)).toEqual({ type: 'goto', pathname: '/album/b' });
	});

	it('Back onto an entry the router wrote at its own address mounts it as it is', async () => {
		const albumA = standingEntry();

		await backFromSettings();

		expect(fakePage.url.pathname).toBe('/album/a');
		expect(standingEntry()).toEqual(albumA);
		expect(reportedNavigations.at(-1)).toEqual({ type: 'popstate', pathname: '/album/a' });
	});

	// Issue #1263: a page pushed while the router still loads the route of the
	// entry below stands at once; the mount issued again over it lands on it,
	// and the older one, superseded, writes nothing.
	it('a page pushed while a route mounts stands at once, and the mount issued over it lands on it', async () => {
		const routesLoaded = holdRouteLoads();
		const albumMounted = navigateTo(location.href, {
			replaceState: true,
			noScroll: true,
			keepFocus: true,
			state: {}
		});

		const albumB = pushEntry('/album/b', {});
		const albumBMounted = remountOverStandingEntry('/album/b', {});

		expect(location.pathname).toBe('/album/b');
		expect(standingEntry()).toEqual(albumB);
		routesLoaded();
		await Promise.all([albumMounted, albumBMounted]);
		expect(fakePage.url.pathname).toBe('/album/b');
		expect(standingEntry()).toEqual(albumB);
	});

	function navigationTo(pathname: string): NavigationTarget {
		return { url: new URL(pathname, location.href), params: {}, route: { id: null }, scroll: null };
	}

	function abortableNavigation(): { complete: Promise<void>; abort: () => Promise<void> } {
		let reject: (reason: Error) => void = () => undefined;
		const complete = new Promise<void>((_, rejectComplete) => (reject = rejectComplete));
		return {
			complete,
			abort: async () => {
				reject(new Error('navigation aborted'));
				await complete.catch(() => undefined);
			}
		};
	}

	// Issue #1006 H5: the router takes a Back onto an entry of the navigation
	// it is heading to for shallow routing, and the navigation that Back aborts
	// mounts nothing -- the page before stays on screen under the address.
	it("a Back that aborts the router's navigation without one of its own mounts the route of the address it landed on", async () => {
		const loading = abortableNavigation();
		mountRouteOfLandedAddress({
			type: 'popstate',
			to: navigationTo('/album/a'),
			complete: loading.complete
		});
		fakePage.url = new URL('/settings', location.href);

		await loading.abort();

		await vi.waitFor(() => expect(fakePage.url.pathname).toBe('/album/a'));
		expect(reportedNavigations.at(-1)).toEqual({ type: 'goto', pathname: '/album/a' });
	});

	// Issue #1340: the first of two Backs from Settings lands on a song's entry
	// written over the album's page, so the router heads to the album and the
	// landing mounts the song over it; the second Back, onto the album, aborts
	// both and starts nothing of its own.
	it('a Back that aborts the mount its landing issued mounts the route of the address it landed on', async () => {
		pushEntry('/album/a/song', {});
		const loading = abortableNavigation();
		vi.mocked(goto).mockImplementationOnce(() => Promise.resolve());
		mountRouteOfLandedAddress({
			type: 'popstate',
			to: navigationTo('/album/a'),
			complete: loading.complete
		});
		await popstateAfterBack();
		fakePage.url = new URL('/settings', location.href);

		await loading.abort();

		await vi.waitFor(() => expect(fakePage.url.pathname).toBe('/album/a'));
		expect(location.pathname).toBe('/album/a');
	});

	it('an aborted navigation leaves the mount to the navigation that took over', async () => {
		const loading = abortableNavigation();
		mountRouteOfLandedAddress({
			type: 'popstate',
			to: navigationTo('/album/a'),
			complete: loading.complete
		});
		mountRouteOfLandedAddress({
			type: 'link',
			to: navigationTo('/settings'),
			complete: new Promise<void>(() => undefined)
		});
		const navigated = reportedNavigations.length;

		await loading.abort();

		expect(reportedNavigations).toHaveLength(navigated);
	});

	// Issue #1340: the router reports a navigation only after the mount it
	// aborts has failed -- the album a tap in the library list opens -- and not at all
	// while another one loads.
	it('an aborted navigation leaves the mount to a page navigation issued before the router reports it', async () => {
		const loading = abortableNavigation();
		mountRouteOfLandedAddress({
			type: 'popstate',
			to: navigationTo('/album/a'),
			complete: loading.complete
		});
		const releaseRouteLoads = holdRouteLoads();
		const navigated = navigateTo('/album/b', {
			replaceState: false,
			noScroll: true,
			keepFocus: true,
			state: {}
		});

		await loading.abort();
		releaseRouteLoads();
		await navigated;

		expect(location.pathname).toBe('/album/b');
	});

	it.each(['link', 'goto'] as const)(
		'a %s navigation to another address is left to the router',
		(type) => {
			const navigated = reportedNavigations.length;

			mountRouteOfLandedAddress({
				type,
				to: navigationTo('/settings'),
				complete: Promise.resolve()
			});

			expect(reportedNavigations).toHaveLength(navigated);
			expect(location.pathname).toBe('/album/a');
		}
	);
});
