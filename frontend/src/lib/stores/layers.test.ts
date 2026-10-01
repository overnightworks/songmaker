import { afterEach, describe, expect, it } from 'vitest';
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
		left: (layer) => entries.splice(entries.indexOf(layer), 1)
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

	it('gives the layer a fresh history entry when Back stepped off its own', async () => {
		const entries = followHistory();
		let formOpen = true;
		holdLayer('details-editing', () => (formOpen = false));
		const save = pendingWork();
		const saved = holdOpenWhile('details-saving', save.work).catch(() => undefined);
		const [, firstSavingEntry] = entries;
		entries.pop();

		dropLayersFrom(1);

		expect(formOpen).toBe(true);
		expect(stackedIds()).toEqual(['details-editing', 'details-saving']);
		expect(entries.map((layer) => layer.id)).toEqual(['details-editing', 'details-saving']);
		expect(entries[1]).not.toBe(firstSavingEntry);

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
