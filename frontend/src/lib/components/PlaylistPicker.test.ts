import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { playlistList, playlistLoad, resetPlaylistsForTests } from '$lib/stores/playlists';
import { describeBackClosesOverlay, plannedHistoryIndex } from '$lib/test-utils/library-history';
import PlaylistPicker from './PlaylistPicker.svelte';

const NIGHT_DRIVE = {
	id: 'playlist-1',
	title: 'Night Drive',
	slug: 'night-drive',
	entry_count: 3,
	is_shared: false,
	album_covers: [],
	created_at: '2026-09-30T00:00:00Z'
};

// The picker as a song page shows it: choosing a playlist or closing it hides it.
const picker = {
	added: [] as string[],
	addSawHistoryAt: undefined as number | undefined,
	shown: null as ReturnType<typeof mount> | null,
	open(target: HTMLElement): void {
		picker.added = [];
		picker.addSawHistoryAt = undefined;
		picker.shown = mount(PlaylistPicker, {
			target,
			props: {
				onselect: (playlistId: string) => {
					picker.added.push(playlistId);
					picker.addSawHistoryAt = plannedHistoryIndex();
					picker.hide();
				},
				onclose: picker.hide
			}
		});
	},
	hide(): void {
		if (picker.shown) void unmount(picker.shown);
		picker.shown = null;
	}
};

beforeEach(() => {
	playlistList.set([NIGHT_DRIVE]);
	playlistLoad.set({ status: 'ready', error: null });
});

afterEach(() => {
	picker.hide();
	resetPlaylistsForTests();
	document.body.replaceChildren();
});

it('defect:#1444 lists every supplied playlist with its title and entry count', async () => {
	playlistList.set([
		NIGHT_DRIVE,
		{ ...NIGHT_DRIVE, id: 'playlist-2', title: 'Morning Run', slug: 'morning-run', entry_count: 0 }
	]);
	const target = document.createElement('div');
	document.body.append(target);
	picker.open(target);
	await tick();

	expect(
		Array.from(target.querySelectorAll('.picker-item'), (item) => ({
			title: item.querySelector('.picker-title')?.textContent,
			count: item.querySelector('.picker-count')?.textContent
		}))
	).toEqual([
		{ title: 'Night Drive', count: '3' },
		{ title: 'Morning Run', count: '0' }
	]);
});

describe('the playlist picker closes on history Back', () => {
	describeBackClosesOverlay({
		name: 'the playlist picker',
		render: async () => {
			const target = document.createElement('div');
			document.body.append(target);
			await tick();
			return target;
		},
		open: picker.open,
		isShown: (target) => target.querySelector('[role="dialog"]') !== null,
		afterBack: () => expect(picker.added).toEqual([]),
		closeWays: [
			{
				way: 'choosing a playlist',
				close: (target) => target.querySelector<HTMLButtonElement>('.picker-item')?.click(),
				actionSawHistoryAt: () => picker.addSawHistoryAt
			},
			{ way: 'a click outside it', close: () => document.body.click() },
			{
				way: 'Escape',
				close: () =>
					document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
			}
		]
	});
});
