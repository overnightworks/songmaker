import { describe, expect, it } from 'vitest';
import { routerHistoryEntry } from '#lib/test-utils/router-history-layout.ts';
import { pageStateOfHistoryState, routerIndexOf } from './routerHistoryState.ts';

describe("the reader of SvelteKit's history-entry layout", () => {
	it('reads the page state of an entry the router wrote', () => {
		const state = routerHistoryEntry({ entry: { id: 5 } }, { historyIndex: 3 });

		expect(pageStateOfHistoryState(state)).toEqual({ entry: { id: 5 } });
	});

	it("reads the router's place of an entry the router wrote", () => {
		expect(routerIndexOf(routerHistoryEntry({}, { historyIndex: 3 }))).toBe(3);
	});

	it.each([
		{ stored: 'a record the router did not write', state: { entry: { id: 5 } } },
		{ stored: 'null', state: null },
		{ stored: 'a string', state: 'sveltekit' }
	])('finds neither page state nor place in $stored', ({ state }) => {
		expect(pageStateOfHistoryState(state)).toBeNull();
		expect(routerIndexOf(state)).toBeUndefined();
	});
});
