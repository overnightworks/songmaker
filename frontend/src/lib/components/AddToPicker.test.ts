import { makePlaylist as playlist } from '#lib/test-utils/factories.ts';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { playlistList, playlistLoad, resetPlaylistsForTests } from '#lib/stores/playlists.ts';
import { addToast } from '#lib/stores/toast.ts';
import { words } from '#lib/words/en.ts';

const createPlaylist = vi.fn();
const fetchPlaylists = vi.fn();

vi.mock('#lib/api/client.ts', () => ({
	createPlaylist: (...args: unknown[]) => createPlaylist(...args),
	fetchPlaylists: (...args: unknown[]) => fetchPlaylists(...args)
}));
vi.mock('#lib/stores/toast.ts', () => ({ addToast: vi.fn(), dismissToast: vi.fn() }));

import AddToPicker from './AddToPicker.svelte';

let mounted: ReturnType<typeof mount> | undefined;
let target: HTMLElement;
let onselect = vi.fn<(playlistId: string) => void>();
let onback = vi.fn<() => void>();

beforeEach(() => {
	playlistList.set([
		playlist({ id: 'p-night', title: 'Night Drive', entry_count: 3 }),
		playlist({ id: 'p-run', title: 'Morning Run', entry_count: 0 })
	]);
	playlistLoad.set({ status: 'ready', error: null });
	createPlaylist.mockReset();
	fetchPlaylists.mockReset();
	vi.mocked(addToast).mockClear();
	onselect = vi.fn<(playlistId: string) => void>();
	onback = vi.fn<() => void>();
	target = document.createElement('div');
	document.body.append(target);
});

afterEach(() => {
	if (mounted) void unmount(mounted);
	mounted = undefined;
	resetPlaylistsForTests();
	document.body.replaceChildren();
});

async function showPicker(excludePlaylistId?: string): Promise<void> {
	mounted = mount(AddToPicker, { target, props: { onselect, onback, excludePlaylistId } });
	await tick();
}

function newPlaylistField(): HTMLInputElement {
	const field = target.querySelector<HTMLInputElement>('input[type="text"]');
	if (!field) throw new Error('Expected the New playlist field');
	return field;
}

async function typeInto(field: HTMLInputElement, text: string, key?: string): Promise<void> {
	field.value = text;
	field.dispatchEvent(new Event('input', { bubbles: true }));
	if (key) field.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
	await tick();
	await Promise.resolve();
	await tick();
}

describe('AddToPicker', () => {
	it('lists every playlist with its title and entry count under the Add to heading', async () => {
		await showPicker();

		expect(target.textContent).toContain(words['addToPicker.heading']);
		expect(
			Array.from(target.querySelectorAll('.menu-picker-row'), (row) => ({
				title: row.querySelector('.ap-title')?.textContent,
				count: row.querySelector('.ap-count')?.textContent
			}))
		).toEqual([
			{ title: 'Night Drive', count: '3' },
			{ title: 'Morning Run', count: '0' }
		]);
	});

	it('leaves out the playlist the host is adding from', async () => {
		await showPicker('p-night');

		expect(
			Array.from(
				target.querySelectorAll('.menu-picker-row .ap-title'),
				(title) => title.textContent
			)
		).toEqual(['Morning Run']);
	});

	it('says it is loading while no playlist has arrived', async () => {
		playlistList.set([]);
		playlistLoad.set({ status: 'idle', error: null });
		fetchPlaylists.mockReturnValue(new Promise(() => undefined));
		await showPicker();

		expect(target.querySelector('[role="status"]')?.textContent).toBe(words['addToPicker.loading']);
	});

	it('hands the chosen playlist to its host', async () => {
		await showPicker();
		target.querySelectorAll<HTMLButtonElement>('.menu-picker-row')[1]?.click();

		expect(onselect).toHaveBeenCalledWith('p-run');
	});

	it('goes back to the menu rows from the back button', async () => {
		await showPicker();
		target.querySelector<HTMLButtonElement>('.menu-picker-back')?.click();

		expect(onback).toHaveBeenCalledTimes(1);
	});

	it('creates a playlist from the New playlist field on Enter and adds to it', async () => {
		createPlaylist.mockResolvedValue(playlist({ id: 'p-new', title: 'Road Trip' }));
		await showPicker();
		await typeInto(newPlaylistField(), '  Road Trip ', 'Enter');

		expect(createPlaylist).toHaveBeenCalledWith('Road Trip');
		expect(onselect).toHaveBeenCalledWith('p-new');
	});

	it('creates nothing from an empty field', async () => {
		await showPicker();
		await typeInto(newPlaylistField(), '   ', 'Enter');

		expect(createPlaylist).not.toHaveBeenCalled();
		expect(onselect).not.toHaveBeenCalled();
	});

	it('toasts and adds nothing when the playlist cannot be created', async () => {
		createPlaylist.mockRejectedValue(new Error('boom'));
		await showPicker();
		await typeInto(newPlaylistField(), 'Road Trip', 'Enter');

		expect(addToast).toHaveBeenCalledWith(words['addToPicker.createFailed'], 'error');
		expect(onselect).not.toHaveBeenCalled();
	});
});
