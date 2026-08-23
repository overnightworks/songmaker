import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { GenerationItem, SongItem } from '$lib/api/types';
import { GENERATION_ACTIONS_KEY, type GenerationActions } from '$lib/contexts/generation-actions';
import {
	HITBOX_COMPACT_PX,
	HITBOX_FREQUENT_PX,
	TAKE_ARCHIVED_TITLE,
	TAKE_PLAYLIST_LABEL,
	TAKES_MOBILE_HINT
} from '$lib/constants';
import { HITBOX_STYLE as hitboxCss } from '$lib/styles/hitbox';
import { get } from 'svelte/store';
import { clearSelection, selectedIds, toggleSelection } from '$lib/stores/selection';

function enterSelectionMode(): void {
	toggleSelection('selection-mode-seed');
}

function px(value: string): number {
	const resolved = value.startsWith('var(')
		? getComputedStyle(document.documentElement)
				.getPropertyValue(value.slice('var('.length, -1).trim())
				.trim()
		: value;
	return Number.parseFloat(resolved);
}

vi.mock('$lib/api/client', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/api/client')>();
	return {
		...actual,
		bulkDeleteGenerations: vi.fn(),
		cancelJob: vi.fn(),
		remasterGeneration: vi.fn(),
		unarchiveGeneration: vi.fn(),
		fetchSong: vi.fn(),
		deleteVersion: vi.fn(),
		fetchVersions: vi.fn().mockResolvedValue([])
	};
});
vi.mock('$lib/stores/toast', () => ({ addToast: vi.fn() }));
vi.mock('$lib/stores/navigation', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/stores/navigation')>();
	return { ...actual, persistLibraryHistory: vi.fn() };
});
vi.mock('$lib/stores/player', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/stores/player')>();
	return {
		...actual,
		playTakeAndShowNowPlaying: vi.fn(async () => undefined)
	};
});

import { addToast } from '$lib/stores/toast';
import { playTakeAndShowNowPlaying } from '$lib/stores/player';
import { playlistList, playlistLoad } from '$lib/stores/playlists';
import TakesList from './TakesList.svelte';

const playlist = {
	id: 'p1',
	title: 'Night Drive',
	entry_count: 0,
	is_shared: false,
	share_slug: null,
	created_at: '2026-01-01T00:00:00+00:00'
};

function openTakeMenu(row: HTMLElement): void {
	row.querySelector<HTMLButtonElement>('.overflow-btn')?.click();
}

function clickMenuItem(root: ParentNode, label: string): void {
	const item = Array.from(root.querySelectorAll<HTMLButtonElement>('.overflow-item')).find(
		(el) => el.textContent?.trim() === label
	);
	if (!item) throw new Error(`No take menu item named "${label}"`);
	item.click();
}

vi.mock('$lib/stores/playlists', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/stores/playlists')>();
	return { ...actual, ensurePlaylistsLoaded: vi.fn(async () => undefined) };
});

const mounted: Array<ReturnType<typeof mount>> = [];
const pick = vi.fn();
const keep = vi.fn();
const pinSeed = vi.fn();
const useAsSource = vi.fn();

const addToPlaylist = vi.fn(async () => undefined);

function mockActions(): GenerationActions {
	return {
		score: vi.fn(),
		pick,
		keep,
		del: vi.fn(),
		rate: vi.fn(async () => undefined),
		share: vi.fn(async () => ({ status: 'ok', share_url: '', share_slug: '' })),
		unshare: vi.fn(async () => undefined),
		addToPlaylist,
		pinSeed,
		clickVersion: vi.fn(),
		useAsSource
	};
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
		generation_params: { audio_duration: 195 },
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
		version_count: 3,
		generation_count: 5,
		best_scores: null,
		best_rating: null,
		generations: [
			generation({ id: 'g1', version_number: 3, generation_number: 3, is_picked: true }),
			generation({ id: 'g2', version_number: 3, generation_number: 2 }),
			generation({ id: 'g3', version_number: 2, generation_number: 1 })
		],
		created_at: '2026-01-01T00:00:00+00:00',
		is_shared: false,
		share_slug: null,
		...overrides
	};
}

beforeEach(() => {
	pick.mockReset();
	keep.mockReset();
	pinSeed.mockReset();
	useAsSource.mockReset();
	addToPlaylist.mockClear();
	playlistList.set([{ ...playlist }]);
	playlistLoad.set({ status: 'ready', error: null });
	vi.mocked(addToast).mockClear();
	vi.mocked(playTakeAndShowNowPlaying).mockClear();
	clearSelection();
	const sheet = document.createElement('style');
	sheet.dataset.hitboxStyles = 'true';
	sheet.textContent = hitboxCss;
	document.head.append(sheet);
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	document.head.querySelectorAll('[data-hitbox-styles]').forEach((el) => el.remove());
	delete document.documentElement.dataset.pointer;
	clearSelection();
});

async function render(overrides: Partial<Record<string, unknown>> = {}) {
	const target = document.createElement('div');
	document.body.append(target);
	const props = {
		song: song(),
		dirty: false,
		draftVersionNumber: 4,
		latestVersionNumber: 3,
		onagain: vi.fn(),
		onuseasreference: vi.fn(),
		...overrides
	};
	mounted.push(
		mount(TakesList, {
			target,
			props,
			context: new Map([[GENERATION_ACTIONS_KEY, mockActions()]])
		})
	);
	await tick();
	return { target, props };
}

describe('TakesList', () => {
	it('groups takes by version, newest first', async () => {
		const { target } = await render();
		const headers = Array.from(target.querySelectorAll('.version-header')).map(
			(el) => el.textContent
		);
		expect(headers[0]).toBe('v3 · 2 takes');
		expect(headers[1]).toBe('v2 · 1 take');
	});

	it('shows the draft banner with the next version number only when dirty', async () => {
		const { target: clean } = await render({ dirty: false });
		expect(clean.querySelector('.draft-banner')).toBeNull();

		const { target: dirty } = await render({ dirty: true, draftVersionNumber: 4 });
		expect(dirty.querySelector('.draft-banner')?.textContent).toContain('v4');
	});

	it('shows a generating row while a generate job runs for this song', async () => {
		const { target } = await render({
			generateJob: { id: 'j1', type: 'generate', status: 'running', progress: 0.4 }
		});
		expect(target.querySelector('.generating-row')?.textContent).toContain('generating');
	});

	it('labels the generating row with the version actually being generated, not the next draft version', async () => {
		// draftVersionNumber (the number Generate would create *next*) is 4
		// here — the two must not be conflated, since a running job always
		// targets an already-saved version (latestVersionNumber).
		const { target } = await render({
			generateJob: { id: 'j1', type: 'generate', status: 'running', progress: 0.4 },
			draftVersionNumber: 4,
			latestVersionNumber: 3
		});
		expect(target.querySelector('.generating-label')?.textContent).toContain('v3');
		expect(target.querySelector('.generating-label')?.textContent).not.toContain('v4');
	});

	it('labels the generating row from the actual highest version number, not the stale version_count after a mid-run deletion', async () => {
		// A middle version (v2) was deleted after this job started: song.version_count
		// dropped to 2, but the job still targets the highest surviving version, v3.
		const { target } = await render({
			song: song({ version_count: 2 }),
			generateJob: { id: 'j1', type: 'generate', status: 'running', progress: 0.4 },
			latestVersionNumber: 3
		});
		expect(target.querySelector('.generating-label')?.textContent).toContain('v3');
		expect(target.querySelector('.generating-label')?.textContent).not.toContain('v2');
	});

	it('deletes a version and its takes from the group header, with confirmation', async () => {
		const { deleteVersion, fetchSong, fetchVersions } = await import('$lib/api/client');
		vi.mocked(deleteVersion).mockResolvedValueOnce(undefined);
		vi.mocked(fetchSong).mockResolvedValueOnce(song({ version_count: 2 }));
		vi.mocked(fetchVersions).mockResolvedValueOnce([]);

		const { target } = await render();
		const deleteBtn = target.querySelector<HTMLButtonElement>('.version-delete-btn');
		if (!deleteBtn) throw new Error('Expected a delete-version button on the newest group');
		deleteBtn.click();
		await tick();
		expect(document.querySelector('.dialog h3')?.textContent).toBe('Delete v3?');

		document.querySelector<HTMLButtonElement>('.confirm-btn')?.click();
		await tick();
		await Promise.resolve();

		expect(deleteVersion).toHaveBeenCalledWith('v1', true);
	});

	it('calls pick and keep from the take actions', async () => {
		const { target } = await render();
		const row = target.querySelectorAll('.take-row')[1];
		if (!(row instanceof HTMLElement)) throw new Error('Expected the second take row (g2)');
		row.querySelector<HTMLButtonElement>('.pick-btn')?.click();
		expect(pick).toHaveBeenCalledWith('g2', true);
		row.querySelector<HTMLButtonElement>('.keep-btn')?.click();
		expect(keep).toHaveBeenCalledWith('g2', true);
	});

	it('plays the take and opens Now Playing on row click', async () => {
		const { target } = await render();
		const row = target.querySelector<HTMLElement>('.take-row');
		row?.click();
		expect(playTakeAndShowNowPlaying).toHaveBeenCalledWith(
			expect.objectContaining({ id: 'g1' }),
			expect.objectContaining({ id: 's1' })
		);
	});

	it("names the take on the row's menu, without also playing it", async () => {
		const { target } = await render();
		const row = target.querySelector<HTMLElement>('.take-row');
		row?.querySelector<HTMLButtonElement>('.overflow-btn')?.click();
		await tick();
		expect(target.querySelector('.menu-heading')?.textContent).toBe('Take · v3 · 3');
		expect(playTakeAndShowNowPlaying).not.toHaveBeenCalled();
	});

	it('adds the take to a playlist from its own row, without also playing it', async () => {
		// #141/3: the picker is absolutely positioned, so it must sit inside a
		// positioned anchor in the row — otherwise it escapes the row entirely
		// and the menu entry looks like it does nothing.
		const { target } = await render();
		const row = target.querySelector<HTMLElement>('.take-row');
		if (!row) throw new Error('Expected a take row');
		openTakeMenu(row);
		await tick();
		clickMenuItem(row, TAKE_PLAYLIST_LABEL);
		await tick();

		const picker = row.querySelector('.picker');
		expect(picker, 'the playlist picker renders inside the take row').not.toBeNull();
		expect(picker?.parentElement?.classList.contains('take-picker-anchor')).toBe(true);

		row.querySelector<HTMLButtonElement>('.picker-item')?.click();
		await tick();
		await Promise.resolve();

		expect(addToPlaylist).toHaveBeenCalledWith('p1', 'g1');
		expect(playTakeAndShowNowPlaying).not.toHaveBeenCalled();
	});

	it('sizes pick and keep to the frequent hitbox on a coarse pointer', async () => {
		const { target } = await render();
		const pickBtn = target.querySelector<HTMLButtonElement>('.pick-btn');
		if (!pickBtn) throw new Error('Expected pick button');
		document.documentElement.dataset.pointer = 'coarse';
		const style = getComputedStyle(pickBtn);
		expect(px(style.minWidth)).toBe(HITBOX_FREQUENT_PX);
		expect(px(style.minHeight)).toBe(HITBOX_FREQUENT_PX);
		document.documentElement.dataset.pointer = 'fine';
		const fineStyle = getComputedStyle(pickBtn);
		expect(px(fineStyle.minWidth)).toBeGreaterThanOrEqual(HITBOX_COMPACT_PX);
	});
});

describe('TakesList archived takes', () => {
	async function renderWithArchived() {
		return render({
			song: song({
				generations: [
					generation({ id: 'g1', version_number: 3, generation_number: 3 }),
					generation({ id: 'g-arch', version_number: 3, generation_number: 2, is_archived: true })
				]
			})
		});
	}

	it('offers no play affordance and does not play on click', async () => {
		const { target } = await renderWithArchived();
		const archivedRow = target.querySelectorAll<HTMLElement>('.take-row')[1];
		if (!archivedRow) throw new Error('Expected the archived take row');

		expect(archivedRow.classList.contains('archived')).toBe(true);
		expect(archivedRow.getAttribute('title')).toBe(TAKE_ARCHIVED_TITLE);
		expect(archivedRow.querySelector('.take-label')?.previousElementSibling).toBeNull();

		archivedRow.click();
		await tick();
		expect(playTakeAndShowNowPlaying).not.toHaveBeenCalled();
	});

	it('opens its menu and playlist picker unclipped, with no stacking context on the row', async () => {
		// #141: `opacity` on the row would create a stacking context and clip
		// the row's own popovers under the next row.
		const { target } = await renderWithArchived();
		const archivedRow = target.querySelectorAll<HTMLElement>('.take-row')[1];
		if (!archivedRow) throw new Error('Expected the archived take row');
		expect(getComputedStyle(archivedRow).opacity).not.toBe('0.55');

		openTakeMenu(archivedRow);
		await tick();
		expect(archivedRow.querySelector('.overflow-menu')).not.toBeNull();
		clickMenuItem(archivedRow, TAKE_PLAYLIST_LABEL);
		await tick();

		const picker = archivedRow.querySelector('.picker');
		expect(picker, 'the playlist picker renders inside the archived row').not.toBeNull();
		expect(picker?.parentElement?.classList.contains('take-picker-anchor')).toBe(true);
		expect(playTakeAndShowNowPlaying).not.toHaveBeenCalled();
	});

	it('stops announcing itself as a button while it cannot act', async () => {
		const { target } = await renderWithArchived();
		const [playable, archived] = Array.from(target.querySelectorAll<HTMLElement>('.take-row'));
		expect(playable.getAttribute('role')).toBe('button');
		expect(archived.getAttribute('role')).toBeNull();
		expect(archived.getAttribute('tabindex')).toBeNull();
	});

	it('is a button again in selection mode, where ticking it still does something', async () => {
		const { target } = await renderWithArchived();
		enterSelectionMode();
		await tick();
		const archived = target.querySelectorAll<HTMLElement>('.take-row')[1];
		expect(archived.getAttribute('role')).toBe('button');
		archived.click();
		await tick();
		expect(get(selectedIds).has('g-arch')).toBe(true);
	});

	it('still plays a take that is not archived', async () => {
		const { target } = await renderWithArchived();
		target.querySelector<HTMLElement>('.take-row')?.click();
		await tick();
		expect(playTakeAndShowNowPlaying).toHaveBeenCalledWith(
			expect.objectContaining({ id: 'g1' }),
			expect.objectContaining({ id: 's1' })
		);
	});
});

describe('TakesList touch hint', () => {
	it('shows the tap hint on a coarse pointer and hides it on a mouse', async () => {
		// #141/11: a narrow desktop window is compact but still has a mouse.
		vi.stubGlobal(
			'matchMedia',
			vi.fn((query: string) => ({
				matches: query.includes('coarse'),
				media: query,
				onchange: null,
				addEventListener: vi.fn(),
				removeEventListener: vi.fn(),
				addListener: vi.fn(),
				removeListener: vi.fn(),
				dispatchEvent: vi.fn()
			}))
		);
		const { target: coarse } = await render();
		expect(coarse.textContent).toContain(TAKES_MOBILE_HINT);

		vi.stubGlobal(
			'matchMedia',
			vi.fn((query: string) => ({
				matches: false,
				media: query,
				onchange: null,
				addEventListener: vi.fn(),
				removeEventListener: vi.fn(),
				addListener: vi.fn(),
				removeListener: vi.fn(),
				dispatchEvent: vi.fn()
			}))
		);
		const { target: fine } = await render();
		expect(fine.textContent).not.toContain(TAKES_MOBILE_HINT);
		vi.unstubAllGlobals();
	});
});

describe('Escape yields to the take overflow menu before any global shortcut', () => {
	it('closes the overflow menu on Escape without leaking to a document listener', async () => {
		const { target } = await render();
		target
			.querySelector<HTMLElement>('.take-row')
			?.querySelector<HTMLButtonElement>('.overflow-btn')
			?.click();
		await tick();
		expect(target.querySelector('.overflow-menu')).not.toBeNull();
		document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
		await tick();
		expect(target.querySelector('.overflow-menu')).toBeNull();
	});
});
