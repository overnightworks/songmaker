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

import LibraryContinue, { clearLibraryContinueCache } from './LibraryContinue.svelte';

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
	clearLibraryContinueCache();
	fetchLibraryContinue.mockReset();
	openAlbum.mockReset().mockResolvedValue(undefined);
	selectSong.mockReset().mockResolvedValue(undefined);
	localStorage.clear();
	libraryContinueCollapsed.set(false);
});

afterEach(async () => {
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

async function settle(): Promise<void> {
	await Promise.resolve();
	await Promise.resolve();
	await tick();
}

describe('LibraryContinue', () => {
	it('shares one request across wall remounts in the same document', async () => {
		fetchLibraryContinue.mockResolvedValue({ items: [item()] });
		await render();
		await settle();
		const firstMount = mounted.pop();
		if (!firstMount) throw new Error('Expected the first Continue mount');
		await unmount(firstMount);

		const target = await render();
		await settle();

		expect(fetchLibraryContinue).toHaveBeenCalledOnce();
		expect(target.querySelectorAll('.continue-item')).toHaveLength(1);
	});

	it('renders at most six tagged items with their cover and title', async () => {
		fetchLibraryContinue.mockResolvedValue({
			items: [
				item({ type: 'song', id: 'song-1', title: 'Stadion', album_title: 'Anfield' }),
				...Array.from({ length: 6 }, (_, index) =>
					item({ id: `album-${index + 2}`, title: `Album ${index + 2}` })
				)
			]
		});
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
		fetchLibraryContinue.mockResolvedValue({
			items: [
				item(),
				item({ type: 'song', id: 'song-1', title: 'Stadion', album_title: 'Anfield' })
			]
		});
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

		resolveRequest?.({ items: [] });
		await settle();
		expect(target.textContent).toContain('Nothing to continue yet.');
	});

	it('names an error and retries it', async () => {
		fetchLibraryContinue.mockRejectedValueOnce(new Error('offline'));
		const target = await render();
		await settle();
		expect(target.textContent).toContain('Could not load continue items.');

		fetchLibraryContinue.mockResolvedValueOnce({ items: [item()] });
		target.querySelector<HTMLButtonElement>('.continue-retry')?.click();
		await settle();
		expect(target.querySelectorAll('.continue-item')).toHaveLength(1);
	});

	it('collapses and restores the browser preference', async () => {
		fetchLibraryContinue.mockResolvedValue({ items: [item()] });
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
