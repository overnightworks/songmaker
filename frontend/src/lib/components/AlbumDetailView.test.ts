import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { AlbumItem, PlaylistItem, SongItem } from '$lib/api/types';
import { ALBUM_ART_EMPTY_INITIALS, ALBUM_COVER_ALT_TYPE } from '$lib/constants';
import { albumList, selectedAlbumId, songList } from '$lib/stores/player';
import { openCollection } from '$lib/stores/collection';

const uploadAlbumCover = vi.fn();

vi.mock('$lib/api/client', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/api/client')>();
	return {
		...actual,
		uploadAlbumCover: (...args: unknown[]) => uploadAlbumCover(...args),
		deleteAlbumCover: vi.fn(),
		renameAlbum: vi.fn(),
		shareAlbum: vi.fn(),
		unshareAlbum: vi.fn(),
		deleteAlbum: vi.fn().mockResolvedValue(undefined),
		restoreAlbum: vi.fn()
	};
});
vi.mock('$lib/api/songs', () => ({
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false })
}));
vi.mock('$lib/stores/toast', () => ({
	addToast: vi.fn(),
	addUndoToast: vi.fn()
}));
vi.mock('$lib/stores/shares', () => ({
	refreshSharesAfterMutation: vi.fn()
}));
vi.mock('$lib/stores/playlists', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/stores/playlists')>();
	return {
		...actual,
		addAlbumToPlaylist: vi.fn()
	};
});

import AlbumDetailView from './AlbumDetailView.svelte';
import AlbumNode from './AlbumNode.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

function album(overrides: Partial<AlbumItem> = {}): AlbumItem {
	return {
		id: 'a-local',
		title: 'Night Drive',
		artist: 'Artist',
		subtitle: '',
		year: '',
		colors: {},
		song_count: 1,
		is_shared: false,
		share_slug: null,
		cover: null,
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

function song(): SongItem {
	return {
		id: 's-local',
		title: 'Local Only',
		album_id: 'a-local',
		album_title: 'Night Drive',
		artist: 'Artist',
		track_number: 1,
		vocal_language: 'en',
		lyrics: '',
		prompt: '',
		bpm: 120,
		audio_duration: 180,
		key_scale: 'Am',
		generation_params: null,
		version_count: 1,
		generation_count: 0,
		best_scores: null,
		best_rating: null,
		generations: [],
		created_at: '2026-01-01T00:00:00+00:00',
		is_shared: false,
		share_slug: null
	};
}

async function renderDetail(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(AlbumDetailView, { target }));
	await tick();
	return target;
}

beforeEach(() => {
	albumList.set([album()]);
	songList.set([song()]);
	selectedAlbumId.set('a-local');
	uploadAlbumCover.mockReset();
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	selectedAlbumId.set(null);
	albumList.set([]);
	songList.set([]);
	openCollection.set(null);
});

function requireElement<T extends Element>(root: ParentNode, selector: string): T {
	const element = root.querySelector<T>(selector);
	if (!element) throw new Error(`Expected ${selector} to be rendered`);
	return element;
}

async function openCollectionMenu(target: HTMLElement): Promise<HTMLElement> {
	requireElement<HTMLButtonElement>(target, '.collection-menu [aria-haspopup="dialog"]').click();
	await tick();
	return requireElement<HTMLElement>(document.body, '.menu-panel');
}

describe('AlbumDetailView header', () => {
	it('renders the albumId prop instead of the selected album', async () => {
		albumList.set([
			album({ id: 'a-local', title: 'Night Drive' }),
			album({ id: 'a-other', title: 'Other Night' })
		]);
		selectedAlbumId.set('a-other');
		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(mount(AlbumDetailView, { target, props: { albumId: 'a-local' } }));
		await tick();
		expect(target.textContent).toContain('Night Drive');
		expect(target.textContent).not.toContain('Other Night');
	});

	it('shows the cover, title, and a single Play action beside the menu', async () => {
		const target = await renderDetail();
		const header = requireElement(target, '.collection-header');
		expect(header.querySelector('.header-cover')).not.toBeNull();
		expect(header.querySelector('.header-title')?.textContent).toContain('Night Drive');
		expect(header.querySelector('.play-btn')?.textContent).toContain('Play');
		expect(header.querySelector('.collection-menu')).not.toBeNull();
	});

	it('names the object and lists Share, Cover, Rename, Add to playlist, Delete in the menu', async () => {
		const target = await renderDetail();
		const menu = await openCollectionMenu(target);
		expect(menu.querySelector('.menu-heading')?.textContent).toBe('Album · Night Drive');
		expect(menu.querySelector('.menu-row-label')?.textContent).toBe('Share album');
		const items = Array.from(menu.querySelectorAll('.menu-item')).map((el) =>
			el.textContent?.trim()
		);
		expect(items).toEqual(['Cover…', 'Rename', 'Add to playlist', 'Delete album']);
	});

	it('uploads a cover from the menu action', async () => {
		uploadAlbumCover.mockResolvedValue(
			album({
				cover: {
					card: '/api/albums/a-local/cover?variant=card&v=abc.jpg',
					detail: '/api/albums/a-local/cover?variant=detail&v=abc.jpg'
				}
			})
		);
		const target = await renderDetail();
		const menu = await openCollectionMenu(target);
		const input = target.querySelector('.cover-file-input');
		expect(input).toBeInstanceOf(HTMLInputElement);
		if (!(input instanceof HTMLInputElement)) return;
		requireElement<HTMLButtonElement>(menu, '.menu-item').click();
		const file = new File([new Uint8Array([1, 2, 3])], 'cover.jpg', { type: 'image/jpeg' });
		Object.defineProperty(input, 'files', { configurable: true, value: [file] });
		input.dispatchEvent(new Event('change', { bubbles: true }));
		await vi.waitFor(() => expect(uploadAlbumCover).toHaveBeenCalledTimes(1));
		await tick();
		expect(target.querySelector('img')?.getAttribute('alt')).toBe(
			`${ALBUM_COVER_ALT_TYPE} Night Drive`
		);
	});

	it('renames the album through the menu, reusing the EditableTitle interaction', async () => {
		const target = await renderDetail();
		const menu = await openCollectionMenu(target);
		const renameItem = Array.from(menu.querySelectorAll<HTMLButtonElement>('.menu-item')).find(
			(el) => el.textContent?.trim() === 'Rename'
		);
		renameItem?.click();
		await tick();
		expect(document.body.querySelector('.menu-panel')).toBeNull();
		expect(target.querySelector('.editable-title-input')).not.toBeNull();
	});

	it('clears the open collection on delete so the wall takes over instead of a blank panel', async () => {
		openCollection.set({ kind: 'album', id: 'a-local' });
		const target = await renderDetail();
		const menu = await openCollectionMenu(target);
		requireElement<HTMLButtonElement>(menu, '.menu-item.destructive').click();
		await tick();
		requireElement<HTMLButtonElement>(document.body, '.confirm-btn').click();
		await tick();
		await Promise.resolve();
		await tick();

		expect(get(openCollection)).toBeNull();
	});
});

describe('AlbumNode cover vs fallback', () => {
	function renderNode(item: AlbumItem): HTMLElement {
		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(
			mount(AlbumNode, {
				target,
				props: { album: item, selected: false, onselect: () => undefined }
			})
		);
		return target;
	}

	it('renders cover image with type and title alt', async () => {
		const target = renderNode(
			album({
				cover: {
					card: '/api/albums/a-local/cover?variant=card&v=abc.jpg',
					detail: '/api/albums/a-local/cover?variant=detail&v=abc.jpg'
				}
			})
		);
		await tick();
		const img = target.querySelector('img');
		expect(img?.getAttribute('src')).toContain('variant=card');
		expect(img?.getAttribute('alt')).toBe(`${ALBUM_COVER_ALT_TYPE} Night Drive`);
		expect(target.querySelector('.album-art-initials')).toBeNull();
	});

	it('falls back to initials when the cover image errors', async () => {
		const target = renderNode(
			album({
				cover: {
					card: '/api/albums/a-local/cover?variant=card&v=missing.jpg',
					detail: '/api/albums/a-local/cover?variant=detail&v=missing.jpg'
				}
			})
		);
		await tick();
		target.querySelector('img')?.dispatchEvent(new Event('error'));
		await tick();
		expect(target.querySelector('img')).toBeNull();
		expect(target.querySelector('.album-art-initials')?.getAttribute('aria-hidden')).toBe('true');
		expect(target.querySelector('.album-art-initials')?.textContent).toBe('ND');
	});

	it('uses primary color fallback when there is no cover', async () => {
		const target = renderNode(album({ colors: { primary: '#112233' } }));
		await tick();
		expect(target.querySelector('img')).toBeNull();
		const art = target.querySelector('.album-art');
		expect(art?.getAttribute('aria-hidden')).toBe('true');
		expect(art?.getAttribute('style')).toContain('rgb(17, 34, 51)');
	});

	it('uses empty initials when title and cover are missing', async () => {
		const target = renderNode(album({ title: '   ', colors: {} }));
		await tick();
		expect(target.querySelector('.album-art-initials')?.textContent).toBe(ALBUM_ART_EMPTY_INITIALS);
	});

	it('renders playlist tiles with the same card chrome and title initials', async () => {
		const target = document.createElement('div');
		document.body.append(target);
		const playlist: PlaylistItem = {
			id: 'p1',
			title: 'Night Drive',
			entry_count: 3,
			is_shared: false,
			share_slug: null,
			created_at: '2026-01-01T00:00:00+00:00'
		};
		mounted.push(
			mount(AlbumNode, {
				target,
				props: { playlist, selected: false, onselect: () => undefined }
			})
		);
		await tick();
		expect(target.querySelector('.album-card')?.getAttribute('data-collection-kind')).toBe(
			'playlist'
		);
		expect(target.querySelector('.album-art-initials')?.textContent).toBe('ND');
		expect(target.querySelector('.album-title')?.textContent).toBe('Night Drive');
		expect(target.querySelector('.album-count')?.textContent).toBe('3');
	});
});
