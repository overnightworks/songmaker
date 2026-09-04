import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import { openCollection, setOpenCollection } from '$lib/stores/collection';
import { librarySurface, resetLibraryContextForTests } from '$lib/stores/libraryContext';
import { albumList } from '$lib/stores/libraryData';
import { playlistList, resetPlaylists, selectedPlaylistDetail } from '$lib/stores/playlists';
import {
	buildAlbum as album,
	buildPlaylist as playlist,
	buildPlaylistDetail as detail,
	createComponentMount,
	requireElement
} from './rail-test-fixtures';

vi.mock('$app/navigation', async () => (await import('./rail-test-fixtures')).railNavigationMock());
vi.mock('$app/paths', async () => (await import('./rail-test-fixtures')).railPathsMock());
vi.mock('$lib/api/library', async () =>
	(await import('./rail-test-fixtures')).railLibraryApiMock()
);
vi.mock('$lib/api/albums', async () => (await import('./rail-test-fixtures')).railAlbumsApiMock());
vi.mock('$lib/api/songs', async () => (await import('./rail-test-fixtures')).railSongsApiMock());
vi.mock('$lib/api/client', async () => (await import('./rail-test-fixtures')).railClientApiMock());

import Rail from './Rail.svelte';

const onlogout = vi.fn();
const { render, cleanup } = createComponentMount(Rail, { username: 'felix', onlogout });

function findButtonByText(root: ParentNode, text: string): HTMLButtonElement {
	const button = Array.from(root.querySelectorAll<HTMLButtonElement>('button')).find((candidate) =>
		candidate.textContent?.includes(text)
	);
	if (!button) throw new Error(`Expected a button named ${text}`);
	return button;
}

function firePointer(
	target: EventTarget,
	type: 'pointerdown' | 'pointermove' | 'pointerup',
	clientY: number,
	timeStamp: number
): void {
	const event = new PointerEvent(type, {
		pointerId: 1,
		pointerType: 'mouse',
		button: 0,
		bubbles: true,
		cancelable: true,
		clientY
	});
	Object.defineProperty(event, 'timeStamp', { value: timeStamp, configurable: true });
	target.dispatchEvent(event);
}

function fireClick(target: EventTarget): void {
	target.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
}

function stubMomentumTiming(): void {
	vi.stubGlobal(
		'requestAnimationFrame',
		vi.fn(() => 1)
	);
	vi.stubGlobal('cancelAnimationFrame', vi.fn());
	vi.stubGlobal('performance', { now: () => 0 });
}

async function openRailGroup(root: ParentNode, index: number): Promise<void> {
	const disclosure = root.querySelectorAll<HTMLButtonElement>(
		'.rail-group > .disclose-row > button.disclose'
	)[index];
	if (!disclosure) throw new Error('Expected the Library disclosure');
	if (disclosure.getAttribute('aria-expanded') === 'false') disclosure.click();
	await tick();
}

beforeEach(() => {
	localStorage.clear();
	resetLibraryContextForTests();
	albumList.set([]);
	history.replaceState(null, '', '/');
});

afterEach(async () => {
	await cleanup();
	resetLibraryContextForTests();
	resetPlaylists();
	vi.unstubAllGlobals();
});

describe('Rail', () => {
	it('renders the brand, the LIBRARY and PLAYLISTS groups, the settings disclosure, and the user row', async () => {
		albumList.set([album({ id: 'a1', title: 'A' })]);
		const target = await render();
		expect(requireElement(target, '.brand').textContent).toBe('Hallucinai');
		// Scoped to the top-level group toggles: a nested album row is also a
		// `button.disclose` (RailLibraryGroup's per-album disclosure), so an
		// unscoped query would pick it up between Library, Playlists, and
		// Settings.
		const groupRows = target.querySelectorAll<HTMLElement>('.rail-group > .disclose-row');
		expect(groupRows[0]?.textContent).toContain('Library');
		expect(groupRows[0]?.querySelector('.meta')?.textContent).toBe('1');
		expect(groupRows[1]?.textContent).toContain('Playlists');
		expect(groupRows[2]?.textContent).toContain('Settings');
		expect(target.textContent).toContain('felix');
	});

	it('acts as the Library link when the brand wordmark is clicked, keeping the open collection', async () => {
		openCollection.set({ kind: 'album', id: 'a1' });
		librarySurface.set('detail');
		const target = await render();
		const brand = requireElement<HTMLButtonElement>(target, '.brand');
		// Named after what it is (the wordmark), not what it does -- GitHub's own
		// logo pattern -- so it never collides with the LIBRARY group's own
		// "Library" name in an accessible-name lookup (both live in the same
		// mobile drawer).
		expect(brand.hasAttribute('aria-label')).toBe(false);
		expect(brand.textContent).toBe('Hallucinai');
		brand.click();
		await tick();
		await Promise.resolve();
		expect(get(librarySurface)).toBe('browse');
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
	});

	it('scrolls the LIBRARY and PLAYLISTS groups, pinning Settings and the user row below them', async () => {
		const target = await render();
		const scroll = requireElement(target, '.rail-scroll');
		const scrolledToggles = scroll.querySelectorAll(
			'.rail-group > .disclose-row > button.disclose'
		);
		expect(scrolledToggles).toHaveLength(2);
		expect(scrolledToggles[0]?.querySelector('.group-title')?.textContent?.trim()).toBe('Library');
		expect(scrolledToggles[1]?.querySelector('.group-title')?.textContent?.trim()).toBe(
			'Playlists'
		);
		expect(scroll.textContent).not.toContain('Settings');

		const settingsPin = requireElement(target, '.rail-settings-pin');
		const settingsToggle = settingsPin.querySelector(
			'.rail-group > .disclose-row > button.disclose'
		);
		expect(settingsToggle?.textContent).toContain('Settings');

		const bottom = requireElement(target, '.rail-bottom');
		expect(bottom.textContent).toContain('felix');
		expect(target.querySelector('.rail-scroll ~ .rail-settings-pin ~ .rail-bottom')).not.toBeNull();
	});

	it('opens an album through the kinetic rail click', async () => {
		albumList.set([
			album({ id: 'a1', title: 'Nachtstrom' }),
			album({ id: 'a2', title: 'Sonnwendfeuer' })
		]);
		setOpenCollection({ kind: 'album', id: 'a1' });
		const target = await render();
		await openRailGroup(target, 0);
		const albumButton = findButtonByText(target, 'Sonnwendfeuer');

		fireClick(albumButton);

		await vi.waitFor(() => {
			expect(get(openCollection)).toEqual({ kind: 'album', id: 'a2' });
		});
	});

	it('does not open an album after dragging the kinetic rail', async () => {
		stubMomentumTiming();
		albumList.set([
			album({ id: 'a1', title: 'Nachtstrom' }),
			album({ id: 'a2', title: 'Sonnwendfeuer' })
		]);
		setOpenCollection({ kind: 'album', id: 'a1' });
		const target = await render();
		await openRailGroup(target, 0);
		const scroll = requireElement<HTMLElement>(target, '.rail-scroll');
		scroll.style.flexDirection = 'column';
		Object.defineProperty(scroll, 'clientHeight', { value: 100, configurable: true });
		Object.defineProperty(scroll, 'scrollHeight', { value: 400, configurable: true });

		firePointer(scroll, 'pointerdown', 200, 1000);
		firePointer(scroll, 'pointermove', 150, 1010);
		firePointer(scroll, 'pointerup', 150, 1040);
		fireClick(findButtonByText(target, 'Sonnwendfeuer'));
		await tick();

		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
	});

	it('does not open an album when a click catches the rail momentum', async () => {
		stubMomentumTiming();
		albumList.set([
			album({ id: 'a1', title: 'Nachtstrom' }),
			album({ id: 'a2', title: 'Sonnwendfeuer' })
		]);
		playlistList.set([
			playlist({ id: 'p1', title: 'Night Drive' }),
			playlist({ id: 'p2', title: 'Morning Run' })
		]);
		setOpenCollection({ kind: 'album', id: 'a1' });
		const target = await render();
		await openRailGroup(target, 0);
		await openRailGroup(target, 1);
		const scroll = requireElement<HTMLElement>(target, '.rail-scroll');
		scroll.style.flexDirection = 'column';
		Object.defineProperty(scroll, 'clientHeight', { value: 100, configurable: true });
		Object.defineProperty(scroll, 'scrollHeight', { value: 400, configurable: true });

		firePointer(scroll, 'pointerdown', 200, 1000);
		firePointer(scroll, 'pointermove', 150, 1010);
		firePointer(scroll, 'pointerup', 150, 1040);
		fireClick(findButtonByText(target, 'Sonnwendfeuer'));
		firePointer(scroll, 'pointerdown', 150, 1100);
		firePointer(scroll, 'pointerup', 150, 1100);
		fireClick(findButtonByText(target, 'Morning Run'));
		await tick();

		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
	});

	it('opens a playlist through the kinetic rail click', async () => {
		playlistList.set([
			playlist({ id: 'p1', title: 'Night Drive' }),
			playlist({ id: 'p2', title: 'Morning Run' })
		]);
		const target = await render();
		await openRailGroup(target, 1);

		fireClick(findButtonByText(target, 'Morning Run'));

		await vi.waitFor(() => {
			expect(get(openCollection)).toEqual({ kind: 'playlist', id: 'p2' });
		});
	});

	it('does not collapse an open playlist when an album row is expanded by its own chevron -- Library and Playlists do not share a slot', async () => {
		albumList.set([album({ id: 'a1', title: 'Nachtstrom' })]);
		playlistList.set([playlist({ id: 'p1', title: 'Night Drive', entry_count: 0 })]);
		setOpenCollection({ kind: 'playlist', id: 'p1' });
		selectedPlaylistDetail.set(
			detail({ id: 'p1', title: 'Night Drive', entry_count: 0, entries: [] })
		);
		const target = await render();
		const playlistPanel = requireElement<HTMLDivElement>(target, '.playlist-songs');
		expect(playlistPanel.getAttribute('data-open')).toBe('true');

		const albumToggle = requireElement<HTMLButtonElement>(target, '.album-disclose');
		albumToggle.click();
		await tick();

		expect(albumToggle.getAttribute('aria-expanded')).toBe('true');
		expect(playlistPanel.getAttribute('data-open')).toBe('true');
	});

	it('marks the open album and the open playlist with the same row-active highlight', async () => {
		albumList.set([
			album({ id: 'a1', title: 'Nachtstrom' }),
			album({ id: 'a2', title: 'Sonnwendfeuer' })
		]);
		playlistList.set([
			playlist({ id: 'p1', title: 'Night Drive', entry_count: 0 }),
			playlist({ id: 'p2', title: 'Morning Run', entry_count: 0 })
		]);
		setOpenCollection({ kind: 'album', id: 'a1' });
		selectedPlaylistDetail.set(null);
		const target = await render();

		const albumLabels = target.querySelectorAll<HTMLButtonElement>('.album-label');
		const playlistLabels = target.querySelectorAll<HTMLButtonElement>('.playlist-label');
		expect(albumLabels).toHaveLength(2);
		expect(playlistLabels).toHaveLength(2);

		// The open album is marked, its sibling is not -- no third state, same
		// as the open playlist below.
		expect(albumLabels[0]?.classList.contains('row-active')).toBe(true);
		expect(albumLabels[1]?.classList.contains('row-active')).toBe(false);
		expect(playlistLabels[0]?.classList.contains('row-active')).toBe(false);
		expect(playlistLabels[1]?.classList.contains('row-active')).toBe(false);

		setOpenCollection({ kind: 'playlist', id: 'p2' });
		await tick();

		expect(albumLabels[0]?.classList.contains('row-active')).toBe(false);
		expect(albumLabels[1]?.classList.contains('row-active')).toBe(false);
		expect(playlistLabels[0]?.classList.contains('row-active')).toBe(false);
		expect(playlistLabels[1]?.classList.contains('row-active')).toBe(true);
	});
});
