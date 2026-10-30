import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { AlbumItem, PlaylistItem } from '#lib/api/types.ts';
import { LIBRARY_NEW_MENU_LABEL } from '#lib/constants.ts';
import { openCollection, resetCollectionForTests } from '#lib/stores/collection.ts';
import { toasts } from '#lib/stores/toast.ts';
import { makeAlbum, makePlaylist } from '#lib/test-utils/factories.ts';
import {
	describeBackClosesOverlay,
	replaceHistoryEntry,
	standingHistoryEntry
} from '#lib/test-utils/library-history.ts';

vi.mock('$app/navigation', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation()
);

import NewPlaceMenu from './NewPlaceMenu.svelte';

const TAKEN = 'That name is taken';

interface NewKind {
	choice: 'Album' | 'Playlist';
	card: string;
	close: string;
	field: string;
	endpoint: string;
	name: string;
	created: AlbumItem | PlaylistItem;
	opened: { kind: 'album' | 'playlist'; id: string };
	serverFailure: string;
}

const NEW_ALBUM: NewKind = {
	choice: 'Album',
	card: 'New album',
	close: 'Close new album',
	field: 'Title',
	endpoint: '/api/albums',
	name: 'Night Drive',
	created: makeAlbum({ id: 'a-night', title: 'Night Drive' }),
	opened: { kind: 'album', id: 'a-night' },
	serverFailure: 'The album could not be created. Try again.'
};
const NEW_PLAYLIST: NewKind = {
	choice: 'Playlist',
	card: 'New playlist',
	close: 'Close new playlist',
	field: 'Name',
	endpoint: '/api/playlists',
	name: 'Road Trip',
	created: makePlaylist({ id: 'p-road', title: 'Road Trip', share_slug: null }),
	opened: { kind: 'playlist', id: 'p-road' },
	serverFailure: 'The playlist could not be created. Try again.'
};

const fetchStub = vi.fn();
const mounted: Array<ReturnType<typeof mount>> = [];

beforeEach(() => {
	fetchStub.mockReset().mockImplementation(async (path: string) => {
		const made = [NEW_ALBUM, NEW_PLAYLIST].find((kind) => kind.endpoint === path);
		return Response.json(made?.created ?? { items: [] });
	});
	vi.stubGlobal('fetch', fetchStub);
	resetCollectionForTests();
	toasts.set([]);
	replaceHistoryEntry('/');
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	vi.unstubAllGlobals();
});

async function render(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(NewPlaceMenu, { target }));
	await tick();
	return target;
}

function newButton(root: ParentNode): HTMLButtonElement {
	const button = root.querySelector<HTMLButtonElement>(`[aria-label="${LIBRARY_NEW_MENU_LABEL}"]`);
	if (!button) throw new Error('no + New');
	return button;
}

function newMenu(): HTMLElement | null {
	return document.querySelector<HTMLElement>(
		`[role="dialog"][aria-label="${LIBRARY_NEW_MENU_LABEL}"]`
	);
}

function newCard(root: ParentNode, kind: NewKind): HTMLElement | null {
	return root.querySelector<HTMLElement>(`[aria-label="${kind.card}"]`);
}

async function openNewMenu(root: HTMLElement): Promise<HTMLElement> {
	newButton(root).click();
	await tick();
	await tick();
	const menu = newMenu();
	if (!menu) throw new Error('+ New opened no menu');
	return menu;
}

async function chooseNew(root: HTMLElement, kind: NewKind): Promise<HTMLElement> {
	const menu = await openNewMenu(root);
	[...menu.querySelectorAll('button')]
		.find((item) => item.textContent?.trim() === kind.choice)
		?.click();
	await tick();
	const card = newCard(root, kind);
	if (!card) throw new Error(`${kind.choice} unfolded no card`);
	return card;
}

async function fillAndCreate(card: HTMLElement, value: string): Promise<void> {
	const input = card.querySelector<HTMLInputElement>('input');
	if (!input) throw new Error('no first field');
	input.value = value;
	input.dispatchEvent(new Event('input', { bubbles: true }));
	await tick();
	card.querySelector<HTMLButtonElement>('button[type="submit"]')?.click();
}

function refusal(status: number, detail: string): Response {
	return Response.json({ detail }, { status });
}

describe('1354_rule_14 915_C1 NewPlaceMenu', () => {
	it('stands as + New with its plus', async () => {
		const root = await render();

		expect(newButton(root).textContent).toContain('New');
		expect(newButton(root).querySelector('svg')).not.toBeNull();
	});

	it('opens New in Library offering Album and Playlist, each with its icon', async () => {
		const root = await render();

		const menu = await openNewMenu(root);

		expect(newButton(root).getAttribute('aria-expanded')).toBe('true');
		expect(menu.textContent).toContain('New in Library');
		const items = [...menu.querySelectorAll('button')];
		expect(items.map((item) => item.textContent?.trim())).toEqual(['Album', 'Playlist']);
		expect(items.every((item) => item.querySelector('svg') !== null)).toBe(true);
	});

	it.each([NEW_ALBUM, NEW_PLAYLIST])(
		'$choice closes the menu and unfolds its card beside + New, which stays pressed',
		async (kind) => {
			const root = await render();

			const card = await chooseNew(root, kind);

			expect(newMenu()).toBeNull();
			expect(root.contains(card)).toBe(true);
			expect(document.activeElement?.closest('label')?.textContent).toContain(kind.field);
			expect(newButton(root).classList.contains('pressed')).toBe(true);
		}
	);

	it.each([NEW_ALBUM, NEW_PLAYLIST])(
		'× folds the $choice card, creates nothing and hands focus back to + New',
		async (kind) => {
			const root = await render();
			const card = await chooseNew(root, kind);

			card.querySelector<HTMLButtonElement>(`[aria-label="${kind.close}"]`)?.click();
			await vi.waitFor(() => expect(document.activeElement).toBe(newButton(root)));

			expect(newCard(root, kind)).toBeNull();
			expect(newButton(root).classList.contains('pressed')).toBe(false);
			expect(fetchStub).not.toHaveBeenCalled();
		}
	);

	it.each([NEW_ALBUM, NEW_PLAYLIST])(
		'CREATE makes the $choice by its name, folds the card and opens its page',
		async (kind) => {
			const root = await render();
			const card = await chooseNew(root, kind);

			await fillAndCreate(card, kind.name);
			await vi.waitFor(() => expect(get(openCollection)).toEqual(kind.opened));

			const request = fetchStub.mock.calls.find(([path]) => path === kind.endpoint)?.[1];
			expect(request.method).toBe('POST');
			expect(JSON.parse(request.body)).toMatchObject({ title: kind.name });
			expect(newCard(root, kind)).toBeNull();
		}
	);

	it.each([NEW_ALBUM, NEW_PLAYLIST])(
		'915_E3 the $card card says only the latest refusal, and nothing once a create succeeds',
		async (kind) => {
			fetchStub
				.mockResolvedValueOnce(refusal(422, TAKEN))
				.mockResolvedValueOnce(refusal(500, 'Internal Server Error'));
			const root = await render();
			const card = await chooseNew(root, kind);
			const submit = () => card.querySelector<HTMLButtonElement>('button[type="submit"]')?.click();
			const toastMessages = () => get(toasts).map(({ message }) => message);

			await fillAndCreate(card, kind.name);
			await vi.waitFor(() => expect(toastMessages()).toEqual([TAKEN]));
			submit();
			await vi.waitFor(() => expect(toastMessages()).toEqual([kind.serverFailure]));
			submit();
			await vi.waitFor(() => expect(get(openCollection)).toEqual(kind.opened));

			expect(toastMessages()).toEqual([]);
		}
	);
});

describeBackClosesOverlay({
	name: '1354_rule_14 the New in Library menu',
	render,
	open: async (target) => {
		await openNewMenu(target);
	},
	isShown: () => newMenu() !== null,
	afterBack: () =>
		expect(document.activeElement?.getAttribute('aria-label')).toBe(LIBRARY_NEW_MENU_LABEL),
	closeWays: []
});

for (const kind of [NEW_ALBUM, NEW_PLAYLIST]) {
	describeBackClosesOverlay({
		name: `1354_rule_14 the ${kind.card} card`,
		render,
		open: async (target) => {
			await chooseNew(target, kind);
			await vi.waitFor(() => expect(standingHistoryEntry()?.layer).toBe('library-new-card'));
		},
		isShown: (target) => newCard(target, kind) !== null,
		afterBack: () => {
			expect(document.activeElement?.getAttribute('aria-label')).toBe(LIBRARY_NEW_MENU_LABEL);
			expect(fetchStub).not.toHaveBeenCalled();
		},
		closeWays: [
			{
				way: '×',
				close: (target) =>
					target.querySelector<HTMLButtonElement>(`[aria-label="${kind.close}"]`)?.click()
			}
		]
	});
}
