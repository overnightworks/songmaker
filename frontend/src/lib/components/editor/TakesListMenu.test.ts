import { tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { clearHitboxStyles, clearPointer, injectHitboxStyles } from '#lib/test-utils/hitbox.ts';
import { selectedSongId } from '#lib/stores/player.ts';
import { clearSelection } from '#lib/stores/selection.ts';

vi.mock('#lib/api/client.ts', async (importOriginal) => {
	const actual = await importOriginal<typeof import('#lib/api/client.ts')>();
	return {
		...actual,
		bulkDeleteGenerations: vi.fn(),
		cancelJob: vi.fn(),
		fetchSong: vi.fn(),
		deleteVersion: vi.fn(),
		fetchVersions: vi.fn().mockResolvedValue([])
	};
});
vi.mock('#lib/stores/toast.ts', () => ({ addToast: vi.fn() }));
const generateState = await vi.hoisted(async () => {
	const { writable } = await import('svelte/store');
	return writable<GenerateState>({ kind: 'idle' });
});
vi.mock('#lib/stores/generateAction.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/stores/generateAction.ts')>()),
	generateAction: generateState
}));
vi.mock('#lib/stores/navigation.ts', async (importOriginal) => {
	const actual = await importOriginal<typeof import('#lib/stores/navigation.ts')>();
	return { ...actual, persistLibraryHistory: vi.fn() };
});
vi.mock('#lib/stores/player.ts', async (importOriginal) => {
	const actual = await importOriginal<typeof import('#lib/stores/player.ts')>();
	return {
		...actual,
		playTake: vi.fn(async () => undefined),
		playTakeAndShowNowPlaying: vi.fn(async () => undefined)
	};
});

import { addToast } from '#lib/stores/toast.ts';
import type { GenerateState } from '#lib/stores/generateAction.ts';
import { activeJobs, generationFailures } from '#lib/stores/jobs.ts';
import { playTake, playTakeAndShowNowPlaying } from '#lib/stores/player.ts';
import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import { playlistList, playlistLoad } from '#lib/stores/playlists.ts';
import {
	IDLE,
	addToPlaylist,
	clickMenuItem,
	clickVersion,
	keep,
	mounted,
	openTakeMenu,
	pick,
	playlist,
	render,
	useSeed
} from '#lib/test-utils/takes-list.ts';
import { words } from '#lib/words/en.ts';

vi.mock('#lib/stores/playlists.ts', async (importOriginal) => {
	const actual = await importOriginal<typeof import('#lib/stores/playlists.ts')>();
	return { ...actual, ensurePlaylistsLoaded: vi.fn(async () => undefined) };
});

let songSequence = 0;

beforeEach(() => {
	pick.mockReset();
	keep.mockReset();
	useSeed.mockReset();
	clickVersion.mockClear();
	addToPlaylist.mockClear();
	playlistList.set([{ ...playlist }]);
	playlistLoad.set({ status: 'ready', error: null });
	vi.mocked(addToast).mockClear();
	vi.mocked(playTake).mockClear();
	vi.mocked(playTakeAndShowNowPlaying).mockClear();
	activeJobs.set([]);
	generationFailures.set({});
	// The scoring job streams its progress over server-sent events jsdom does
	// not implement.
	vi.stubGlobal(
		'EventSource',
		class {
			close(): void {}
		}
	);
	selectedSongId.set(`song-${(songSequence += 1)}`);
	clearSelection();
	audioPlayer.current = null;
	audioPlayer.status = 'idle';
	injectHitboxStyles();
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	audioPlayer.current = null;
	audioPlayer.status = 'idle';
	clearHitboxStyles();
	clearPointer();
	activeJobs.set([]);
	generationFailures.set({});
	generateState.set(IDLE);
	vi.unstubAllGlobals();
	clearSelection();
});

describe('TakesList menu', () => {
	it("names the take on the row's menu, without also playing it", async () => {
		const { target } = await render();
		const row = target.querySelector<HTMLElement>('.take-row');
		row?.querySelector<HTMLButtonElement>('.menu-trigger')?.click();
		await tick();
		expect(target.querySelector('.menu-heading')?.textContent).toBe(
			words['takeMenu.headingWithVersion']({ version: '3', take: '3' })
		);
		expect(playTake).not.toHaveBeenCalled();
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
		clickMenuItem(row, words['takeMenu.addToPlaylist']);
		await tick();

		const picker = row.querySelector('.picker');
		expect(picker, 'the playlist picker renders inside the take row').not.toBeNull();
		expect(picker?.parentElement?.classList.contains('take-picker-anchor')).toBe(true);

		row.querySelector<HTMLButtonElement>('.picker-item')?.click();
		await tick();
		await Promise.resolve();

		expect(addToPlaylist).toHaveBeenCalledWith('p1', 'g1');
		expect(playTake).not.toHaveBeenCalled();
	});
});

describe('Escape yields to the take overflow menu before any global shortcut', () => {
	it('closes the overflow menu on Escape without leaking to a document listener', async () => {
		const { target } = await render();
		target
			.querySelector<HTMLElement>('.take-row')
			?.querySelector<HTMLButtonElement>('.menu-trigger')
			?.click();
		await tick();
		expect(target.querySelector('.menu-panel')).not.toBeNull();
		document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
		await tick();
		expect(target.querySelector('.menu-panel')).toBeNull();
	});
});
