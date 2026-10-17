import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { LibraryListenItem } from '$lib/api/library';
import {
	HOME_PAGE_LABEL,
	LIBRARY_NEW_ALBUM_LABEL,
	LIBRARY_NEW_MENU_LABEL,
	LIBRARY_NEW_PLAYLIST_LABEL,
	NEW_ALBUM_CARD_LABEL
} from '$lib/constants';

import { accessibleName, getByRoleButton } from '$lib/test-utils/accessible-name';

import LibraryHome from './LibraryHome.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

const listenedAlbum: LibraryListenItem = {
	type: 'album',
	id: 'album-1',
	title: 'Open Windows',
	cover: null,
	album_covers: [],
	song_id: null,
	song_title: null,
	song_number: null,
	played_at: '2026-09-27T03:47:00Z'
};

beforeEach(() => {
	vi.stubGlobal(
		'fetch',
		vi.fn(async () => Response.json({ items: [listenedAlbum] }))
	);
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	vi.unstubAllGlobals();
});

async function render(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(LibraryHome, { target }));
	await vi.waitFor(() => expect(target.querySelector('.continue-item')).not.toBeNull());
	await tick();
	return target;
}

describe('LibraryHome', () => {
	it('1354_rule_31: heads the page Home and shows Continue under it', async () => {
		const target = await render();

		expect(target.querySelector('h1')?.textContent).toBe(HOME_PAGE_LABEL);
		expect(target.querySelector('[aria-label="Continue"]')).not.toBeNull();
		expect(target.querySelector('.continue-item')?.getAttribute('aria-label')).toBe(
			'Open album Open Windows'
		);
	});

	it('1354_rule_31: shows no wall of albums', async () => {
		const target = await render();

		expect(target.querySelector('.tile-grid, .wall-tile, .library-wall')).toBeNull();
	});

	it('1354_rule_14 915_C1: stands + New on the head line, whose Album unfolds its card under the head, above Continue', async () => {
		const target = await render();
		const head = target.querySelector('.home-titlebar');
		if (!head) throw new Error('Expected the Home head');

		getByRoleButton(head, LIBRARY_NEW_MENU_LABEL).click();
		await tick();
		const menu = document.body.querySelector(
			`[role="dialog"][aria-label="${LIBRARY_NEW_MENU_LABEL}"]`
		);
		if (!menu) throw new Error('+ New opened no menu');
		expect([...menu.querySelectorAll('button')].map(accessibleName)).toEqual([
			LIBRARY_NEW_ALBUM_LABEL,
			LIBRARY_NEW_PLAYLIST_LABEL
		]);
		getByRoleButton(menu, LIBRARY_NEW_ALBUM_LABEL).click();
		await tick();

		const card = head.querySelector(`[aria-label="${NEW_ALBUM_CARD_LABEL}"]`);
		expect(card).not.toBeNull();
		const continueRegion = target.querySelector('[aria-label="Continue"]');
		expect(card?.compareDocumentPosition(continueRegion as Node)).toBe(
			Node.DOCUMENT_POSITION_FOLLOWING
		);
	});
});
