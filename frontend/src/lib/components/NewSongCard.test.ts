import { makeAlbum as album, makeSong as song } from '$lib/test-utils/factories';
import { mount, tick, unmount } from 'svelte';
import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '$lib/api/fetch';
import { resetCollectionForTests } from '$lib/stores/collection';
import { detailTab } from '$lib/stores/libraryContext';
import { songList } from '$lib/stores/libraryData';
import { selectedSongId } from '$lib/stores/player';
import { toasts } from '$lib/stores/toast';
import { replaceHistoryEntry } from '$lib/test-utils/library-history';
import { createButton, createSettled, field, type } from '$lib/test-utils/new-place-card';

const createSong = vi.fn();

vi.mock('$app/navigation', async () =>
	(await import('$lib/test-utils/app-navigation')).fakeAppNavigation()
);
vi.mock('$app/paths', () => ({ resolve: vi.fn((path: string) => path) }));
vi.mock('$lib/api/client', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/client')>()),
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

function refuseOnce(): void {
	createSong.mockRejectedValueOnce(
		new ApiError(422, 'Validation error on: body.title', '/api/songs')
	);
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

	it('keeps the card and the title when the server refuses, and says why readably', async () => {
		refuseOnce();
		const root = await render();
		type(field(root, 'Title'), 'Tidewater');

		createButton(root).click();
		await createSettled(createSong);

		expect(creates).toBe(0);
		expect(field(root, 'Title').value).toBe('Tidewater');
		expect(createButton(root).disabled).toBe(false);
		expect(get(songList)).toEqual([]);
		expect(toastMessages()).toEqual([SONG_NOT_CREATED]);
	});

	it('clears the failure it said once the song is made after all', async () => {
		refuseOnce();
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
