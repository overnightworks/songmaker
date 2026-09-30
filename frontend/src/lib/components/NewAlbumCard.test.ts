import { makeAlbum as album } from '$lib/test-utils/factories';
import { mount, tick, unmount } from 'svelte';
import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { goto } from '$app/navigation';
import { ApiError, NetworkError } from '$lib/api/fetch';
import { openCollection, resetCollectionForTests } from '$lib/stores/collection';
import { albumList } from '$lib/stores/libraryData';
import { addToast } from '$lib/stores/toast';
import { replaceHistoryEntry } from '$lib/test-utils/library-history';
import {
	captureUnhandledRejections,
	createButton,
	field,
	type
} from '$lib/test-utils/new-place-card';

const createAlbum = vi.fn();

vi.mock('$app/navigation', async () =>
	(await import('$lib/test-utils/app-navigation')).fakeAppNavigation()
);
vi.mock('$app/paths', () => ({ resolve: vi.fn((path: string) => path) }));
vi.mock('$lib/api/client', () => ({
	createAlbum: (...args: unknown[]) => createAlbum(...args),
	fetchAlbums: vi.fn(),
	fetchSongs: vi.fn().mockResolvedValue({ items: [], has_more: false })
}));
vi.mock('$lib/api/songs', () => ({ fetchSong: vi.fn(), fetchSongs: vi.fn() }));
vi.mock('$lib/stores/toast', () => ({ addToast: vi.fn() }));

import NewAlbumCard from './NewAlbumCard.svelte';

const NIGHT_DRIVE = album({ id: 'a-night', title: 'Night Drive', artist: '' });

let mounted: ReturnType<typeof mount> | undefined;
let cancels: number;
let creates: number;
let restoreUnhandledRejections: (() => void) | undefined;

beforeEach(() => {
	createAlbum.mockReset().mockResolvedValue(NIGHT_DRIVE);
	vi.mocked(addToast).mockClear();
	albumList.set([]);
	resetCollectionForTests();
	replaceHistoryEntry('/');
	cancels = 0;
	creates = 0;
});

afterEach(async () => {
	restoreUnhandledRejections?.();
	restoreUnhandledRejections = undefined;
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

async function render(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(NewAlbumCard, {
		target,
		props: { oncancel: () => (cancels += 1), oncreated: () => (creates += 1) }
	});
	await tick();
	return target;
}

async function createSettled(): Promise<void> {
	await vi.waitFor(() => expect(createAlbum).toHaveBeenCalled());
	await tick();
	await tick();
}

describe('NewAlbumCard', () => {
	it('names itself New album and puts the cursor in Title', async () => {
		const root = await render();

		expect(root.querySelector('[aria-label="New album"]')).not.toBeNull();
		expect(document.activeElement).toBe(field(root, 'Title'));
		expect(field(root, 'Artist').required).toBe(false);
		expect(field(root, 'Artist').placeholder).toBe('Artist');
	});

	it.each(['Title', 'Artist'])('%s takes no more than the server keeps', async (label) => {
		const root = await render();

		expect(field(root, label).maxLength).toBe(200);
	});

	it.each([
		{ case: 'no title', title: '' },
		{ case: 'a title of spaces', title: '   ' }
	])('offers no Create for $case', async ({ title }) => {
		const root = await render();

		type(field(root, 'Title'), title);

		expect(createButton(root).disabled).toBe(true);
	});

	it('creates the album with its title and optional artist, lists it and opens its page', async () => {
		const root = await render();
		type(field(root, 'Title'), '  Night Drive ');
		type(field(root, 'Artist'), ' Lichtwechsel ');

		createButton(root).click();
		await createSettled();

		expect(createAlbum).toHaveBeenCalledWith('Night Drive', 'Lichtwechsel');
		expect(get(albumList).map((listed) => listed.id)).toEqual(['a-night']);
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a-night' });
		expect(creates).toBe(1);
	});

	it('creates on Enter in the title field', async () => {
		const root = await render();
		type(field(root, 'Title'), 'Night Drive');

		field(root, 'Title').form?.requestSubmit();
		await createSettled();

		expect(createAlbum).toHaveBeenCalledWith('Night Drive', '');
	});

	it.each([
		{
			case: 'the server refuses it',
			refusal: new ApiError(422, 'Validation error on: body.title', '/api/albums'),
			reason: 'The album could not be created. Try again.'
		},
		{
			case: 'the network is gone',
			refusal: new NetworkError('/api/albums', new TypeError('Failed to fetch')),
			reason: "You're offline, so nothing was created. Try again once you're back online."
		}
	])('keeps the card and what was typed when $case, and says why readably', async ({
		refusal,
		reason
	}) => {
		createAlbum.mockRejectedValue(refusal);
		const root = await render();
		type(field(root, 'Title'), 'Night Drive');

		createButton(root).click();
		await createSettled();

		expect(creates).toBe(0);
		expect(field(root, 'Title').value).toBe('Night Drive');
		expect(createButton(root).disabled).toBe(false);
		expect(get(openCollection)).toBeNull();
		expect(addToast).toHaveBeenCalledWith(reason, 'error');
	});

	it('keeps the created album listed and says nothing failed when only opening its page fails', async () => {
		const openFailure = new Error('navigation aborted');
		vi.mocked(goto).mockRejectedValueOnce(openFailure);
		const { escaped, restore } = captureUnhandledRejections();
		restoreUnhandledRejections = restore;
		const root = await render();
		type(field(root, 'Title'), 'Night Drive');

		createButton(root).click();
		await createSettled();

		await vi.waitFor(() => expect(escaped).toContain(openFailure));
		expect(get(albumList).map((listed) => listed.id)).toEqual(['a-night']);
		expect(addToast).not.toHaveBeenCalled();
	});

	it('× closes it and creates nothing', async () => {
		const root = await render();
		type(field(root, 'Title'), 'Night Drive');

		root.querySelector<HTMLButtonElement>('[aria-label="Close new album"]')?.click();
		await tick();

		expect(cancels).toBe(1);
		expect(createAlbum).not.toHaveBeenCalled();
	});
});
