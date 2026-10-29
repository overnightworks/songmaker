import { makeAlbum as album, makeSong as song } from '#lib/test-utils/factories.ts';
import { mount, tick, unmount } from 'svelte';
import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError, NetworkError } from '#lib/api/fetch.ts';
import { resetCollectionForTests } from '#lib/stores/collection.ts';
import { detailTab } from '#lib/stores/libraryContext.ts';
import { songList } from '#lib/stores/libraryData.ts';
import { selectedSongId } from '#lib/stores/player.ts';
import { toasts } from '#lib/stores/toast.ts';
import { replaceHistoryEntry } from '#lib/test-utils/library-history.ts';
import { createButton, createSettled, field, type } from '#lib/test-utils/new-place-card.ts';

const createSong = vi.fn();

vi.mock('$app/navigation', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation()
);
vi.mock('$app/paths', () => ({ resolve: vi.fn((path: string) => path) }));
vi.mock('#lib/api/client.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/client.ts')>()),
	createSong: (...args: unknown[]) => createSong(...args)
}));

import NewSongCard from './NewSongCard.svelte';

const NIGHTDRIVE = album({ id: 'a-night', title: 'Nightdrive' });
const TIDEWATER = song({ id: 's-tide', title: 'Tidewater', album_id: 'a-night' });

let mounted: ReturnType<typeof mount> | undefined;
let cancels: number;
let creates: number;

beforeEach(() => {
	createSong.mockReset().mockResolvedValue(TIDEWATER);
	songList.set([]);
	selectedSongId.set(null);
	toasts.set([]);
	resetCollectionForTests();
	replaceHistoryEntry('/');
	cancels = 0;
	creates = 0;
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

async function render(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(NewSongCard, {
		target,
		props: {
			album: NIGHTDRIVE,
			oncancel: () => (cancels += 1),
			oncreated: () => (creates += 1)
		}
	});
	await tick();
	return target;
}

const SONG_NOT_CREATED = 'The song could not be created. Try again.';

function toastMessages(): string[] {
	return get(toasts).map((toast) => toast.message);
}

function failOnce(status: number, detail: string): void {
	createSong.mockRejectedValueOnce(new ApiError(status, detail, '/api/songs'));
}

describe('NewSongCard', () => {
	it('names the album it adds to, with one Title field that holds the cursor and no more than the server keeps', async () => {
		const root = await render();

		expect(root.querySelector('[aria-label="New song in Nightdrive"]')).not.toBeNull();
		expect(root.querySelectorAll('input')).toHaveLength(1);
		expect(document.activeElement).toBe(field(root, 'Title'));
		expect(field(root, 'Title').maxLength).toBe(200);
	});

	it.each(['', '   '])('offers no Create for the title %j', async (title) => {
		const root = await render();

		type(field(root, 'Title'), title);

		expect(createButton(root).disabled).toBe(true);
	});

	it('creates the song in this album by its title, lists it and opens it on Write', async () => {
		const root = await render();
		type(field(root, 'Title'), '  Tidewater ');

		createButton(root).click();
		await createSettled(createSong);

		expect(createSong).toHaveBeenCalledWith({ title: 'Tidewater', album_id: 'a-night' });
		expect(get(songList).map((listed) => listed.id)).toEqual(['s-tide']);
		await vi.waitFor(() => expect(get(selectedSongId)).toBe('s-tide'));
		expect(get(detailTab)).toBe('edit');
		expect(creates).toBe(1);
	});

	it.each([
		{
			case: 'the server refuses it and says why',
			failure: new ApiError(422, 'That title is taken', '/api/songs'),
			toast: 'That title is taken'
		},
		{
			case: 'the server refuses it without a reason',
			failure: new ApiError(404, '', '/api/songs'),
			toast: 'The song could not be created.'
		},
		{
			case: 'the server fails',
			failure: new ApiError(500, 'Internal Server Error', '/api/songs'),
			toast: SONG_NOT_CREATED
		},
		{
			case: 'the server rate-limits it',
			failure: new ApiError(429, 'Too many requests', '/api/songs', 30),
			toast: SONG_NOT_CREATED
		},
		{
			case: 'the network is gone',
			failure: new NetworkError('/api/songs', new TypeError('Failed to fetch')),
			toast: "You're offline, so nothing was created. Try again once you're back online."
		}
	])(
		'915_E2 keeps the card and the title when $case, and says why in words that fit',
		async ({ failure, toast }) => {
			createSong.mockRejectedValueOnce(failure);
			const root = await render();
			type(field(root, 'Title'), 'Tidewater');

			createButton(root).click();
			await createSettled(createSong);

			expect(creates).toBe(0);
			expect(field(root, 'Title').value).toBe('Tidewater');
			expect(createButton(root).disabled).toBe(false);
			expect(get(songList)).toEqual([]);
			expect(toastMessages()).toEqual([toast]);
		}
	);

	it('915_E3 says only the latest failure when the create is refused again', async () => {
		failOnce(422, 'That title is taken');
		failOnce(422, 'That title is too long');
		const root = await render();
		type(field(root, 'Title'), 'Tidewater');
		createButton(root).click();
		await vi.waitFor(() => expect(toastMessages()).toEqual(['That title is taken']));

		createButton(root).click();

		await vi.waitFor(() => expect(toastMessages()).toEqual(['That title is too long']));
	});

	it('915_E3 clears the failure it said once the song is made after all', async () => {
		failOnce(500, 'Internal Server Error');
		const root = await render();
		type(field(root, 'Title'), 'Tidewater');
		createButton(root).click();
		await vi.waitFor(() => expect(toastMessages()).toContain(SONG_NOT_CREATED));

		createButton(root).click();
		await vi.waitFor(() => expect(creates).toBe(1));

		expect(toastMessages()).not.toContain(SONG_NOT_CREATED);
	});

	it('× closes it and creates nothing', async () => {
		const root = await render();
		type(field(root, 'Title'), 'Tidewater');

		root.querySelector<HTMLButtonElement>('[aria-label="Close new song"]')?.click();
		await tick();

		expect(cancels).toBe(1);
		expect(createSong).not.toHaveBeenCalled();
	});
});
