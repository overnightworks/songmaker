import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, expect } from 'vitest';
import { playlistList, playlistLoad, resetPlaylists } from '$lib/stores/playlists';
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
	resetPlaylists();
	document.body.replaceChildren();
});

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
