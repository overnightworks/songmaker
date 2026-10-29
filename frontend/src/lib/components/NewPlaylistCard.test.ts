import { makePlaylist as playlist } from '#lib/test-utils/factories.ts';
import { mount, tick, unmount } from 'svelte';
import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { goto } from '$app/navigation';
import { ApiError, NetworkError } from '#lib/api/fetch.ts';
import { openCollection, resetCollectionForTests } from '#lib/stores/collection.ts';
import { playlistList, playlistLoad, resetPlaylistsForTests } from '#lib/stores/playlists.ts';
import { addToast } from '#lib/stores/toast.ts';
import { replaceHistoryEntry } from '#lib/test-utils/library-history.ts';
import {
	captureUnhandledRejections,
	createButton,
	createSettled,
	field,
	type
} from '#lib/test-utils/new-place-card.ts';

const createPlaylist = vi.fn();

vi.mock('$app/navigation', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation()
);
vi.mock('$app/paths', () => ({ resolve: vi.fn((path: string) => path) }));
vi.mock('#lib/api/client.ts', () => ({
	createPlaylist: (...args: unknown[]) => createPlaylist(...args),
	fetchPlaylists: vi.fn().mockResolvedValue([]),
	fetchPlaylist: vi.fn().mockResolvedValue({ ...ROAD_TRIP, entries: [] })
}));
vi.mock('#lib/api/songs.ts', () => ({ fetchSong: vi.fn(), fetchSongs: vi.fn() }));
vi.mock('#lib/stores/toast.ts', () => ({ addToast: vi.fn(), dismissToast: vi.fn() }));

import NewPlaylistCard from './NewPlaylistCard.svelte';

const ROAD_TRIP = vi.hoisted(() => ({
	id: 'p-road',
	title: 'Road Trip',
	slug: 'road-trip',
	entry_count: 0,
	is_shared: false,
	album_covers: [],
	created_at: '2026-09-30T10:00:00+00:00'
}));

let mounted: ReturnType<typeof mount> | undefined;
let cancels: number;
let creates: number;
let restoreUnhandledRejections: (() => void) | undefined;

beforeEach(() => {
	createPlaylist.mockReset().mockResolvedValue(playlist(ROAD_TRIP));
	vi.mocked(addToast).mockClear();
	resetPlaylistsForTests();
	playlistList.set([]);
	playlistLoad.set({ status: 'ready', error: null });
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
	mounted = mount(NewPlaylistCard, {
		target,
		props: { oncancel: () => (cancels += 1), oncreated: () => (creates += 1) }
	});
	await tick();
	return target;
}

function listedIds(): string[] {
	return get(playlistList).map((listed) => listed.id);
}

describe('NewPlaylistCard', () => {
	it('names itself New playlist with one Name field that holds the cursor and no more than the server keeps', async () => {
		const root = await render();

		expect(root.querySelector('[aria-label="New playlist"]')).not.toBeNull();
		expect(root.querySelectorAll('input')).toHaveLength(1);
		expect(document.activeElement).toBe(field(root, 'Name'));
		expect(field(root, 'Name').maxLength).toBe(200);
	});

	it.each(['', '   '])('offers no Create for the name %j', async (name) => {
		const root = await render();

		type(field(root, 'Name'), name);

		expect(createButton(root).disabled).toBe(true);
	});

	it('creates the playlist by its name, lists it and opens it', async () => {
		const root = await render();
		type(field(root, 'Name'), '  Road Trip ');

		createButton(root).click();
		await createSettled(createPlaylist);

		expect(createPlaylist).toHaveBeenCalledWith('Road Trip');
		expect(listedIds()).toEqual(['p-road']);
		await vi.waitFor(() => expect(get(openCollection)).toEqual({ kind: 'playlist', id: 'p-road' }));
		expect(creates).toBe(1);
	});

	it.each([
		{
			case: 'the server refuses it and says why',
			refusal: new ApiError(422, 'That name is taken', '/api/playlists'),
			reason: 'That name is taken'
		},
		{
			case: 'the server refuses it without a reason',
			refusal: new ApiError(422, '', '/api/playlists'),
			reason: 'The playlist could not be created.'
		},
		{
			case: 'the server fails',
			refusal: new ApiError(500, 'Internal Server Error', '/api/playlists'),
			reason: 'The playlist could not be created. Try again.'
		},
		{
			case: 'the server rate-limits it',
			refusal: new ApiError(429, 'Too many requests', '/api/playlists', 30),
			reason: 'The playlist could not be created. Try again.'
		},
		{
			case: 'the network is gone',
			refusal: new NetworkError('/api/playlists', new TypeError('Failed to fetch')),
			reason: "You're offline, so nothing was created. Try again once you're back online."
		}
	])(
		'915_E2 keeps the card and the name when $case, and says why in words that fit',
		async ({ refusal, reason }) => {
			createPlaylist.mockRejectedValue(refusal);
			const root = await render();
			type(field(root, 'Name'), 'Road Trip');

			createButton(root).click();
			await createSettled(createPlaylist);

			expect(creates).toBe(0);
			expect(field(root, 'Name').value).toBe('Road Trip');
			expect(createButton(root).disabled).toBe(false);
			expect(listedIds()).toEqual([]);
			expect(addToast).toHaveBeenCalledWith(reason, 'error');
		}
	);

	it('keeps the created playlist listed and says nothing failed when only opening it fails', async () => {
		const openFailure = new Error('navigation aborted');
		vi.mocked(goto).mockRejectedValueOnce(openFailure);
		const { escaped, restore } = captureUnhandledRejections();
		restoreUnhandledRejections = restore;
		const root = await render();
		type(field(root, 'Name'), 'Road Trip');

		createButton(root).click();
		await createSettled(createPlaylist);

		await vi.waitFor(() => expect(escaped).toContain(openFailure));
		expect(listedIds()).toEqual(['p-road']);
		expect(addToast).not.toHaveBeenCalled();
	});

	it('× closes it and creates nothing', async () => {
		const root = await render();
		type(field(root, 'Name'), 'Road Trip');

		root.querySelector<HTMLButtonElement>('[aria-label="Close new playlist"]')?.click();
		await tick();

		expect(cancels).toBe(1);
		expect(createPlaylist).not.toHaveBeenCalled();
	});
});
