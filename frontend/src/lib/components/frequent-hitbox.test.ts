import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type {
	GenerationItem,
	PlaylistDetailItem,
	PlaylistEntryItem,
	SongItem
} from '$lib/api/types';
import { HITBOX_COMPACT_PX, HITBOX_FREQUENT_PX } from '$lib/constants';
import { GENERATION_ACTIONS_KEY, type GenerationActions } from '$lib/contexts/generation-actions';
import { resetLibraryContextForTests } from '$lib/stores/libraryContext';
import { resetLibrarySearchForTests } from '$lib/stores/librarySearch';
import { albumList, songList } from '$lib/stores/player';
import { playlistList, playlistLoad, selectedPlaylistDetail } from '$lib/stores/playlists';
import { theme } from '$lib/stores/ui';
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
		reorderPlaylistEntry: vi.fn().mockResolvedValue(undefined)
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
vi.mock('$lib/stores/navigation', () => ({
	openAlbum: vi.fn(),
	openPlaylist: vi.fn(),
	selectLibraryFilter: vi.fn(),
	selectSong: vi.fn(),
	persistLibraryHistory: vi.fn()
}));
vi.mock('$lib/stores/toast', () => ({
	addToast: vi.fn()
}));

import { removeFromPlaylist, reorderPlaylistEntry } from '$lib/api/client';
import GenerationsList from './GenerationsList.svelte';
import PlaylistDetailView from './PlaylistDetailView.svelte';
import PlaylistPicker from './PlaylistPicker.svelte';
import LibraryWall from './LibraryWall.svelte';
import ThemeToggle from './ThemeToggle.svelte';

type PointerKind = 'coarse' | 'fine';

const INVENTORY = [
	{ name: 'theme-toggle', selector: '[data-hitbox="frequent"][aria-label="Toggle theme"]' },
	{ name: 'pick', selector: '.pick-btn[data-hitbox="frequent"]' },
	{ name: 'keep', selector: '.keep-btn[data-hitbox="frequent"]' },
	{
		name: 'playlist-move-up',
		selector: '.move-btn[data-hitbox="frequent"][aria-label$=" up"]'
	},
	{
		name: 'playlist-move-down',
		selector: '.move-btn[data-hitbox="frequent"][aria-label$=" down"]'
	},
	{ name: 'playlist-remove', selector: '.remove-btn[data-hitbox="frequent"]' },
	{ name: 'new-album', selector: '[data-hitbox="frequent"][aria-label="New album"]' },
	{ name: 'playlist-picker-add', selector: '.picker-add[data-hitbox="frequent"]' }
] as const;

const mounted: Array<ReturnType<typeof mount>> = [];
const pick = vi.fn();
const keep = vi.fn();

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

function minBox(el: Element, name: string): { width: number; height: number } {
	const style = getComputedStyle(el);
	return {
		width: parsePx(style.minWidth, `${name} min-width`),
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
		const box = minBox(el, name);
		const rect = column
			? { name, left: 0, right: box.width, top: cursor, bottom: cursor + box.height }
			: { name, left: cursor, right: cursor + box.width, top: 0, bottom: box.height };
		cursor += (column ? box.height : box.width) + gap;
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

function mockActions(): GenerationActions {
	return {
		score: vi.fn(),
		pick,
		keep,
		del: vi.fn(),
		rate: vi.fn(async () => undefined),
		share: vi.fn(async () => ({ status: 'ok', share_url: '', share_slug: '' })),
		unshare: vi.fn(async () => undefined),
		addToPlaylist: vi.fn(async () => undefined),
		pinSeed: vi.fn(),
		clickVersion: vi.fn(),
		useAsSource: vi.fn()
	};
}

function requireButton(root: ParentNode, name: string, selector: string): HTMLButtonElement {
	const el = root.querySelector<HTMLButtonElement>(selector);
	if (!el) throw new Error(`${name} is missing (${selector})`);
	return el;
}

beforeEach(() => {
	pick.mockReset();
	keep.mockReset();
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
			is_shared: false,
			share_slug: null,
			created_at: '2026-01-01T00:00:00+00:00'
		}
	]);
	songList.set([song({ generations: [] })]);
	playlistList.set([]);
	playlistLoad.set({ status: 'ready', error: null });
	selectedPlaylistDetail.set(playlistDetail());
	theme.set('dark');
	document.documentElement.dataset.theme = 'dark';
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	clearPointer();
	resetLibrarySearchForTests();
	resetLibraryContextForTests();
	selectedPlaylistDetail.set(null);
});

async function renderInventory(): Promise<HTMLElement> {
	const root = document.createElement('div');
	document.body.append(root);

	const themeTarget = document.createElement('div');
	const genTarget = document.createElement('div');
	const playlistTarget = document.createElement('div');
	const songTarget = document.createElement('div');
	const pickerTarget = document.createElement('div');
	root.append(themeTarget, genTarget, playlistTarget, songTarget, pickerTarget);

	mounted.push(mount(ThemeToggle, { target: themeTarget }));
	mounted.push(
		mount(GenerationsList, {
			target: genTarget,
			props: { song: song(), onselect: vi.fn() },
			context: new Map([[GENERATION_ACTIONS_KEY, mockActions()]])
		})
	);
	mounted.push(mount(PlaylistDetailView, { target: playlistTarget }));
	mounted.push(mount(LibraryWall, { target: songTarget, props: { onNewSong: vi.fn() } }));
	mounted.push(
		mount(PlaylistPicker, { target: pickerTarget, props: { onselect: vi.fn(), onclose: vi.fn() } })
	);
	await tick();
	return root;
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
		const root = await renderInventory();
		const found: Array<{ name: string; el: HTMLButtonElement }> = [];

		for (const target of INVENTORY) {
			const el = requireButton(root, target.name, target.selector);
			expect(el.tagName, `${target.name} is a button`).toBe('BUTTON');
			found.push({ name: target.name, el });
		}

		setPointer('fine');
		for (const { name, el } of found) {
			const box = minBox(el, name);
			expect(box.width, `${name} fine width`).toBeGreaterThanOrEqual(HITBOX_COMPACT_PX);
			expect(box.height, `${name} fine height`).toBeGreaterThanOrEqual(HITBOX_COMPACT_PX);
		}

		setPointer('coarse');
		for (const { name, el } of found) {
			const box = minBox(el, name);
			expect(box.width, `${name} coarse width`).toBe(HITBOX_FREQUENT_PX);
			expect(box.height, `${name} coarse height`).toBe(HITBOX_FREQUENT_PX);
		}

		const siblingGroups: Array<Array<{ name: string; el: HTMLButtonElement }>> = [
			found.filter((item) => item.name === 'pick' || item.name === 'keep')
		];
		const middleRow = root.querySelectorAll('.entry-row')[1];
		if (!(middleRow instanceof HTMLElement)) {
			throw new Error('playlist-move-up is missing a middle-row neighbor');
		}
		siblingGroups.push([
			{
				name: 'playlist-move-up',
				el: requireButton(
					middleRow,
					'playlist-move-up',
					'.move-btn[data-hitbox="frequent"][aria-label$=" up"]'
				)
			},
			{
				name: 'playlist-move-down',
				el: requireButton(
					middleRow,
					'playlist-move-down',
					'.move-btn[data-hitbox="frequent"][aria-label$=" down"]'
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

	it('keeps pick, keep, reorder, and remove on the same button hitbox for pointer and keyboard', async () => {
		const root = await renderInventory();
		const pickBtn = requireButton(root, 'pick', '.pick-btn[data-hitbox="frequent"]');
		const keepBtn = requireButton(root, 'keep', '.keep-btn[data-hitbox="frequent"]');
		const upBtn = requireButton(
			root,
			'playlist-move-up',
			'.move-btn[data-hitbox="frequent"][aria-label="Move Second Track up"]'
		);
		const downBtn = requireButton(
			root,
			'playlist-move-down',
			'.move-btn[data-hitbox="frequent"][aria-label="Move Second Track down"]'
		);
		const removeBtn = requireButton(
			root,
			'playlist-remove',
			'.remove-btn[data-hitbox="frequent"][aria-label="Remove Second Track from playlist"]'
		);
		const themeBtn = requireButton(root, 'theme-toggle', '[aria-label="Toggle theme"]');

		pickBtn.click();
		expect(pick).toHaveBeenCalledWith('g1', true);
		keepBtn.click();
		expect(keep).toHaveBeenCalledWith('g1', true);

		upBtn.focus();
		expect(document.activeElement).toBe(upBtn);
		downBtn.focus();
		expect(document.activeElement).toBe(downBtn);
		removeBtn.focus();
		expect(document.activeElement).toBe(removeBtn);
		upBtn.click();
		await tick();
		expect(reorderPlaylistEntry).toHaveBeenCalled();
		removeBtn.click();
		await tick();
		expect(removeFromPlaylist).toHaveBeenCalled();

		themeBtn.click();
		await tick();
		expect(document.documentElement.dataset.theme).toBe('light');
	});
});
