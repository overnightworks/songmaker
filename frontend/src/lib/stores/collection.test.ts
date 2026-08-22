import { beforeEach, describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import { openCollection, resetCollectionForTests, setOpenCollection } from './collection';

beforeEach(() => {
	resetCollectionForTests();
});

describe('collection', () => {
	it('starts with no open collection', () => {
		expect(get(openCollection)).toBeNull();
	});

	it('sets and replaces the open collection', () => {
		setOpenCollection({ kind: 'album', id: 'a1' });
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });

		setOpenCollection({ kind: 'playlist', id: 'p1' });
		expect(get(openCollection)).toEqual({ kind: 'playlist', id: 'p1' });
	});

	it('clears the open collection', () => {
		setOpenCollection({ kind: 'album', id: 'a1' });
		setOpenCollection(null);
		expect(get(openCollection)).toBeNull();
	});
});
