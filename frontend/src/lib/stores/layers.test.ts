import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
	closeTopLayer,
	dropLayersFrom,
	holdLayer,
	holdOpenWhile,
	keepLayerHistory,
	resetLayersForTests,
	stackedLayers,
	type Layer
} from './layers';
import {
	listenForLandings,
	replaceEntry,
	resetHistoryControllerForTests
} from '$lib/history/historyController';
import { startFakeRouter } from '$lib/test-utils/app-navigation';
import { standingHistoryEntry } from '$lib/test-utils/library-history';

vi.mock('$app/navigation', async () =>
	(await import('$lib/test-utils/app-navigation')).fakeAppNavigation()
);

interface Pending {
	work: Promise<void>;
	settle: () => void;
	fail: () => void;
}

function pendingWork(): Pending {
	let settle!: () => void;
	let fail!: () => void;
	const work = new Promise<void>((resolve, reject) => {
		settle = resolve;
		fail = () => reject(new Error('refused'));
	});
	return { work, settle, fail };
}

function stackedIds(): string[] {
	return stackedLayers().map((layer) => layer.id);
}

function followHistory(): Layer[] {
	const entries: Layer[] = [];
	keepLayerHistory({
		held: (layer) => entries.push(layer),
		left: (layer) => {
			if (entries.includes(layer)) entries.splice(entries.indexOf(layer), 1);
		}
	});
	return entries;
}

describe('a layer held open while its overlay saves (#1184 K1)', () => {
	afterEach(() => resetLayersForTests());

	it('lets Escape close nothing until the save has finished', async () => {
		let formOpen = true;
		holdLayer('details-editing', () => (formOpen = false));
		const save = pendingWork();
		const saved = holdOpenWhile('details-saving', save.work);

		expect(closeTopLayer()).toBe(true);
		expect(formOpen).toBe(true);
		expect(stackedIds()).toEqual(['details-editing', 'details-saving']);

		save.settle();
		await saved;
		expect(stackedIds()).toEqual(['details-editing']);
		expect(closeTopLayer()).toBe(true);
		expect(formOpen).toBe(false);
	});

	it('holds itself again without a history entry when Back stepped off its own', async () => {
		const entries = followHistory();
		let formOpen = true;
		holdLayer('details-editing', () => (formOpen = false));
		const save = pendingWork();
		const saved = holdOpenWhile('details-saving', save.work).catch(() => undefined);
		entries.pop();

		dropLayersFrom(1);

		expect(formOpen).toBe(true);
		expect(stackedIds()).toEqual(['details-editing', 'details-saving']);
		expect(entries.map((layer) => layer.id)).toEqual(['details-editing']);

		save.fail();
		await saved;
		expect(stackedIds()).toEqual(['details-editing']);
		expect(entries.map((layer) => layer.id)).toEqual(['details-editing']);
		expect(formOpen).toBe(true);
	});

	it('goes along without holding itself again when the overlay under it closes', async () => {
		const leave = holdLayer('details-editing', () => undefined);
		const save = pendingWork();
		const saved = holdOpenWhile('details-saving', save.work);

		leave();

		expect(stackedIds()).toEqual([]);
		save.settle();
		await saved;
		expect(stackedIds()).toEqual([]);
	});

	it('holds nothing again when one Back jumps past the overlay as well', async () => {
		let formOpen = true;
		holdLayer('details-editing', () => (formOpen = false));
		const save = pendingWork();
		const saved = holdOpenWhile('details-saving', save.work);

		dropLayersFrom(0);

		expect(formOpen).toBe(false);
		expect(stackedIds()).toEqual([]);
		save.settle();
		await saved;
		expect(stackedIds()).toEqual([]);
	});

	it('keeps a layer opened above it during the save open when the save is refused', async () => {
		holdLayer('details-editing', () => undefined);
		const save = pendingWork();
		const saved = holdOpenWhile('details-saving', save.work).catch(() => undefined);
		let drawerOpen = true;
		holdLayer('rail-drawer', () => (drawerOpen = false));

		save.fail();
		await saved;

		expect(drawerOpen).toBe(true);
		expect(stackedIds()).toEqual(['details-editing', 'rail-drawer']);
	});
});

// Issue #1006 H2: while history is followed, each layer owns an entry the
// history controller pushed for it, and a landing closes exactly the layers
// whose entries it left.
describe('layers as history entries', () => {
	let stopListening: () => void;
	let page: number;

	beforeEach(() => {
		sessionStorage.clear();
		history.replaceState(null, '', '/');
		resetHistoryControllerForTests();
		startFakeRouter();
		page = replaceEntry('/', {})?.id ?? Number.NaN;
		stopListening = listenForLandings(() => undefined);
	});

	afterEach(() => {
		stopListening();
		resetLayersForTests();
	});

	async function pressBack(): Promise<void> {
		const landed = new Promise((resolve) =>
			window.addEventListener('popstate', resolve, { once: true })
		);
		history.back();
		await landed;
	}

	it('save held, drawer opened above, save settles, Back', async () => {
		let editorOpen = true;
		let drawerOpen = true;
		holdLayer('details-editing', () => (editorOpen = false));
		const editing = standingHistoryEntry();
		const save = pendingWork();
		const saved = holdOpenWhile('details-saving', save.work);
		holdLayer('rail-drawer', () => (drawerOpen = false));
		save.settle();
		await saved;

		await pressBack();

		await vi.waitFor(() => expect(standingHistoryEntry()).toEqual(editing));
		expect(drawerOpen).toBe(false);
		expect(editorOpen).toBe(true);
		expect(stackedIds()).toEqual(['details-editing']);
		await pressBack();
		expect(editorOpen).toBe(false);
		expect(standingHistoryEntry()?.id).toBe(page);
	});

	it('held re-hold pushes no new entry', async () => {
		let editorOpen = true;
		holdLayer('details-editing', () => (editorOpen = false));
		const editing = standingHistoryEntry();
		const save = pendingWork();
		const saved = holdOpenWhile('details-saving', save.work);
		const lengthWithBoth = history.length;

		await pressBack();
		await vi.waitFor(() => expect(standingHistoryEntry()).toEqual(editing));

		expect(stackedIds()).toEqual(['details-editing', 'details-saving']);
		expect(history.length).toBe(lengthWithBoth);
		expect(closeTopLayer()).toBe(true);
		expect(editorOpen).toBe(true);
		await pressBack();
		expect(editorOpen).toBe(false);
		expect(stackedIds()).toEqual([]);
		save.settle();
		await saved;
		expect(stackedIds()).toEqual([]);
	});
});
