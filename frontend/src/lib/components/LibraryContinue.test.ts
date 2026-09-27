import { mount, tick, unmount } from 'svelte';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { LibraryContinueItem } from '$lib/api/library';
import { libraryContinueCollapsed } from '$lib/stores/ui';

const fetchLibraryContinue = vi.fn();
const openAlbum = vi.fn();
const openPlaylist = vi.fn();
const selectSong = vi.fn();

vi.mock('$lib/api/library', () => ({
	fetchLibraryContinue: (...args: unknown[]) => fetchLibraryContinue(...args)
}));
vi.mock('$lib/stores/navigation', () => ({
	openAlbum: (...args: unknown[]) => openAlbum(...args),
	openPlaylist: (...args: unknown[]) => openPlaylist(...args),
	selectSong: (...args: unknown[]) => selectSong(...args)
}));

import LibraryContinue from './LibraryContinue.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

function item(overrides: Partial<LibraryContinueItem> = {}): LibraryContinueItem {
	return {
		type: 'album',
		id: 'album-1',
		title: 'Open Windows',
		cover: { card: '/covers/open-windows.jpg', detail: '/covers/open-windows-detail.jpg' },
		album_covers: [],
		song_id: null,
		song_title: null,
		activity_at: '2026-09-27T03:47:00Z',
		...overrides
	};
}

beforeAll(() => {
	vi.stubEnv('TZ', 'Europe/Berlin');
	vi.useFakeTimers({ toFake: ['Date'] });
	vi.setSystemTime(new Date('2026-09-27T10:00:00Z'));
});

afterAll(() => {
	vi.useRealTimers();
	vi.unstubAllEnvs();
});

beforeEach(() => {
	fetchLibraryContinue.mockReset();
	openAlbum.mockReset().mockResolvedValue(undefined);
	openPlaylist.mockReset().mockResolvedValue(undefined);
	selectSong.mockReset().mockResolvedValue(undefined);
	localStorage.clear();
	libraryContinueCollapsed.set(false);
});

afterEach(async () => {
	Reflect.deleteProperty(document, 'visibilityState');
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
});

async function render(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(LibraryContinue, { target }));
	await tick();
	return target;
}

function continueResponse(items: LibraryContinueItem[]): { items: LibraryContinueItem[] } {
	return { items };
}

function dispatchVisibility(state: DocumentVisibilityState): void {
	Object.defineProperty(document, 'visibilityState', { configurable: true, value: state });
	document.dispatchEvent(new Event('visibilitychange'));
}

function entryLabels(target: HTMLElement): Array<string | null> {
	return Array.from(target.querySelectorAll('.continue-item')).map((entry) =>
		entry.getAttribute('aria-label')
	);
}

async function settle(): Promise<void> {
	await Promise.resolve();
	await Promise.resolve();
	await tick();
}

describe('LibraryContinue', () => {
	it('renders at most six places, each with its cover, title, song and when', async () => {
		fetchLibraryContinue.mockResolvedValue(
			continueResponse([
				item({
					id: 'vernissage',
					title: 'Vernissage',
					song_id: 'song-1',
					song_title: 'Kuratorenherz'
				}),
				...Array.from({ length: 6 }, (_, index) =>
					item({ id: `album-${index + 2}`, title: `Album ${index + 2}` })
				)
			])
		);
		const target = await render();
		await settle();

		const tiles = target.querySelectorAll('.continue-item');
		expect(tiles).toHaveLength(6);
		expect(tiles[0].querySelector('img')?.getAttribute('src')).toBe('/covers/open-windows.jpg');
		expect(tiles[0].querySelector('.tile-title')?.textContent).toBe('Vernissage');
		expect(tiles[0].querySelector('.tile-subtitle')?.textContent).toBe('Kuratorenherz');
		expect(tiles[0].querySelector('time')?.textContent).toBe('today 05:47');
		expect(tiles[0].querySelector('time')?.getAttribute('datetime')).toBe('2026-09-27T03:47:00Z');
		expect(tiles[1].querySelector('.tile-subtitle')?.textContent).toBe('');
		expect(target.querySelector('.continue-tag')).toBeNull();
	});

	it("shows a playlist's album covers as its mosaic unless it has its own cover", async () => {
		const albumCover = { card: '/covers/anfield.jpg', detail: '/covers/anfield-detail.jpg' };
		fetchLibraryContinue.mockResolvedValue(
			continueResponse([
				item({ type: 'playlist', id: 'night-drive', cover: null, album_covers: [albumCover] }),
				item({ type: 'playlist', id: 'late-shift', album_covers: [albumCover] })
			])
		);
		const target = await render();
		await settle();

		const [mosaic, uploaded] = target.querySelectorAll('.continue-item');
		expect(mosaic.querySelector('.playlist-cover img')?.getAttribute('src')).toBe(
			'/covers/anfield.jpg'
		);
		expect(uploaded.querySelector('.playlist-cover')).toBeNull();
		expect(uploaded.querySelector('img')?.getAttribute('src')).toBe('/covers/open-windows.jpg');
	});

	it('continues on the song a place names, else opens the place itself', async () => {
		fetchLibraryContinue.mockResolvedValue(
			continueResponse([
				item({ id: 'vernissage', song_id: 'song-1', song_title: 'Kuratorenherz' }),
				item({
					type: 'playlist',
					id: 'night-drive',
					title: 'Night drive',
					song_id: 'song-2',
					song_title: 'Lichtwechsel'
				}),
				item({ id: 'empty-album', title: 'Empty' }),
				item({ type: 'playlist', id: 'empty-playlist', title: 'Empty list' })
			])
		);
		const target = await render();
		await settle();

		expect(entryLabels(target)).toEqual([
			'Open song Kuratorenherz in album Open Windows',
			'Open song Lichtwechsel in playlist Night drive',
			'Open album Empty',
			'Open playlist Empty list'
		]);
		for (const entry of target.querySelectorAll<HTMLButtonElement>('.continue-item')) {
			entry.click();
		}

		expect(selectSong.mock.calls).toEqual([['song-1'], ['song-2']]);
		expect(openAlbum).toHaveBeenCalledExactlyOnceWith('empty-album');
		expect(openPlaylist).toHaveBeenCalledExactlyOnceWith('empty-playlist');
	});

	it('names loading and empty states honestly', async () => {
		let resolveRequest: ((value: { items: LibraryContinueItem[] }) => void) | undefined;
		fetchLibraryContinue.mockImplementationOnce(
			() => new Promise((resolve) => (resolveRequest = resolve))
		);
		const target = await render();
		expect(target.textContent).toContain('Loading continue items…');

		resolveRequest?.(continueResponse([]));
		await settle();
		expect(target.textContent).toContain('Nothing to continue yet.');
	});

	it('names an error and retries it', async () => {
		fetchLibraryContinue.mockRejectedValueOnce(new Error('offline'));
		const target = await render();
		await settle();
		expect(target.textContent).toContain('Could not load continue items.');

		fetchLibraryContinue.mockResolvedValueOnce(continueResponse([item()]));
		target.querySelector<HTMLButtonElement>('.continue-retry')?.click();
		await settle();
		expect(target.querySelectorAll('.continue-item')).toHaveLength(1);
	});

	it('keeps the list it showed when a refresh on return to the foreground fails', async () => {
		fetchLibraryContinue
			.mockResolvedValueOnce(continueResponse([item({ id: 'yesterday', title: 'Yesterday' })]))
			.mockRejectedValueOnce(new Error('offline'))
			.mockResolvedValueOnce(continueResponse([item({ id: 'vernissage', title: 'Vernissage' })]));
		const target = await render();
		await settle();

		dispatchVisibility('visible');
		await settle();
		expect(fetchLibraryContinue).toHaveBeenCalledTimes(2);
		expect(entryLabels(target)).toEqual(['Open album Yesterday']);
		expect(target.querySelector('[role="alert"]')).toBeNull();
		expect(target.querySelector('.continue-retry')).toBeNull();

		dispatchVisibility('visible');
		await settle();
		expect(entryLabels(target)).toEqual(['Open album Vernissage']);
	});

	it('fetches Continue fresh every time Home is shown', async () => {
		fetchLibraryContinue
			.mockResolvedValueOnce(continueResponse([item({ id: 'yesterday', title: 'Yesterday' })]))
			.mockResolvedValueOnce(continueResponse([item({ id: 'vernissage', title: 'Vernissage' })]));
		const first = await render();
		await settle();
		expect(entryLabels(first)).toEqual(['Open album Yesterday']);
		await unmount(mounted.splice(0)[0]);

		const second = await render();
		await settle();

		expect(entryLabels(second)).toEqual(['Open album Vernissage']);
	});

	it('refreshes Continue when the app returns to the foreground on Home', async () => {
		fetchLibraryContinue
			.mockResolvedValueOnce(continueResponse([item({ id: 'yesterday', title: 'Yesterday' })]))
			.mockResolvedValueOnce(
				continueResponse([
					item({ id: 'vernissage', title: 'Vernissage' }),
					item({ id: 'yesterday', title: 'Yesterday' })
				])
			);
		const target = await render();
		await settle();

		dispatchVisibility('hidden');
		await settle();
		expect(fetchLibraryContinue).toHaveBeenCalledOnce();
		expect(entryLabels(target)).toEqual(['Open album Yesterday']);

		dispatchVisibility('visible');
		await settle();

		expect(entryLabels(target)).toEqual(['Open album Vernissage', 'Open album Yesterday']);
	});

	it('asks the server once per return even when the foreground signal repeats', async () => {
		let resolveRefresh: ((value: { items: LibraryContinueItem[] }) => void) | undefined;
		fetchLibraryContinue
			.mockResolvedValueOnce(continueResponse([item()]))
			.mockImplementationOnce(() => new Promise((resolve) => (resolveRefresh = resolve)));
		const target = await render();
		await settle();

		dispatchVisibility('visible');
		dispatchVisibility('visible');
		target.querySelector<HTMLButtonElement>('.continue-toggle')?.click();
		target.querySelector<HTMLButtonElement>('.continue-toggle')?.click();
		await settle();

		expect(fetchLibraryContinue).toHaveBeenCalledTimes(2);
		expect(entryLabels(target)).toEqual(['Open album Open Windows']);
		resolveRefresh?.(continueResponse([]));
		await settle();
		expect(target.textContent).toContain('Nothing to continue yet.');
	});

	it('stops listening for the foreground once Home is left', async () => {
		fetchLibraryContinue.mockResolvedValue(continueResponse([item()]));
		await render();
		await settle();
		await unmount(mounted.splice(0)[0]);

		dispatchVisibility('visible');
		await settle();

		expect(fetchLibraryContinue).toHaveBeenCalledOnce();
	});

	it('collapses and restores the browser preference', async () => {
		fetchLibraryContinue.mockResolvedValue(continueResponse([item()]));
		const target = await render();
		await settle();

		const toggle = target.querySelector<HTMLButtonElement>('.continue-toggle');
		toggle?.click();
		await tick();
		expect(get(libraryContinueCollapsed)).toBe(true);
		expect(localStorage.getItem('songmaker.library-continue-collapsed')).toBe('true');
		expect(toggle?.getAttribute('aria-expanded')).toBe('false');
	});
});
