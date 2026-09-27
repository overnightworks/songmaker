import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { LibraryContinueItem } from '$lib/api/library';
import { libraryContinueCollapsed } from '$lib/stores/ui';

const fetchLibraryContinue = vi.fn();
const openAlbum = vi.fn();
const selectSong = vi.fn();

vi.mock('$lib/api/library', () => ({
	fetchLibraryContinue: (...args: unknown[]) => fetchLibraryContinue(...args)
}));
vi.mock('$lib/stores/navigation', () => ({
	openAlbum: (...args: unknown[]) => openAlbum(...args),
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
		...overrides
	};
}

beforeEach(() => {
	fetchLibraryContinue.mockReset();
	openAlbum.mockReset().mockResolvedValue(undefined);
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

function setVisibility(state: DocumentVisibilityState): void {
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
	it('renders at most six tagged items with their cover and title', async () => {
		fetchLibraryContinue.mockResolvedValue(
			continueResponse([
				item({ type: 'song', id: 'song-1', title: 'Stadion', album_title: 'Anfield' }),
				...Array.from({ length: 6 }, (_, index) =>
					item({ id: `album-${index + 2}`, title: `Album ${index + 2}` })
				)
			])
		);
		const target = await render();
		await settle();

		expect(target.querySelectorAll('.continue-item')).toHaveLength(6);
		expect(target.querySelector('.continue-item img')?.getAttribute('src')).toBe(
			'/covers/open-windows.jpg'
		);
		expect(target.textContent).toContain('Stadion');
		expect(
			Array.from(target.querySelectorAll('.continue-tag')).map((tag) => tag.textContent)
		).toEqual(['Song', 'Album', 'Album', 'Album', 'Album', 'Album']);
	});

	it('opens albums and songs through the navigation store', async () => {
		fetchLibraryContinue.mockResolvedValue(
			continueResponse([
				item(),
				item({ type: 'song', id: 'song-1', title: 'Stadion', album_title: 'Anfield' })
			])
		);
		const target = await render();
		await settle();

		const entries = target.querySelectorAll<HTMLButtonElement>('.continue-item');
		entries[0].click();
		entries[1].click();

		expect(openAlbum).toHaveBeenCalledWith('album-1');
		expect(selectSong).toHaveBeenCalledWith('song-1');
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

		setVisibility('hidden');
		await settle();
		expect(fetchLibraryContinue).toHaveBeenCalledOnce();
		expect(entryLabels(target)).toEqual(['Open album Yesterday']);

		setVisibility('visible');
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

		setVisibility('visible');
		setVisibility('visible');
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

		setVisibility('visible');
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
