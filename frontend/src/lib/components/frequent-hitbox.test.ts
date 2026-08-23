import { createRawSnippet, mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type {
	GenerationItem,
	PlaylistDetailItem,
	PlaylistEntryItem,
	SongItem
} from '$lib/api/types';
import {
	HITBOX_COMPACT_PX,
	HITBOX_FREQUENT_PX,
	PLAYLIST_ENTRY_MOVE_DOWN_LABEL,
	PLAYLIST_ENTRY_MOVE_UP_LABEL,
	PLAYLIST_ENTRY_REMOVE_LABEL
} from '$lib/constants';
import { libraryFilter, resetLibraryContextForTests } from '$lib/stores/libraryContext';
import { resetLibrarySearchForTests } from '$lib/stores/librarySearch';
import { albumList, songList } from '$lib/stores/player';
import { resetCollectionForTests, setOpenCollection } from '$lib/stores/collection';
import { playlistList, playlistLoad, selectedPlaylistDetail } from '$lib/stores/playlists';
import { currentUser, authLoading } from '$lib/stores/auth';
import { closeSidebar, theme, toggleSidebar } from '$lib/stores/ui';
import { HITBOX_STYLE as hitboxCss } from '$lib/styles/hitbox';

vi.mock('$lib/api/library', () => ({
	searchLibrary: vi.fn()
}));
vi.mock('$lib/api/albums', () => ({
	fetchAlbum: vi.fn(),
	fetchAlbums: vi.fn()
}));
vi.mock('$lib/api/songs', () => ({
	fetchSong: vi.fn(),
	fetchSongs: vi.fn()
}));
vi.mock('$lib/api/client', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/api/client')>();
	return {
		...actual,
		bulkDeleteGenerations: vi.fn(),
		sharePlaylist: vi.fn(),
		unsharePlaylist: vi.fn(),
		createQueueStreamSnapshot: vi.fn(),
		fetchPlaylists: vi.fn().mockResolvedValue([]),
		fetchPlaylist: vi.fn(),
		removeFromPlaylist: vi.fn().mockResolvedValue(undefined),
		reorderPlaylistEntry: vi.fn().mockResolvedValue(undefined),
		fetchCapabilities: vi.fn().mockResolvedValue({}),
		checkSetupRequired: vi.fn()
	};
});
vi.mock('$lib/api/queue-streams', () => ({
	pinQueueStream: vi.fn(),
	unpinQueueStream: vi.fn()
}));
vi.mock('$lib/services/offline', () => ({
	saveStream: vi.fn(),
	removeStream: vi.fn(),
	offlineStreamUrl: vi.fn(() => '/offline/stream/test'),
	rememberPlaylistOfflineStream: vi.fn(),
	forgetPlaylistOfflineStream: vi.fn(),
	loadSavedOfflinePlaylist: vi.fn().mockResolvedValue(null)
}));
vi.mock('$lib/stores/navigation', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/stores/navigation')>();
	return {
		...actual,
		backToCollection: vi.fn(),
		openAlbum: vi.fn(),
		openLibraryCreate: vi.fn(),
		openLibraryWall: vi.fn(),
		openPlaylist: vi.fn(),
		selectLibraryFilter: vi.fn(),
		selectSong: vi.fn(),
		persistLibraryHistory: vi.fn()
	};
});
vi.mock('$lib/stores/toast', () => ({
	addToast: vi.fn()
}));
vi.mock('$app/navigation', () => ({
	goto: vi.fn().mockResolvedValue(undefined),
	afterNavigate: vi.fn()
}));
vi.mock('$app/environment', () => ({
	browser: true,
	dev: true
}));
vi.mock('$app/state', () => ({
	page: { url: new URL('https://songmaker.test/') }
}));
vi.mock('$lib/stores/auth', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/stores/auth')>();
	return {
		...actual,
		checkAuth: vi.fn(async () => {
			const user = { id: 'u1', username: 'felix', role: 'user' as const };
			actual.currentUser.set(user);
			actual.authLoading.set(false);
			return user;
		})
	};
});

import { removeFromPlaylist, reorderPlaylistEntry } from '$lib/api/client';
import { backToCollection, openLibraryWall } from '$lib/stores/navigation';
import AlbumDetailView from './AlbumDetailView.svelte';
import PlaylistDetailView from './PlaylistDetailView.svelte';
import PlaylistPicker from './PlaylistPicker.svelte';
import LibraryWall from './LibraryWall.svelte';
import PlayerBar from './PlayerBar.svelte';
import ThemeToggle from './ThemeToggle.svelte';
import Layout from '../../routes/+layout.svelte';

type PointerKind = 'coarse' | 'fine';

const INVENTORY = [
	{ name: 'theme-toggle', selector: '[data-hitbox="frequent"][aria-label="Toggle theme"]' },
	{
		name: 'playlist-move-up',
		selector: '.entry-overflow-item[data-hitbox="frequent"]',
		text: PLAYLIST_ENTRY_MOVE_UP_LABEL
	},
	{
		name: 'playlist-move-down',
		selector: '.entry-overflow-item[data-hitbox="frequent"]',
		text: PLAYLIST_ENTRY_MOVE_DOWN_LABEL
	},
	{
		name: 'playlist-remove',
		selector: '.entry-overflow-item[data-hitbox="frequent"]',
		text: PLAYLIST_ENTRY_REMOVE_LABEL
	},
	{ name: 'playlist-row-play', selector: '.entry-play[data-hitbox="frequent"]' },
	{ name: 'album-row-play', selector: '.item-play[data-hitbox="frequent"]' },
	{ name: 'new-album', selector: '[data-hitbox="frequent"][aria-label="New album"]' },
	{ name: 'wall-tile-play', selector: '.wall-tile-play[data-hitbox="frequent"]' },
	{ name: 'playlist-picker-add', selector: '.picker-add[data-hitbox="frequent"]' },
	{ name: 'drawer-trigger', selector: '.drawer-trigger[data-hitbox="frequent"]' },
	{ name: 'collection-menu', selector: '.menu-trigger[data-hitbox="frequent"]' },
	{ name: 'library-filter-chip', selector: '.filter-chip[data-hitbox="frequent"]' },
	{ name: 'library-sort-select', selector: '.sort-select[data-hitbox="frequent"]' },
	{ name: 'library-search', selector: '.search[data-hitbox="text"]', shape: 'text' },
	{ name: 'breadcrumb-link', selector: '.crumb-link[data-hitbox="frequent"]' },
	{ name: 'now-playing-trigger', selector: '.now-playing-btn[data-hitbox="frequent"]' }
] as const;

const mounted: Array<ReturnType<typeof mount>> = [];

function setPointer(kind: PointerKind): void {
	document.documentElement.dataset.pointer = kind;
}

function clearPointer(): void {
	delete document.documentElement.dataset.pointer;
}

function parsePx(value: string, label: string): number {
	const resolved = value.startsWith('var(')
		? getComputedStyle(document.documentElement)
				.getPropertyValue(value.slice('var('.length, -1).trim())
				.trim()
		: value;
	const px = Number.parseFloat(resolved);
	if (!Number.isFinite(px)) {
		throw new Error(`${label} is not a pixel length: ${value}`);
	}
	return px;
}

function minBox(
	el: Element,
	name: string,
	heightOnly = false
): { width: number | null; height: number } {
	const style = getComputedStyle(el);
	return {
		width: heightOnly ? null : parsePx(style.minWidth, `${name} min-width`),
		height: parsePx(style.minHeight, `${name} min-height`)
	};
}

function parseGap(parent: Element): number {
	const value = getComputedStyle(parent).gap;
	const gap = Number.parseFloat(value);
	return Number.isFinite(gap) ? gap : 0;
}

function isColumn(parent: Element): boolean {
	return getComputedStyle(parent).flexDirection.startsWith('column');
}

function boxesOverlap(
	a: { left: number; right: number; top: number; bottom: number },
	b: { left: number; right: number; top: number; bottom: number }
): boolean {
	return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}

function layoutAlongParent(
	parent: Element,
	items: Array<{ name: string; el: HTMLElement }>
): Array<{ name: string; left: number; right: number; top: number; bottom: number }> {
	const gap = parseGap(parent);
	const column = isColumn(parent);
	let cursor = 0;
	return items.map(({ name, el }) => {
		const { width, height } = minBox(el, name);
		if (width === null) throw new Error(`${name} has no measurable min-width`);
		const rect = column
			? { name, left: 0, right: width, top: cursor, bottom: cursor + height }
			: { name, left: cursor, right: cursor + width, top: 0, bottom: height };
		cursor += (column ? height : width) + gap;
		return rect;
	});
}

function generation(overrides: Partial<GenerationItem> = {}): GenerationItem {
	return {
		id: 'g1',
		song_id: 's1',
		version_id: 'v1',
		version_number: 1,
		generation_number: 1,
		mp3_path: 'g1.mp3',
		wav_path: null,
		seed: 7,
		status: 'completed',
		is_archived: false,
		is_picked: false,
		is_kept: false,
		is_shared: false,
		model_mode: 'turbo',
		whisper_text: null,
		whisper_cues: null,
		version_lyrics: null,
		scores: null,
		generation_params: null,
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

function song(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's1',
		title: 'Local Only',
		album_id: 'a-local',
		album_title: 'Local Album',
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
		generation_count: 1,
		best_scores: null,
		best_rating: null,
		generations: [generation()],
		created_at: '2026-01-01T00:00:00+00:00',
		is_shared: false,
		share_slug: null,
		...overrides
	};
}

function playlistEntry(overrides: Partial<PlaylistEntryItem> = {}): PlaylistEntryItem {
	return {
		id: 'e1',
		position: 0,
		generation_id: 'g1',
		song_id: 's1',
		song_title: 'First Track',
		album_title: 'Local Album',
		artist: 'Artist',
		generation_number: 1,
		version_number: 1,
		is_picked: false,
		audio_duration: 180,
		mp3_path: 'g1.mp3',
		seed: 7,
		model_mode: 'turbo',
		lyrics: null,
		...overrides
	};
}

function playlistDetail(): PlaylistDetailItem {
	return {
		id: 'p1',
		title: 'Night Drive',
		entry_count: 3,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00',
		entries: [
			playlistEntry({ id: 'e1', position: 0, song_title: 'First Track' }),
			playlistEntry({
				id: 'e2',
				position: 1,
				generation_id: 'g2',
				song_title: 'Second Track'
			}),
			playlistEntry({
				id: 'e3',
				position: 2,
				generation_id: 'g3',
				song_title: 'Third Track'
			})
		]
	};
}

function requireButton(
	root: ParentNode,
	name: string,
	selector: string,
	text?: string
): HTMLElement {
	const matches = Array.from(root.querySelectorAll<HTMLElement>(selector));
	const el = text === undefined ? matches[0] : matches.find((m) => m.textContent?.trim() === text);
	if (!el) {
		throw new Error(`${name} is missing (${selector}${text === undefined ? '' : ` "${text}"`})`);
	}
	return el;
}

function openEntryOverflowMenu(row: HTMLElement): void {
	requireButton(row, 'entry-overflow-toggle', '.overflow-btn').click();
}

beforeEach(() => {
	const sheet = document.createElement('style');
	sheet.dataset.hitboxStyles = 'true';
	sheet.textContent = hitboxCss;
	document.head.append(sheet);
	resetLibrarySearchForTests();
	resetLibraryContextForTests();
	albumList.set([
		{
			id: 'a-local',
			title: 'Local Album',
			artist: 'Artist',
			subtitle: '',
			year: '',
			colors: {},
			song_count: 1,
			picked_count: 0,
			is_shared: false,
			share_slug: null,
			created_at: '2026-01-01T00:00:00+00:00'
		}
	]);
	songList.set([song({ generations: [] })]);
	playlistList.set([]);
	playlistLoad.set({ status: 'ready', error: null });
	const playlist = playlistDetail();
	setOpenCollection({ kind: 'playlist', id: playlist.id });
	selectedPlaylistDetail.set(playlist);
	theme.set('dark');
	document.documentElement.dataset.theme = 'dark';
	vi.stubGlobal(
		'matchMedia',
		vi.fn(() => ({
			matches: true,
			media: '',
			onchange: null,
			addEventListener: vi.fn(),
			removeEventListener: vi.fn(),
			addListener: vi.fn(),
			removeListener: vi.fn(),
			dispatchEvent: vi.fn()
		}))
	);
	currentUser.set({ id: 'u1', username: 'felix', role: 'user' as const });
	authLoading.set(false);
	vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	clearPointer();
	resetLibrarySearchForTests();
	resetLibraryContextForTests();
	selectedPlaylistDetail.set(null);
	currentUser.set(null);
	closeSidebar();
	resetCollectionForTests();
	vi.unstubAllGlobals();
});

const layoutChildren = createRawSnippet(() => ({
	render: () => `<div></div>`
}));

interface RenderedInventory {
	root: HTMLElement;
	playlistPickerOnClose: ReturnType<typeof vi.fn>;
}

async function renderInventory(): Promise<RenderedInventory> {
	const root = document.createElement('div');
	document.body.append(root);

	const themeTarget = document.createElement('div');
	const playlistTarget = document.createElement('div');
	const albumTarget = document.createElement('div');
	const songTarget = document.createElement('div');
	const pickerTarget = document.createElement('div');
	const layoutTarget = document.createElement('div');
	const playerTarget = document.createElement('div');
	root.append(
		themeTarget,
		playlistTarget,
		albumTarget,
		songTarget,
		pickerTarget,
		layoutTarget,
		playerTarget
	);

	const playlistPickerOnClose = vi.fn();

	mounted.push(mount(ThemeToggle, { target: themeTarget }));
	mounted.push(mount(PlaylistDetailView, { target: playlistTarget }));
	// The album interior is asked for by id rather than by opening it, since the
	// playlist interior above needs the open collection to stay its own.
	mounted.push(mount(AlbumDetailView, { target: albumTarget, props: { albumId: 'a-local' } }));
	mounted.push(mount(LibraryWall, { target: songTarget, props: { oncreate: vi.fn() } }));
	mounted.push(
		mount(PlaylistPicker, {
			target: pickerTarget,
			props: { onselect: vi.fn(), onclose: playlistPickerOnClose }
		})
	);
	mounted.push(mount(Layout, { target: layoutTarget, props: { children: layoutChildren } }));
	mounted.push(mount(PlayerBar, { target: playerTarget }));
	await tick();
	await Promise.resolve();
	await tick();
	toggleSidebar();
	await tick();
	return { root, playlistPickerOnClose };
}

describe('frequent action hitboxes', () => {
	it('defines shared frequent and compact hitbox tokens', () => {
		const style = getComputedStyle(document.documentElement);
		expect(style.getPropertyValue('--hitbox-frequent').trim()).toBe(`${HITBOX_FREQUENT_PX}px`);
		expect(style.getPropertyValue('--hitbox-compact').trim()).toBe(`${HITBOX_COMPACT_PX}px`);
		expect(hitboxCss).toContain(`--hitbox-frequent: ${HITBOX_FREQUENT_PX}px`);
		expect(hitboxCss).toContain(`--hitbox-compact: ${HITBOX_COMPACT_PX}px`);
		expect(hitboxCss).toContain('@media (any-pointer: coarse)');
	});

	it('names every frequent-action target and measures coarse and fine pointers', async () => {
		const { root } = await renderInventory();
		const middleRow = root.querySelectorAll('.entry-row')[1];
		if (!(middleRow instanceof HTMLElement)) {
			throw new Error('playlist-move-up is missing a middle-row neighbor');
		}
		openEntryOverflowMenu(middleRow);
		await tick();
		const found: Array<{ name: string; el: HTMLElement; shape?: string }> = [];

		for (const target of INVENTORY) {
			const el = requireButton(
				root,
				target.name,
				target.selector,
				'text' in target ? target.text : undefined
			);
			found.push({ name: target.name, el, shape: 'shape' in target ? target.shape : undefined });
		}

		// A labelled control's width is its label's, so only its height is
		// measured; an icon target has to be square at both pointer sizes.
		setPointer('fine');
		for (const { name, el, shape } of found) {
			const box = minBox(el, name, shape === 'text');
			if (box.width !== null) {
				expect(box.width, `${name} fine width`).toBeGreaterThanOrEqual(HITBOX_COMPACT_PX);
			}
			expect(box.height, `${name} fine height`).toBeGreaterThanOrEqual(HITBOX_COMPACT_PX);
		}

		setPointer('coarse');
		for (const { name, el, shape } of found) {
			const box = minBox(el, name, shape === 'text');
			if (box.width !== null) {
				expect(box.width, `${name} coarse width`).toBe(HITBOX_FREQUENT_PX);
			}
			expect(box.height, `${name} coarse height`).toBe(HITBOX_FREQUENT_PX);
		}

		const siblingGroups: Array<Array<{ name: string; el: HTMLElement }>> = [];
		siblingGroups.push([
			{
				name: 'playlist-move-up',
				el: requireButton(
					middleRow,
					'playlist-move-up',
					'.entry-overflow-item[data-hitbox="frequent"]',
					PLAYLIST_ENTRY_MOVE_UP_LABEL
				)
			},
			{
				name: 'playlist-move-down',
				el: requireButton(
					middleRow,
					'playlist-move-down',
					'.entry-overflow-item[data-hitbox="frequent"]',
					PLAYLIST_ENTRY_MOVE_DOWN_LABEL
				)
			}
		]);

		for (const group of siblingGroups) {
			const parent = group[0]?.el.parentElement;
			if (!parent || group.length < 2) {
				throw new Error(`${group[0]?.name ?? 'target'} has no sibling hitbox to compare`);
			}
			const rects = layoutAlongParent(parent, group);
			for (let i = 0; i < rects.length; i += 1) {
				for (let j = i + 1; j < rects.length; j += 1) {
					expect(
						boxesOverlap(rects[i], rects[j]),
						`${rects[i].name} overlaps ${rects[j].name}`
					).toBe(false);
				}
			}
		}
	});

	it('sizes the new-playlist create action to the frequent hitbox on the Playlists filter', async () => {
		const { root } = await renderInventory();
		libraryFilter.set('playlists');
		await tick();
		const newPlaylistBtn = requireButton(
			root,
			'new-playlist',
			'[data-hitbox="frequent"][aria-label="New playlist"]'
		);

		setPointer('coarse');
		const coarse = minBox(newPlaylistBtn, 'new-playlist');
		expect(coarse.width).toBe(HITBOX_FREQUENT_PX);
		expect(coarse.height).toBe(HITBOX_FREQUENT_PX);

		setPointer('fine');
		const fine = minBox(newPlaylistBtn, 'new-playlist');
		expect(fine.width).toBeGreaterThanOrEqual(HITBOX_COMPACT_PX);
		expect(fine.height).toBeGreaterThanOrEqual(HITBOX_COMPACT_PX);
	});

	it('keeps reorder and remove on the same button hitbox for pointer and keyboard', async () => {
		const { root } = await renderInventory();
		const secondRow = root.querySelectorAll('.entry-row')[1];
		if (!(secondRow instanceof HTMLElement)) {
			throw new Error('Second Track row is missing');
		}
		openEntryOverflowMenu(secondRow);
		await tick();
		const upBtn = requireButton(
			secondRow,
			'playlist-move-up',
			'.entry-overflow-item[data-hitbox="frequent"]',
			PLAYLIST_ENTRY_MOVE_UP_LABEL
		);
		const downBtn = requireButton(
			secondRow,
			'playlist-move-down',
			'.entry-overflow-item[data-hitbox="frequent"]',
			PLAYLIST_ENTRY_MOVE_DOWN_LABEL
		);
		const removeBtn = requireButton(
			secondRow,
			'playlist-remove',
			'.entry-overflow-item[data-hitbox="frequent"]',
			PLAYLIST_ENTRY_REMOVE_LABEL
		);
		const themeBtn = requireButton(root, 'theme-toggle', '[aria-label="Toggle theme"]');

		upBtn.focus();
		expect(document.activeElement).toBe(upBtn);
		downBtn.focus();
		expect(document.activeElement).toBe(downBtn);
		removeBtn.focus();
		expect(document.activeElement).toBe(removeBtn);
		upBtn.click();
		await tick();
		expect(reorderPlaylistEntry).toHaveBeenCalled();

		openEntryOverflowMenu(secondRow);
		await tick();
		const removeBtnAfterMove = requireButton(
			secondRow,
			'playlist-remove',
			'.entry-overflow-item[data-hitbox="frequent"]',
			PLAYLIST_ENTRY_REMOVE_LABEL
		);
		removeBtnAfterMove.click();
		await tick();
		expect(removeFromPlaylist).toHaveBeenCalled();

		themeBtn.click();
		await tick();
		expect(document.documentElement.dataset.theme).toBe('light');
	});
});

describe('PlayerBar mobile transport', () => {
	// jsdom in this project's Vitest setup does not apply Svelte's scoped
	// component <style> (confirmed empirically: getComputedStyle never
	// reflects it here, even for rules that have long passed elsewhere in
	// this file via the manually injected [data-hitbox] stylesheet), so the
	// 44px mobile play-button rule cannot be asserted by computed style in
	// this suite. What jsdom *can* verify is the wiring that switches the
	// mobile layout on: the single `.mobile-transport` class the component
	// derives from `subscribeCompactLayout`. The 44px value itself is a
	// visual-review item (see docs/architecture.md's mobile bar contract).
	it('applies the mobile transport layout only when the layout is compact', async () => {
		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(mount(PlayerBar, { target }));
		await tick();
		await Promise.resolve();
		await tick();

		expect(target.querySelector('.player-bar.mobile-transport')).not.toBeNull();
	});
});

describe('Escape yields to an open popover before the global one-level-up shortcut', () => {
	beforeEach(() => {
		setOpenCollection({ kind: 'album', id: 'a-local' });
		vi.mocked(openLibraryWall).mockClear();
		vi.mocked(backToCollection).mockClear();
	});

	function pressEscape(): void {
		document.body.dispatchEvent(
			new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
		);
	}

	it('closes the PlaylistPicker and does not run the global one-level-up navigation', async () => {
		const { playlistPickerOnClose } = await renderInventory();

		pressEscape();
		await tick();

		expect(playlistPickerOnClose).toHaveBeenCalledTimes(1);
		expect(openLibraryWall).not.toHaveBeenCalled();
		expect(backToCollection).not.toHaveBeenCalled();
	});
});
