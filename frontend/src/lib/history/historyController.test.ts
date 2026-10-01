import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { goto } from '$app/navigation';
import {
	allocateEntryId,
	land,
	landedEntry,
	listenForLandings,
	loadHistoryPageForTests,
	navigateTo,
	pageStateOfHistoryState,
	pushEntry,
	replaceEntry,
	resetHistoryControllerForTests,
	stampNavigatedEntry,
	stepBackTo,
	type HistoryEntry
} from '$lib/history/historyController';
import { holdLayer, resetLayersForTests, stackedLayers } from '$lib/stores/layers';
import { startFakeRouter } from '$lib/test-utils/app-navigation';

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

describe('landing reducer', () => {
	it('an own step lands on the expected id', () => {
		const outcome = land(ledger({ stepBacks: [6] }), { id: 6 });

		expect(outcome).toMatchObject({ settled: [6], dropLayers: [], stepOff: false, apply: false });
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
		expect(outcome).toMatchObject({ stepOff: false, apply: false });
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
			stepOff: false,
			apply: true
		});
		expect(outcome.ledger).toEqual({ layers: [], stepBacks: [], current: null });
	});

	it.each([
		{ after: 'a reload', layers: [] },
		{ after: 'Forward past an open layer', layers: [{ layer: 'now-playing', entry: 7 }] }
	])('a stale layer entry after $after is stepped off', ({ layers }) => {
		const outcome = land(ledger({ layers }), { id: 9, layer: 'album-menu' });

		expect(outcome).toMatchObject({ stepOff: true, apply: false, dropLayers: [] });
		expect(outcome.ledger.current).toEqual({ id: 6 });
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
	let stopListening: () => void;
	let landingHeard: (() => void) | null = null;

	function nextLanding(): Promise<void> {
		return new Promise((resolve) => {
			landingHeard = resolve;
		});
	}

	beforeEach(() => {
		sessionStorage.clear();
		history.replaceState(null, '', '/');
		resetHistoryControllerForTests();
		landings.length = 0;
		stopListening = listenForLandings((landing) => {
			landings.push(landing);
			landingHeard?.();
		});
	});

	afterEach(() => {
		stopListening();
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

	it('a push stamps a fresh id and a replace keeps the id and the layer mark', () => {
		const page = pushEntry('/album/a', {});
		const layer = pushEntry('/album/a', {}, 'album-menu');

		const replaced = replaceEntry('/album/a', {});

		expect(layer.id).toBeGreaterThan(page.id);
		expect(replaced).toEqual(layer);
		expect(history.state['sveltekit:states'].entry).toEqual(layer);
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
		resetHistoryControllerForTests();
		await stepBackTo(page.id);

		const steppedBack = nextLanding().then(nextLanding);
		history.forward();
		await steppedBack;

		expect(landings.slice(1).map(({ stepOff }) => stepOff)).toEqual([true, false]);
		expect(history.state['sveltekit:states'].entry).toEqual(page);
	});

	it('keeps stamping and pushing entries when session storage refuses writes', () => {
		sessionStorageRefusingWritesAfter(0);
		seedForeignEntry('/album/a');

		const first = replaceEntry('/album/a', {});
		const pushed = pushEntry('/album/b', {});

		expect(first).toEqual({ id: 1 });
		expect(pushed).toEqual({ id: 2 });
		expect(standingEntry()).toEqual(pushed);
	});

	it('ids stay monotonic after session storage starts refusing writes', () => {
		sessionStorageRefusingWritesAfter(2);

		const ids = ['/album/a', '/album/b', '/album/c', '/album/d'].map(
			(url) => pushEntry(url, {}).id
		);

		expect(ids).toEqual([1, 2, 3, 4]);
	});

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
		seedForeignEntry('/legal');
		vi.spyOn(history, 'length', 'get').mockReturnValue(1);
		const first = replaceEntry('/legal', {});
		vi.restoreAllMocks();
		const back = vi.spyOn(history, 'back');

		await stepBackTo((first as HistoryEntry).id - 1);

		expect(back).not.toHaveBeenCalled();
		expect(landings).toEqual([]);
	});

	it('a navigation pushes a fresh id and a replacing one keeps the id it writes over', async () => {
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
		expect(standingEntry()).toEqual({ id: expect.any(Number) });
		expect((standingEntry() as HistoryEntry).id).toBeGreaterThan(page.id);
	});

	it.each([
		{ by: 'a link', type: 'link' as const },
		{ by: 'a goto from elsewhere', type: 'goto' as const }
	])('an entry $by writes without an id gets one on top', async ({ type }) => {
		pushEntry('/album/a', {});
		await vi.mocked(goto)('/settings');

		stampNavigatedEntry(type);

		expect(standingEntry()).toEqual({ id: expect.any(Number) });
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

	it('a router push after a Back gets an id on top', async () => {
		pushEntry('/album/a', {});
		const song = pushEntry('/album/a/song', {});
		await traverse(() => history.back());

		await vi.mocked(goto)('/settings');
		stampNavigatedEntry('link');

		expect(standingEntry()).toEqual({ id: expect.any(Number) });
		expect((standingEntry() as HistoryEntry).id).toBeGreaterThan(song.id);
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

	it('the router start gets back the id the entry was loaded with', () => {
		const loaded = pushEntry('/album/a', {});
		loadHistoryPageForTests();
		startFakeRouter();

		stampNavigatedEntry('enter');

		expect(standingEntry()).toEqual(loaded);
		expect(location.pathname).toBe('/album/a');
	});
});
