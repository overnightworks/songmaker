import { mount, tick, unmount } from 'svelte';
import { get } from 'svelte/store';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { LibraryWriteItem } from '#lib/api/types.ts';
import {
	HOME_WRITE_EMPTY,
	HOME_WRITE_ERROR,
	HOME_WRITE_LOADING,
	homeWriteOpenLabel,
	songEditorOpenLabel
} from '#lib/constants.ts';
import {
	ensureLibraryWriteRead,
	outdateLibraryWrite,
	resetLibraryWriteForTests
} from '#lib/stores/libraryWrite.ts';
import {
	reportSessionCheckReachable,
	resetConnectivityForTests
} from '#lib/stores/connectivity.ts';
import { selectedSongId } from '#lib/stores/player.ts';
import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import { makeSong } from '#lib/test-utils/factories.ts';
import { songList, resetLibraryDataForTests } from '#lib/stores/libraryData.ts';
import HomeWrite from './HomeWrite.svelte';

const writeFetch = vi.fn<typeof globalThis.fetch>();
const writtenSong = (overrides: Partial<LibraryWriteItem> = {}): LibraryWriteItem => ({
	song_id: 'song',
	song_title: 'Quiet Fire',
	album_id: 'album',
	album_title: 'Cold Harbour',
	work: 'lyrics',
	worked_at: new Date().toISOString(),
	...overrides
});
let writeComponent: ReturnType<typeof mount> | undefined;
const writeTitles = () =>
	[...document.querySelectorAll('.tile-title')].map((node) => node.textContent);
async function showWrite(): Promise<void> {
	writeComponent = mount(HomeWrite, { target: document.body });
	await tick();
}
async function settleWrite(): Promise<void> {
	await ensureLibraryWriteRead();
	await tick();
}
function holdWriteAnswer(): (items: LibraryWriteItem[]) => void {
	let resolve!: (response: Response) => void;
	writeFetch.mockReturnValueOnce(
		new Promise<Response>((done) => {
			resolve = done;
		})
	);
	return (items) => resolve(Response.json({ items }));
}
beforeEach(() => {
	resetLibraryWriteForTests();
	resetConnectivityForTests();
	writeFetch.mockReset().mockResolvedValue(Response.json({ items: [writtenSong()] }));
	vi.stubGlobal('fetch', writeFetch);
});
afterEach(async () => {
	if (writeComponent) await unmount(writeComponent);
	writeComponent = undefined;
	document.body.replaceChildren();
	resetLibraryWriteForTests();
	resetLibraryDataForTests();
	resetConnectivityForTests();
	selectedSongId.set(null);
	vi.unstubAllGlobals();
	Reflect.deleteProperty(document, 'visibilityState');
});

it.each([
	['created', 'new song'],
	['lyrics', 'lyrics edited'],
	['style', 'style edited'],
	['renamed', 'renamed'],
	['take', 'new take'],
	['cowriter', 'co-writer'],
	['edited', 'edited']
] as const)('1354_rule_14 shows album context and %s work as %s', async (work, label) => {
	writeFetch.mockResolvedValue(Response.json({ items: [writtenSong({ work })] }));
	await showWrite();
	await settleWrite();
	expect(document.querySelector('.tile-subtitle')).toHaveTextContent(
		`Cold Harbour · ${label} · today`
	);
});

it.each([
	['song', 'Cold Harbour', null],
	['album', 'Cold Harbour', null],
	['initials', 'Cold Harbour', 'CH'],
	['initials', 'Open Windows', 'OW']
] as const)(
	'1354_rule_14 uses the %s cover fallback for album %s',
	async (source, albumTitle, initials) => {
		const cover = { thumb: '/song.webp', card: '/song.webp', detail: '/song.webp' };
		const albumCover = { thumb: '/album.webp', card: '/album.webp', detail: '/album.webp' };
		writeFetch.mockResolvedValue(
			Response.json({
				items: [
					writtenSong({
						album_title: albumTitle,
						cover: source === 'song' ? cover : null,
						album_cover: source === 'initials' ? null : albumCover
					})
				]
			})
		);
		await showWrite();
		await settleWrite();
		if (source === 'initials')
			expect(document.querySelector('.tile-cover')?.textContent?.trim()).toBe(initials);
		else expect(document.querySelector('img')).toHaveAttribute('src', `/${source}.webp`);
	}
);

it('1354_rule_14 preserves server order and reuses a fresh answer on remount', async () => {
	writeFetch.mockResolvedValue(
		Response.json({
			items: ['b', 'a', 'c'].map((id) => writtenSong({ song_id: id, song_title: id }))
		})
	);
	await showWrite();
	await settleWrite();
	expect(writeTitles()).toEqual(['b', 'a', 'c']);
	if (!writeComponent) throw new Error('Write is not mounted');
	await unmount(writeComponent);
	writeComponent = undefined;
	await showWrite();
	await settleWrite();
	expect(writeTitles()).toEqual(['b', 'a', 'c']);
	expect(writeFetch).toHaveBeenCalledTimes(1);
});

it('1354_rule_18 distinguishes initial loading from a successful empty answer', async () => {
	const resolve = holdWriteAnswer();
	await showWrite();
	expect(document.querySelector('[role="status"]')).toHaveTextContent(HOME_WRITE_LOADING);
	expect(document.body).not.toHaveTextContent(HOME_WRITE_EMPTY);
	resolve([]);
	await settleWrite();
	expect(document.body).toHaveTextContent(HOME_WRITE_EMPTY);
	expect(document.querySelector('[role="status"]')).toBeNull();
});

it('1354_rule_19 offers a pending-safe Retry for an initial failure', async () => {
	writeFetch.mockRejectedValueOnce(new TypeError('offline'));
	await showWrite();
	await settleWrite();
	expect(document.querySelector('[role="alert"]')).toHaveTextContent(HOME_WRITE_ERROR);
	expect(document.body).not.toHaveTextContent(HOME_WRITE_EMPTY);
	const resolve = holdWriteAnswer();
	const retry = document.querySelector('button');
	if (!retry) throw new Error('Retry is missing');
	retry.click();
	await tick();
	expect(retry).toBeDisabled();
	resolve([writtenSong()]);
	await settleWrite();
	expect(writeTitles()).toEqual(['Quiet Fire']);
	expect(document.querySelector('[role="alert"]')).toBeNull();
});

it.each([false, true])(
	'1354_rule_19 retains a cached answer (empty: %s) during a failed refresh',
	async (empty) => {
		writeFetch.mockResolvedValueOnce(Response.json({ items: empty ? [] : [writtenSong()] }));
		await showWrite();
		await settleWrite();
		const resolve = holdWriteAnswer();
		outdateLibraryWrite();
		const read = ensureLibraryWriteRead();
		await tick();
		expect(document.body).toHaveTextContent(empty ? HOME_WRITE_EMPTY : 'Quiet Fire');
		resolve(empty ? [] : [writtenSong()]);
		await read;
		writeFetch.mockRejectedValueOnce(new TypeError('offline'));
		outdateLibraryWrite();
		await settleWrite();
		expect(document.body).toHaveTextContent(empty ? HOME_WRITE_EMPTY : 'Quiet Fire');
		expect(document.body).not.toHaveTextContent(HOME_WRITE_ERROR);
	}
);

it.each(['foreground', 'reconnect'] as const)(
	'1354_rule_19 refreshes on %s and unsubscribes on unmount',
	async (trigger) => {
		await showWrite();
		await settleWrite();
		const notify = () => {
			if (trigger === 'reconnect') {
				reportSessionCheckReachable(false);
				reportSessionCheckReachable(true);
			} else {
				Object.defineProperty(document, 'visibilityState', {
					configurable: true,
					value: 'visible'
				});
				document.dispatchEvent(new Event('visibilitychange'));
			}
		};
		Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
		document.dispatchEvent(new Event('visibilitychange'));
		await tick();
		expect(writeFetch).toHaveBeenCalledTimes(1);
		writeFetch.mockResolvedValue(Response.json({ items: [writtenSong({ song_title: 'Fresh' })] }));
		notify();
		await settleWrite();
		expect(writeTitles()).toEqual(['Fresh']);
		expect(writeFetch).toHaveBeenCalledTimes(2);
		if (!writeComponent) throw new Error('Write is not mounted');
		await unmount(writeComponent);
		writeComponent = undefined;
		notify();
		await tick();
		expect(writeFetch).toHaveBeenCalledTimes(2);
	}
);

it.each([
	{ selector: '.wall-tile-body', name: homeWriteOpenLabel('Quiet Fire') },
	{ selector: '.row-editor', name: songEditorOpenLabel('Quiet Fire') }
])(
	'1354_rule_16 defect:#1575 $selector, named apart as $name, selects the song without changing playback',
	async ({ selector, name }) => {
		songList.set([makeSong({ id: 'song', album_id: 'album' })]);
		await showWrite();
		await settleWrite();
		writeFetch.mockResolvedValue(Response.json([]));
		const playback = audioPlayer.current;
		const status = audioPlayer.status;
		const action = document.querySelector<HTMLButtonElement>(selector);
		if (!action) throw new Error('Write action is missing');
		expect(action).toHaveAccessibleName(name);
		action.click();
		await vi.waitFor(() => expect(get(selectedSongId)).toBe('song'));
		expect(audioPlayer.current).toBe(playback);
		expect(audioPlayer.status).toBe(status);
	}
);
