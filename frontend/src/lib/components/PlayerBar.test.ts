import {
	makeAlbum as albumItem,
	makeGeneration,
	makeSong,
	makePlaylistEntry,
	makePlaylistDetail as playlistItem
} from '#lib/test-utils/factories.ts';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from 'vitest';
import type { QueueStreamManifest, QueueStreamTrackItem } from '#lib/api/types.ts';
import {
	NOW_PLAYING_LABEL,
	MINI_PLAYER_WITHOUT_COVER_MEDIA,
	NOW_PLAYING_SWIPE_RISE_PX,
	OFFLINE_STRIP_MESSAGE,
	openNowPlayingLabel,
	PLAYER_WAITING_FOR_NETWORK,
	LIBRARY_PAGE_LABEL,
	REDUCED_MOTION_MEDIA,
	TRANSPORT_PAUSE_LABEL,
	TRANSPORT_PLAY_LABEL,
	TRANSPORT_RETRY_LABEL
} from '#lib/constants.ts';
import {
	audioPlayer,
	STALL_RECOVERY_MS,
	type PlaybackInfo
} from '#lib/services/audioPlayer.svelte.ts';
import type { PlaylistDetailItem } from '#lib/api/types.ts';
import { albumList, songList } from '#lib/stores/libraryData.ts';
import {
	closeNowPlaying,
	nowPlayingDockable,
	nowPlayingSurface,
	playStartNotice,
	queueContext,
	selectedAlbumId,
	selectedSongId,
	setPendingStartForTests,
	setShuffle,
	shuffleEnabled
} from '#lib/stores/player.ts';
import * as playerStore from '#lib/stores/player.ts';
import { dismissToast, toasts } from '#lib/stores/toast.ts';
import { openCollection } from '#lib/stores/collection.ts';
import { selectedPlaylistDetail } from '#lib/stores/playlists.ts';
import { watchTypingOnPhone } from '#lib/stores/ui.ts';
import {
	reportResourceStreamReachable,
	resetConnectivityForTests
} from '#lib/stores/connectivity.ts';
import { get } from 'svelte/store';
import { LIBRARY_QUEUE_EMPTY_TITLE, LIBRARY_QUEUE_LOADING_TITLE } from '#lib/constants.ts';
import PlayerBar from './PlayerBar.svelte';
import { openOnScreenKeyboard } from '#lib/test-utils/on-screen-keyboard.ts';
import { browserReportsOnline } from '#lib/test-utils/network.ts';
import { nowPlayingFromLabel, nowPlayingTakeLabel } from '#lib/constants/now-playing.ts';

function playablePlaylistDefaults(): Partial<PlaylistDetailItem> {
	return {
		share_slug: null,
		entries: [
			makePlaylistEntry({ song_title: 'Tide', album_title: 'Nachtstrom', mp3_path: 'tide.mp3' })
		]
	};
}

class FakeAudio {
	paused = true;
	currentTime = 0;
	duration = 20;
	readyState = 1;
	src = '';
	preload = '';
	crossOrigin: string | null = null;
	buffered = { length: 0, end: () => 0 };
	ended = false;
	error: MediaError | null = null;
	private listeners = new Map<string, Array<(event: Event) => void>>();

	addEventListener(name: string, listener: (event: Event) => void) {
		this.listeners.set(name, [...(this.listeners.get(name) ?? []), listener]);
	}
	load() {
		this.fire('loadstart');
	}
	play() {
		this.paused = false;
		this.fire('play');
		return Promise.resolve();
	}
	pause() {
		this.paused = true;
		this.fire('pause');
	}
	removeAttribute() {}
	fire(name: string) {
		for (const listener of this.listeners.get(name) ?? []) listener({ type: name } as Event);
	}
}

function track(index: number, overrides: Partial<QueueStreamTrackItem> = {}): QueueStreamTrackItem {
	return {
		key: `entry-${index}`,
		index,
		entry_id: `entry-${index}`,
		generation_id: 'same-generation',
		song_id: 'same-song',
		song_title: 'Repeated take',
		artist: 'Artist',
		album_title: 'Album',
		lyrics: 'old verse',
		generation_number: 1,
		mp3_path: 'take.mp3',
		audio_url: '/audio/take.mp3',
		seed: null,
		model_mode: 'sft',
		duration: 10,
		start_offset: index * 10,
		end_offset: (index + 1) * 10,
		...overrides
	};
}

function manifest(tracks: QueueStreamTrackItem[]): QueueStreamManifest {
	return {
		snapshot_id: 'snapshot',
		stream_url: '/stream.mp3',
		expires_at: '2099-01-01T00:00:00Z',
		total_duration: tracks.reduce((total, item) => total + item.duration, 0),
		tracks,
		windowed: true,
		skipped: [],
		skipped_complete: true
	};
}

function useDesktopLayout(): void {
	vi.stubGlobal(
		'matchMedia',
		vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
	);
}

function barTake(songTitle = 'Opening Move'): PlaybackInfo {
	return {
		generation: makeGeneration({
			version_number: 7,
			generation_number: 2,
			mp3_path: 'take.mp3'
		}),
		songId: 's1',
		songTitle,
		artist: 'Artist',
		albumTitle: 'Album',
		lyrics: null
	};
}

function loadTake(songTitle?: string): void {
	audioPlayer.load(barTake(songTitle), { autoplay: false });
}

interface FakeLockScreen {
	playbackState: MediaSessionPlaybackState;
	// Every position state the lock screen was given; null clears it.
	positions: (MediaPositionState | null)[];
	setPositionState: (state?: MediaPositionState) => void;
}

function installLockScreen(): FakeLockScreen {
	const lockScreen: FakeLockScreen = {
		playbackState: 'none',
		positions: [],
		setPositionState(state) {
			this.positions.push(state ?? null);
		}
	};
	Object.defineProperty(navigator, 'mediaSession', { configurable: true, value: lockScreen });
	onTestFinished(() => {
		Reflect.deleteProperty(navigator, 'mediaSession');
	});
	return lockScreen;
}

const WAITING_SONG = { songTitle: 'Opening Move', artist: 'Artist', albumTitle: 'Nachtstrom' };

// An album header start that could not read its takes offline, as the player
// store holds it: the bar names its song, and the lock screen does too.
function holdAlbumStart(notice: 'awaiting-network' | 'gave-up-on-network' | 'idle'): void {
	openCollection.set({ kind: 'album', id: 'a1' });
	albumList.set([albumItem({ share_slug: null, cover: null })]);
	setPendingStartForTests({ albumId: 'a1', song: WAITING_SONG });
	playStartNotice.set(notice);
}

// A take of another album, loaded and paused, as after a reload or a pause
// before the listener opened the album that now waits.
function loadPausedTake(): void {
	audioPlayer.load(barTake('Earlier Song'), { autoplay: false });
}

const RESTORED_POSITION = 13;
const PAST_THE_STALL_CHECK_MS = STALL_RECOVERY_MS + 1;

let component: ReturnType<typeof mount> | undefined;
let target: HTMLDivElement;
let audio: FakeAudio;
let audioContextConstructor: ReturnType<typeof vi.fn>;

beforeEach(() => {
	target = document.createElement('div');
	document.body.appendChild(target);
	audio = new FakeAudio();
	audioContextConstructor = vi.fn();
	vi.stubGlobal(
		'Audio',
		vi.fn(function () {
			return audio;
		})
	);
	vi.stubGlobal('AudioContext', audioContextConstructor);
	vi.stubGlobal(
		'matchMedia',
		vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
	);
	vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
	songList.set([]);
	albumList.set([]);
	queueContext.set({
		type: 'playlist',
		playlist: { id: 'p1', title: 'Night Drive' },
		entries: [],
		index: 0
	});
	selectedAlbumId.set(null);
	selectedSongId.set(null);
	selectedPlaylistDetail.set(null);
	openCollection.set(null);
	playStartNotice.set('idle');
	setPendingStartForTests(null);
	nowPlayingSurface.set('closed');
	nowPlayingDockable.set(false);
	setShuffle(false);
});

afterEach(async () => {
	if (component) await unmount(component);
	component = undefined;
	audioPlayer.destroy();
	document.body.replaceChildren();
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

describe('PlayerBar stream boundaries', () => {
	it('names the library, never the take pool, as the idle Play target with no collection open', async () => {
		queueContext.set({ type: 'library' });
		openCollection.set(null);
		selectedPlaylistDetail.set(null);
		const playIdleStart = vi.spyOn(playerStore, 'playIdleStart').mockResolvedValue();
		component = mount(PlayerBar, { target });
		await tick();

		expect(audioPlayer.current).toBeNull();
		const play = target.querySelector<HTMLButtonElement>('button[aria-label="Play"]');
		expect(play?.disabled).toBe(false);
		expect(target.querySelector('.track-title')?.textContent).toBe(LIBRARY_PAGE_LABEL);
		play?.click();
		expect(playIdleStart).toHaveBeenCalledOnce();
	});

	it.each([
		{ loaded: 'no take', load: () => {} },
		{ loaded: 'a paused take', load: loadPausedTake }
	])(
		'with $loaded loaded, a start that waits for the network shows the waiting transport, and a press goes to the start (#1288, #1330)',
		async ({ load }) => {
			load();
			holdAlbumStart('awaiting-network');
			const playIdleStart = vi.spyOn(playerStore, 'playIdleStart').mockResolvedValue();
			component = mount(PlayerBar, { target });
			await tick();

			const transport = target.querySelector<HTMLButtonElement>('button[aria-label="Pause"]');
			expect(transport?.querySelector('.spinner')).not.toBeNull();
			transport?.click();
			expect(playIdleStart).toHaveBeenCalledOnce();
		}
	);

	it.each([
		{ notice: 'awaiting-network', loaded: 'no take', load: () => {} },
		{ notice: 'gave-up-on-network', loaded: 'no take', load: () => {} },
		{ notice: 'awaiting-network', loaded: 'a paused take', load: loadPausedTake }
	] as const)(
		'while an album header start waits ($notice) with $loaded loaded, the bar names its song and album with Pause, as the lock screen does (#1330)',
		async ({ notice, load }) => {
			useDesktopLayout();
			load();
			holdAlbumStart(notice);
			component = mount(PlayerBar, { target });
			await tick();

			expect({
				title: target.querySelector('.track-title')?.textContent,
				detail: target.querySelector('.track-detail')?.textContent,
				main: playButton().getAttribute('aria-label'),
				timeReadouts: target.querySelectorAll('.timeline .time').length
			}).toEqual({
				title: WAITING_SONG.songTitle,
				detail: WAITING_SONG.albumTitle,
				main: TRANSPORT_PAUSE_LABEL,
				timeReadouts: 0
			});
		}
	);

	it("a start waiting over a take paused partway shows none of that take's position, on the phone's progress line or the lock screen (#1330)", async () => {
		const lockScreen = installLockScreen();
		loadPausedTake();
		component = mount(PlayerBar, { target });
		audio.currentTime = 5;
		audio.fire('loadedmetadata');
		audio.fire('timeupdate');
		await tick();
		const positionShown = () => ({
			progressLine: target.querySelector<HTMLElement>('.mobile-progress-fill')?.style.width,
			lockScreen: lockScreen.positions.at(-1)
		});
		const overThePausedTake = positionShown();

		holdAlbumStart('awaiting-network');
		await tick();

		expect({ overThePausedTake, whileTheStartWaits: positionShown() }).toEqual({
			overThePausedTake: {
				progressLine: '25%',
				lockScreen: { duration: 20, playbackRate: 1, position: 5 }
			},
			whileTheStartWaits: { progressLine: '0%', lockScreen: null }
		});
	});

	it('pausing a waiting album start leaves the album title with Play and no 0:00/0:00 (#1312)', async () => {
		useDesktopLayout();
		holdAlbumStart('awaiting-network');
		component = mount(PlayerBar, { target });
		await tick();

		playStartNotice.set('idle');
		setPendingStartForTests(null);
		await tick();

		expect({
			title: target.querySelector('.track-title')?.textContent,
			main: playButton().getAttribute('aria-label'),
			timeReadouts: target.querySelectorAll('.timeline .time').length
		}).toEqual({ title: 'Nachtstrom', main: TRANSPORT_PLAY_LABEL, timeReadouts: 0 });
	});

	describe('during the restore wait (#1312)', () => {
		async function mountRestoredTake(): Promise<HTMLButtonElement> {
			audioPlayer.load(barTake(), { autoplay: false, startAt: RESTORED_POSITION });
			component = mount(PlayerBar, { target });
			await tick();
			return playButton();
		}

		function buttonFacts(button: HTMLButtonElement) {
			return {
				label: button.getAttribute('aria-label'),
				busy: button.getAttribute('aria-busy'),
				spinner: button.querySelector('.spinner') !== null
			};
		}

		async function dataArrives(): Promise<void> {
			audio.fire('loadedmetadata');
			audio.fire('canplay');
			await tick();
		}

		const readsPlay = { label: TRANSPORT_PLAY_LABEL, busy: 'false', spinner: false };
		const readsBusyPause = { label: TRANSPORT_PAUSE_LABEL, busy: 'true', spinner: true };

		it('reads Pause with its spinner for a Play pressed before the saved take arrived (#1330)', async () => {
			playStartNotice.set('restoring');
			const playIdleStart = vi.spyOn(playerStore, 'playIdleStart').mockResolvedValue();
			component = mount(PlayerBar, { target });
			await tick();
			const whileItArrives = buttonFacts(playButton());

			await clickAndSettle();

			expect({ whileItArrives, pressGoesToTheStart: playIdleStart.mock.calls.length }).toEqual({
				whileItArrives: readsBusyPause,
				pressGoesToTheStart: 1
			});
		});

		it('the timeline shows the restored position while the take still loads (#1330)', async () => {
			useDesktopLayout();
			const take = barTake();
			audioPlayer.load(
				{ ...take, generation: { ...take.generation, audio_duration_sec: 180 } },
				{ autoplay: false, startAt: 73 }
			);
			component = mount(PlayerBar, { target });
			await tick();

			expect(
				[...target.querySelectorAll('.timeline .time')].map((time) => time.textContent)
			).toEqual(['1:13', '3:00']);
		});

		it('reads Play before any press, and Pause with its spinner after the first', async () => {
			const transport = await mountRestoredTake();
			const beforeAnyPress = buttonFacts(transport);
			await clickAndSettle(transport);

			expect({ beforeAnyPress, afterThePress: buttonFacts(transport) }).toEqual({
				beforeAnyPress: readsPlay,
				afterThePress: readsBusyPause
			});
		});

		it('a press on that Pause withdraws the ask, and the take stays paused at the restored position', async () => {
			const transport = await mountRestoredTake();
			await clickAndSettle(transport);
			await clickAndSettle(transport);
			const afterTheWithdrawal = buttonFacts(transport);

			await dataArrives();

			expect({ afterTheWithdrawal, playing: !audio.paused, position: audio.currentTime }).toEqual({
				afterTheWithdrawal: readsPlay,
				playing: false,
				position: RESTORED_POSITION
			});
		});

		it('Play again after the withdrawal plays from the restored position once the data arrives', async () => {
			const transport = await mountRestoredTake();
			await clickAndSettle(transport);
			await clickAndSettle(transport);
			await clickAndSettle(transport);
			const whileWaiting = buttonFacts(transport);

			await dataArrives();

			expect({ whileWaiting, playing: !audio.paused, position: audio.currentTime }).toEqual({
				whileWaiting: readsBusyPause,
				playing: true,
				position: RESTORED_POSITION
			});
		});

		it.each([
			{ moment: 'before any press', presses: 0 },
			{ moment: 'after a press withdrew the ask', presses: 2 }
		])(
			'still reads Play $moment when the data takes longer than the stall check, and stays paused when it arrives',
			async ({ presses }) => {
				vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
				onTestFinished(() => {
					vi.useRealTimers();
				});
				const transport = await mountRestoredTake();
				for (let press = 0; press < presses; press++) await clickAndSettle(transport);

				vi.advanceTimersByTime(PAST_THE_STALL_CHECK_MS);
				await tick();
				const pastTheStallCheck = buttonFacts(transport);
				await dataArrives();

				expect({ pastTheStallCheck, playing: !audio.paused }).toEqual({
					pastTheStallCheck: readsPlay,
					playing: false
				});
			}
		);
	});

	it.each([
		{
			start: 'waits for the network, like the bar (#1288)',
			notice: 'awaiting-network',
			reads: 'playing'
		},
		{
			start: 'was paused from the lock screen, like a paused take (#1330)',
			notice: 'idle',
			reads: 'paused'
		}
	] as const)(
		'the lock screen reads $reads while an album start $start',
		async ({ notice, reads }) => {
			const lockScreen = installLockScreen();
			holdAlbumStart(notice);
			component = mount(PlayerBar, { target });
			await tick();

			expect(lockScreen.playbackState).toBe(reads);
		}
	);

	it('idle Play copy follows an open album interior', async () => {
		openCollection.set({ kind: 'album', id: 'a1' });
		selectedSongId.set(null);
		selectedPlaylistDetail.set(null);
		albumList.set([albumItem({ share_slug: null, cover: null })]);
		vi.spyOn(playerStore, 'playIdleStart').mockResolvedValue();
		component = mount(PlayerBar, { target });
		await tick();
		expect(target.querySelector('.track-title')?.textContent).toBe('Nachtstrom');
		expect(target.textContent).toContain('Nachtstrom');
	});

	it('idle Play copy follows an open playlist interior', async () => {
		openCollection.set({ kind: 'playlist', id: 'p1' });
		selectedSongId.set(null);
		selectedPlaylistDetail.set(playlistItem(playablePlaylistDefaults()));
		vi.spyOn(playerStore, 'playIdleStart').mockResolvedValue();
		component = mount(PlayerBar, { target });
		await tick();
		expect(target.querySelector('.track-title')?.textContent).toBe('Night Drive');
		expect(target.textContent).toContain('Night Drive');
	});

	it('pressing Play on an empty playlist shows the no-takes notice', async () => {
		openCollection.set({ kind: 'playlist', id: 'p1' });
		selectedSongId.set(null);
		selectedPlaylistDetail.set(
			playlistItem({ ...playablePlaylistDefaults(), entry_count: 0, entries: [] })
		);
		component = mount(PlayerBar, { target });
		await tick();

		target.querySelector<HTMLButtonElement>('button[aria-label="Play"]')?.click();
		await vi.waitFor(() => expect(target.textContent).toContain(LIBRARY_QUEUE_EMPTY_TITLE));
		expect(target.textContent).toContain('Night Drive');
		expect(audioPlayer.current).toBeNull();

		selectedPlaylistDetail.set(playlistItem(playablePlaylistDefaults()));
		target.querySelector<HTMLButtonElement>('button[aria-label="Play"]')?.click();
		await vi.waitFor(() => expect(audioPlayer.current?.songTitle).toBe('Tide'));
		expect(target.textContent).not.toContain(LIBRARY_QUEUE_EMPTY_TITLE);
	});

	it('uses English loading and empty copy instead of German leftovers', async () => {
		queueContext.set({ type: 'library' });
		playStartNotice.set('building');
		component = mount(PlayerBar, { target });
		await tick();
		expect(target.textContent).toContain(LIBRARY_QUEUE_LOADING_TITLE);
		expect(target.textContent).not.toContain('Queue wird gebaut');
		playStartNotice.set('empty');
		await tick();
		expect(target.textContent).toContain(LIBRARY_QUEUE_EMPTY_TITLE);
		expect(target.textContent).not.toContain('Keine Takes');
	});

	it('reacts at window boundaries even when adjacent entries use the same generation', async () => {
		audioPlayer.loadStream(manifest([track(0), track(1)]), 0, { autoplay: false });
		component = mount(PlayerBar, { target });
		await tick();

		const previous = target.querySelector<HTMLButtonElement>('button[aria-label="Previous"]');
		const next = target.querySelector<HTMLButtonElement>('button[aria-label="Next"]');
		expect(previous?.disabled).toBe(true);
		expect(next?.disabled).toBe(false);

		audio.currentTime = 15;
		audio.fire('timeupdate');
		await tick();

		expect(previous?.disabled).toBe(false);
		expect(next?.disabled).toBe(true);

		audioPlayer.loadStream(manifest([track(0)]), 0, { autoplay: false });
		await tick();

		expect(previous?.disabled).toBe(true);
		expect(next?.disabled).toBe(true);
	});

	it('keeps Play enabled and queues one loading tap until canplay', async () => {
		audioPlayer.loadStream(manifest([track(0)]), 0, { autoplay: false });
		component = mount(PlayerBar, { target });
		await tick();
		const play = target.querySelector<HTMLButtonElement>('.play-btn');
		if (!play) throw new Error('Expected player Play button');
		const playSpy = vi.spyOn(audio, 'play');

		expect(play.disabled).toBe(false);
		play.click();
		await tick();
		await Promise.resolve();
		expect(playSpy).not.toHaveBeenCalled();

		audio.readyState = HTMLMediaElement.HAVE_FUTURE_DATA;
		audio.fire('canplay');
		await tick();

		expect(playSpy).toHaveBeenCalledOnce();
		expect(audioContextConstructor).not.toHaveBeenCalled();
	});
});

describe('1354_rule_41 desktop album navigation', () => {
	it.each([
		{ source: 'album', cached: true, restored: false },
		{ source: 'playlist', cached: false, restored: false },
		{ source: 'restored album', cached: false, restored: true }
	])('opens the song’s own album from $source playback', async ({ source, cached, restored }) => {
		useDesktopLayout();
		const song = makeSong({ album_id: 'own-album', generations: [makeGeneration()] });
		albumList.set([albumItem({ id: 'own-album', title: 'Album' })]);
		songList.set(cached ? [song] : []);
		if (source !== 'playlist') queueContext.set({ type: 'album', albumId: 'own-album' });
		vi.stubGlobal('fetch', async (input: RequestInfo | URL) => {
			const url = String(input);
			if (url === '/api/songs/s1') return Response.json(song);
			if (url.startsWith('/api/albums/own-album/songs')) {
				return Response.json({ items: [song], total: 1, has_more: false });
			}
			throw new Error(`Unexpected request: ${url}`);
		});
		audioPlayer.load(barTake(), { autoplay: false, startAt: restored ? RESTORED_POSITION : 0 });
		component = mount(PlayerBar, { target });
		await vi.waitFor(() => expect(target.querySelector('button.track-album')).not.toBeNull());

		const albumButton = target.querySelector<HTMLButtonElement>('button.track-album');
		if (!albumButton) throw new Error('Album action missing');
		expect(albumButton.textContent).toBe('Album');
		expect(albumButton.parentElement?.closest('button')).toBeNull();
		albumButton.click();
		await vi.waitFor(() => expect(get(openCollection)).toEqual({ kind: 'album', id: 'own-album' }));
		expect(audioPlayer.current?.songId).toBe('s1');
	});

	it.each([404, 503])(
		'keeps an unresolved album as plain text when lookup returns %s',
		async (status) => {
			useDesktopLayout();
			for (const toast of get(toasts)) dismissToast(toast.id);
			onTestFinished(() => {
				for (const toast of get(toasts)) dismissToast(toast.id);
			});
			vi.stubGlobal('fetch', async () => Response.json({ detail: 'Unavailable' }, { status }));
			loadTake();
			component = mount(PlayerBar, { target });
			await tick();
			await vi.waitFor(() =>
				expect(get(toasts).some((toast) => toast.type === 'error')).toBe(true)
			);

			expect(target.querySelector('span.track-album')?.textContent).toBe('Album');
			expect(target.querySelector('button.track-album')).toBeNull();
		}
	);

	it('keeps the phone track text free of a nested album action', async () => {
		songList.set([makeSong()]);
		loadTake();
		component = mount(PlayerBar, { target });
		await tick();

		expect(target.querySelector('.track-album')).toBeNull();
		expect(target.querySelector('.track-title')?.textContent).toBe('Opening Move');
	});
});

describe('PlayerBar take identifier', () => {
	// L9: the mini-player names the playing take through the one owner,
	// nowPlayingTakeLabel — never a second, ad-hoc format.
	it.each([
		[7, 'v7 · take 2'],
		[null, 'take 2']
	])('reads the take as %s from nowPlayingTakeLabel', async (versionNumber, expected) => {
		queueContext.set({ type: 'library' });
		audioPlayer.load(
			{
				generation: makeGeneration({
					version_number: versionNumber,
					generation_number: 2,
					mp3_path: 'take.mp3'
				}),
				songId: 's1',
				songTitle: 'AMIF',
				artist: 'Artist',
				albumTitle: 'Album',
				lyrics: null
			},
			{ autoplay: false }
		);
		component = mount(PlayerBar, { target });
		await tick();

		expect(target.querySelector('.track-detail')?.textContent).toContain(expected);
		expect(target.querySelector('.track-detail')?.textContent).not.toContain('Artist');
	});
});

describe('PlayerBar shuffle', () => {
	// #141/5: shuffle is transport, so it lives in the transport bar next to
	// prev/next — not only inside the Now Playing overlay.
	function shuffleButton(): HTMLButtonElement {
		const button = target.querySelector<HTMLButtonElement>('.shuffle-btn');
		if (!button) throw new Error('Expected a shuffle control in the transport bar');
		return button;
	}

	it('toggles shuffle from the transport bar and names the queue it would shuffle', async () => {
		useDesktopLayout();
		queueContext.set({ type: 'album', albumId: 'a1' });
		albumList.set([albumItem({ share_slug: null, cover: null })]);
		component = mount(PlayerBar, { target });
		await tick();

		expect(shuffleButton().getAttribute('aria-pressed')).toBe('false');
		expect(shuffleButton().getAttribute('aria-label')).toBe('Shuffle this album');

		shuffleButton().click();
		await tick();

		expect(get(shuffleEnabled)).toBe(true);
		expect(shuffleButton().getAttribute('aria-pressed')).toBe('true');
		expect(shuffleButton().getAttribute('aria-label')).toBe('Disable shuffle (this album)');
	});
});

function playButton(): HTMLButtonElement {
	const button = target.querySelector<HTMLButtonElement>('.play-btn');
	if (!button) throw new Error('Expected a play control in the transport bar');
	return button;
}

async function clickAndSettle(button: HTMLButtonElement = playButton()): Promise<void> {
	button.click();
	await tick();
	await Promise.resolve();
	await tick();
}

describe('PlayerBar transport labels', () => {
	it('names the transport button after the state its click leaves', async () => {
		audioPlayer.loadStream(manifest([track(0)]), 0, { autoplay: false });
		component = mount(PlayerBar, { target });
		await tick();
		expect(playButton().getAttribute('aria-label')).toBe(TRANSPORT_PLAY_LABEL);

		audio.readyState = HTMLMediaElement.HAVE_FUTURE_DATA;
		await clickAndSettle();
		audio.fire('canplay');
		await tick();
		expect(playButton().getAttribute('aria-label')).toBe(TRANSPORT_PAUSE_LABEL);

		await clickAndSettle();
		expect(playButton().getAttribute('aria-label')).toBe(TRANSPORT_PLAY_LABEL);

		vi.spyOn(audio, 'play').mockRejectedValue(new Error('decode failed'));
		await clickAndSettle();
		expect(playButton().getAttribute('aria-label')).toBe(TRANSPORT_RETRY_LABEL);
	});
});

describe('PlayerBar Now Playing', () => {
	beforeEach(useDesktopLayout);

	function nowPlayingButton(): HTMLButtonElement {
		const button = target.querySelector<HTMLButtonElement>(
			`button[aria-label="${NOW_PLAYING_LABEL}"]`
		);
		if (!button) throw new Error('Expected a Now Playing trigger in the transport bar');
		return button;
	}

	it('opens Now Playing, and puts the docked panel away again on a second press', async () => {
		nowPlayingDockable.set(true);
		audioPlayer.loadStream(manifest([track(0)]), 0, { autoplay: false });
		component = mount(PlayerBar, { target });
		await tick();
		// A panel in the page is a disclosure, not a dialog trigger.
		expect(nowPlayingButton().getAttribute('aria-expanded')).toBe('false');

		nowPlayingButton().click();
		await tick();
		expect(get(nowPlayingSurface)).toBe('docked');
		expect(nowPlayingButton().getAttribute('aria-expanded')).toBe('true');
		expect(nowPlayingButton().getAttribute('aria-haspopup')).toBeNull();

		nowPlayingButton().click();
		await tick();
		expect(get(nowPlayingSurface)).toBe('closed');
	});

	it('names the full surface a dialog, which the bar only ever opens', async () => {
		audioPlayer.loadStream(manifest([track(0)]), 0, { autoplay: false });
		component = mount(PlayerBar, { target });
		await tick();

		expect(nowPlayingButton().getAttribute('aria-haspopup')).toBe('dialog');
		nowPlayingButton().click();
		await tick();

		expect(get(nowPlayingSurface)).toBe('full');
	});

	// "One player, never two": the full surface carries the only transport.
	it('hides the transport bar under the full surface and brings it back on close', async () => {
		audioPlayer.loadStream(manifest([track(0)]), 0, { autoplay: false });
		component = mount(PlayerBar, { target });
		await tick();
		expect(target.querySelector('.player-bar')).not.toBeNull();

		target.querySelector<HTMLButtonElement>(`button[aria-label="${NOW_PLAYING_LABEL}"]`)?.click();
		await tick();

		expect(get(nowPlayingSurface)).toBe('full');
		expect(target.querySelector('.player-bar')).toBeNull();

		closeNowPlaying();
		await tick();
		expect(target.querySelector('.player-bar')).not.toBeNull();
	});

	it('keeps the transport bar while Now Playing is docked', async () => {
		nowPlayingDockable.set(true);
		audioPlayer.loadStream(manifest([track(0)]), 0, { autoplay: false });
		component = mount(PlayerBar, { target });
		await tick();

		target.querySelector<HTMLButtonElement>(`button[aria-label="${NOW_PLAYING_LABEL}"]`)?.click();
		await tick();

		expect(get(nowPlayingSurface)).toBe('docked');
		expect(target.querySelector('.player-bar')).not.toBeNull();
	});

	// The full surface unmounts the bar. If the bar owned the audio graph, that
	// would close the context bound to the playing <audio> element and silence
	// it for the rest of the session (browser gate on #140).
	it('leaves the playing element its audio graph when the bar makes way for the full surface', async () => {
		const analyser = {
			fftSize: 2048,
			smoothingTimeConstant: 0,
			frequencyBinCount: 1024,
			connect: vi.fn(),
			getByteFrequencyData: vi.fn(),
			getByteTimeDomainData: vi.fn()
		};
		const context = {
			state: 'running',
			destination: {},
			createAnalyser: vi.fn(() => analyser),
			createMediaElementSource: vi.fn(() => ({ connect: vi.fn() })),
			resume: vi.fn(),
			close: vi.fn()
		};
		audioContextConstructor.mockImplementation(function () {
			return context;
		});
		// A fine pointer on a wide viewport: the only shape that draws a
		// visualizer at all, and so the only one that builds a graph.
		vi.stubGlobal(
			'matchMedia',
			vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
		);
		audioPlayer.loadStream(manifest([track(0)]), 0, { autoplay: false });
		component = mount(PlayerBar, { target });
		await tick();

		audio.readyState = HTMLMediaElement.HAVE_FUTURE_DATA;
		target.querySelector<HTMLButtonElement>('.play-btn')?.click();
		await tick();
		audio.fire('canplay');
		await tick();
		await Promise.resolve();
		await tick();
		expect(context.createMediaElementSource).toHaveBeenCalledOnce();

		nowPlayingSurface.set('full');
		await tick();
		expect(target.querySelector('.player-bar')).toBeNull();
		expect(context.close).not.toHaveBeenCalled();

		closeNowPlaying();
		await tick();
		await Promise.resolve();
		await tick();

		// The remounted bar borrows the same analyser instead of rebuilding a
		// graph the element can never be handed to twice.
		expect(target.querySelector('.player-bar')).not.toBeNull();
		expect(context.createMediaElementSource).toHaveBeenCalledOnce();
		expect(audioContextConstructor).toHaveBeenCalledOnce();
	});

	it('returns focus to the transport bar trigger the bar remounts with', async () => {
		audioPlayer.loadStream(manifest([track(0)]), 0, { autoplay: false });
		component = mount(PlayerBar, { target });
		await tick();

		target.querySelector<HTMLButtonElement>(`button[aria-label="${NOW_PLAYING_LABEL}"]`)?.click();
		await tick();
		expect(target.querySelector('.player-bar')).toBeNull();

		closeNowPlaying();
		await tick();

		expect(document.activeElement).toBe(
			target.querySelector(`button[aria-label="${NOW_PLAYING_LABEL}"]`)
		);
	});
});

describe('PlayerBar mini player on the phone (#1058)', () => {
	function bar(): HTMLElement {
		const content = target.querySelector<HTMLElement>(
			'.player-bar.mobile-transport .player-content'
		);
		if (!content) throw new Error('Expected the phone mini player');
		return content;
	}

	function openTargets(): HTMLButtonElement[] {
		return Array.from(bar().querySelectorAll<HTMLButtonElement>('.open-now-playing'));
	}

	async function mountBar(): Promise<void> {
		component = mount(PlayerBar, { target });
		await tick();
	}

	it.each([
		{
			source: 'an album',
			arrange: () => {
				albumList.set([albumItem({ share_slug: null, cover: null, title: 'Nightdrive' })]);
				queueContext.set({ type: 'album', albumId: 'a1' });
			},
			line: nowPlayingFromLabel('Nightdrive'),
			hides: nowPlayingTakeLabel(7, 2)
		},
		{
			source: 'a playlist',
			arrange: () =>
				queueContext.set({
					type: 'playlist',
					playlist: { id: 'p1', title: 'Late Drives' },
					entries: [],
					index: 0
				}),
			line: nowPlayingFromLabel('Late Drives'),
			hides: nowPlayingTakeLabel(7, 2)
		},
		{
			source: 'the library',
			arrange: () => queueContext.set({ type: 'library' }),
			line: nowPlayingTakeLabel(7, 2),
			hides: nowPlayingFromLabel('')
		}
	])('names $source playing as "$line" under the title', async ({ arrange, line, hides }) => {
		arrange();
		loadTake();
		await mountBar();

		const detail = bar().querySelector('.track-detail')?.textContent;
		expect(bar().querySelector('.track-title')?.textContent).toBe('Opening Move');
		expect(detail).toContain(line);
		expect(detail).not.toContain(hides);
	});

	it('says where the music comes from by the queue, never by the page that is open', async () => {
		queueContext.set({
			type: 'playlist',
			playlist: { id: 'p1', title: 'Late Drives' },
			entries: [],
			index: 0
		});
		albumList.set([albumItem({ share_slug: null, cover: null, title: 'Nightdrive' })]);
		openCollection.set({ kind: 'album', id: 'a1' });
		loadTake();
		await mountBar();

		expect(bar().querySelector('.track-detail')?.textContent).toContain(
			nowPlayingFromLabel('Late Drives')
		);
	});

	it('reads open target · previous · play · next · open target, with no shuffle or chevron', async () => {
		loadTake();
		await mountBar();

		const targets = Array.from(bar().children).map(
			(child) => child.getAttribute('aria-label') ?? child.className.split(' ')[0]
		);
		expect(targets).toEqual([
			openNowPlayingLabel('Opening Move'),
			'transport-controls',
			'phone-side'
		]);
		const transport = Array.from(
			bar().querySelectorAll<HTMLButtonElement>('.transport-controls button')
		).map((button) => button.getAttribute('aria-label'));
		expect(transport).toEqual(['Previous', TRANSPORT_PLAY_LABEL, 'Next']);
		expect(target.querySelector('.shuffle-btn')).toBeNull();
		expect(target.querySelector('.now-playing-btn')).toBeNull();
	});

	it.each([
		{ viewport: 'narrower than the cover needs', narrow: true, covers: 0 },
		{ viewport: 'wide enough for the cover', narrow: false, covers: 1 }
	])('gives the title the whole open target on a phone $viewport', async ({ narrow, covers }) => {
		vi.stubGlobal(
			'matchMedia',
			vi.fn((query: string) => ({
				matches: query === MINI_PLAYER_WITHOUT_COVER_MEDIA ? narrow : true,
				addEventListener: vi.fn(),
				removeEventListener: vi.fn()
			}))
		);
		loadTake();
		await mountBar();

		const [titleTarget] = openTargets();
		expect(titleTarget.querySelectorAll('.track-cover')).toHaveLength(covers);
		expect(titleTarget.querySelector('.track-title')?.textContent).toBe('Opening Move');
		expect(titleTarget.getAttribute('aria-label')).toBe(openNowPlayingLabel('Opening Move'));
	});

	it.each([
		{ place: 'the cover and title', index: 0 },
		{ place: 'the empty right side', index: 1 }
	])(
		'opens Now Playing from $place, and hands focus back to the title on close',
		async ({ index }) => {
			loadTake();
			await mountBar();

			openTargets()[index].click();
			await tick();
			expect(get(nowPlayingSurface)).toBe('full');

			closeNowPlaying();
			await tick();
			expect(document.activeElement).toBe(openTargets()[0]);
		}
	);

	it('keeps the right side out of the keyboard and screen reader path', async () => {
		loadTake();
		await mountBar();

		const rightSide = openTargets()[1];
		expect(rightSide.tabIndex).toBe(-1);
		expect(rightSide.getAttribute('aria-hidden')).toBe('true');
	});

	// A finger lands on the bar and lifts wherever the move ended, usually
	// above the bar, so the lift is dispatched on the page, not on the bar.
	function swipe(from: Element, { rise, drift = 0 }: { rise: number; drift?: number }): void {
		const start = { clientX: 120, clientY: 800 };
		from.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, pointerId: 1, ...start }));
		document.body.dispatchEvent(
			new PointerEvent('pointerup', {
				bubbles: true,
				pointerId: 1,
				clientX: start.clientX + drift,
				clientY: start.clientY - rise
			})
		);
	}

	const swipeStarts = {
		title: () => openTargets()[0],
		rightSide: () => openTargets()[1],
		control: (name: string) => () => {
			const control = bar().querySelector(`.transport-controls button[aria-label="${name}"]`);
			if (!control) throw new Error(`Expected the ${name} button`);
			return control;
		}
	};

	it.each([
		{ gesture: 'a swipe up from the title', start: swipeStarts.title },
		{ gesture: 'a swipe up from the empty right side', start: swipeStarts.rightSide }
	])('opens Now Playing on $gesture', async ({ start }) => {
		loadTake();
		await mountBar();

		swipe(start(), { rise: NOW_PLAYING_SWIPE_RISE_PX });
		await tick();

		expect(get(nowPlayingSurface)).toBe('full');
	});

	it.each([
		{
			gesture: 'a move up too short',
			start: swipeStarts.title,
			rise: NOW_PLAYING_SWIPE_RISE_PX - 1
		},
		{
			gesture: 'a move more sideways than up',
			start: swipeStarts.title,
			rise: NOW_PLAYING_SWIPE_RISE_PX,
			drift: NOW_PLAYING_SWIPE_RISE_PX
		},
		{ gesture: 'a move down', start: swipeStarts.title, rise: -NOW_PLAYING_SWIPE_RISE_PX },
		{
			gesture: 'a swipe up from Previous',
			start: swipeStarts.control('Previous'),
			rise: NOW_PLAYING_SWIPE_RISE_PX
		},
		{
			gesture: 'a swipe up from play',
			start: swipeStarts.control(TRANSPORT_PLAY_LABEL),
			rise: NOW_PLAYING_SWIPE_RISE_PX
		},
		{
			gesture: 'a swipe up from Next',
			start: swipeStarts.control('Next'),
			rise: NOW_PLAYING_SWIPE_RISE_PX
		}
	])('leaves Now Playing closed on $gesture', async ({ start, rise, drift }) => {
		loadTake();
		await mountBar();

		swipe(start(), { rise, drift });
		await tick();

		expect(get(nowPlayingSurface)).toBe('closed');
	});

	// A finger's click counts its taps; a keyboard or screen reader press
	// arrives as a click that counts none.
	function click(control: Element, { by }: { by: 'finger' | 'keyboard' }): void {
		control.dispatchEvent(
			new MouseEvent('click', { bubbles: true, detail: by === 'finger' ? 1 : 0 })
		);
	}

	it('keeps a docked panel open when the swipe that opened it ends in a click on the title', async () => {
		nowPlayingDockable.set(true);
		loadTake();
		await mountBar();

		swipe(openTargets()[0], { rise: NOW_PLAYING_SWIPE_RISE_PX });
		click(openTargets()[0], { by: 'finger' });
		await tick();
		expect(get(nowPlayingSurface)).toBe('docked');

		click(openTargets()[0], { by: 'finger' });
		await tick();
		expect(get(nowPlayingSurface)).toBe('closed');
	});

	// A docked panel leaves the bar in place, so a swipe that ended with no
	// click on it must not eat the next keyboard press.
	it.each([
		{
			control: 'the title',
			press: () => openTargets()[0],
			expectActed: () => expect(get(nowPlayingSurface)).toBe('closed')
		},
		{
			control: 'Next',
			press: swipeStarts.control('Next'),
			expectActed: () => expect(playerStore.playNextSong).toHaveBeenCalledOnce()
		}
	])(
		'acts on a keyboard press on $control after a swipe that ended without a click',
		async ({ press, expectActed }) => {
			vi.spyOn(playerStore, 'playNextSong').mockResolvedValue();
			nowPlayingDockable.set(true);
			audioPlayer.loadStream(manifest([track(0), track(1)]), 0, { autoplay: false });
			await mountBar();
			swipe(openTargets()[0], { rise: NOW_PLAYING_SWIPE_RISE_PX });
			await tick();
			expect(get(nowPlayingSurface)).toBe('docked');

			click(press(), { by: 'keyboard' });
			await tick();

			expectActed();
		}
	);

	it.each([
		{ step: 'Previous', action: 'playPrevSong' as const },
		{ step: 'Next', action: 'playNextSong' as const }
	])('steps with $step', async ({ step, action }) => {
		const played = vi.spyOn(playerStore, action).mockResolvedValue();
		audioPlayer.loadStream(manifest([track(0), track(1)]), 0, { autoplay: false });
		audio.currentTime = step === 'Previous' ? 15 : 0;
		audio.fire('timeupdate');
		await mountBar();

		bar().querySelector<HTMLButtonElement>(`button[aria-label="${step}"]`)?.click();

		expect(played).toHaveBeenCalledOnce();
	});

	const LONG_TITLE = 'An Opening Move Across The Longest Night';

	// jsdom lays nothing out: a test says how wide the title runs and how much
	// room it has, and records each motion the bar asks the browser for.
	function arrangeTitle({
		cut,
		reducedMotion = false,
		phone = true
	}: {
		cut: boolean;
		reducedMotion?: boolean;
		phone?: boolean;
	}): { element: Element; keyframes: Keyframe[] }[] {
		vi.stubGlobal(
			'matchMedia',
			vi.fn((query: string) => ({
				matches: query === REDUCED_MOTION_MEDIA ? reducedMotion : phone,
				addEventListener: vi.fn(),
				removeEventListener: vi.fn()
			}))
		);
		vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(60);
		vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockReturnValue(cut ? 180 : 60);
		const motions: { element: Element; keyframes: Keyframe[] }[] = [];
		Object.defineProperty(HTMLElement.prototype, 'animate', {
			configurable: true,
			value(this: Element, keyframes: Keyframe[]) {
				motions.push({ element: this, keyframes });
				return { cancel: () => {} };
			}
		});
		onTestFinished(() => {
			delete (HTMLElement.prototype as Partial<HTMLElement>).animate;
		});
		return motions;
	}

	it('scrolls a cut title once to its end and back to its start, and once for each new title', async () => {
		const motions = arrangeTitle({ cut: true });
		loadTake(LONG_TITLE);
		await mountBar();

		expect(motions).toHaveLength(1);
		const [{ element, keyframes }] = motions;
		expect(element).toBe(bar().querySelector('.track-title'));
		expect(keyframes.at(0)?.textIndent).toBe('0px');
		expect(keyframes.map((frame) => frame.textIndent)).toContain('-120px');
		expect(keyframes.at(-1)?.textIndent).toBe('0px');

		loadTake(`${LONG_TITLE} Again`);
		await tick();
		expect(motions).toHaveLength(2);
	});

	it.each([
		{ title: 'a title that fits', cut: false },
		{ title: 'a cut title under reduced motion', cut: true, reducedMotion: true },
		{ title: 'a cut title on the desktop bar', cut: true, phone: false }
	])('keeps $title still', async ({ cut, reducedMotion, phone }) => {
		const motions = arrangeTitle({ cut, reducedMotion, phone });
		loadTake(LONG_TITLE);
		await mountBar();

		expect(motions).toHaveLength(0);
	});

	it('names the open target after the full title while the title is cut', async () => {
		arrangeTitle({ cut: true, reducedMotion: true });
		loadTake(LONG_TITLE);
		await mountBar();

		expect(openTargets()[0].getAttribute('aria-label')).toBe(openNowPlayingLabel(LONG_TITLE));
		expect(bar().querySelector('.track-title')?.textContent).toBe(LONG_TITLE);
	});

	it('shows the idle target as plain words that open nothing', async () => {
		queueContext.set({ type: 'library' });
		await mountBar();

		expect(openTargets()).toHaveLength(0);
		expect(bar().querySelector('.track-title')?.textContent).toBe(LIBRARY_PAGE_LABEL);
	});
});

describe('PlayerBar failure line', () => {
	// A take the lost network stopped plays on once the connection is back
	// (#1161 R2), so the player goes before the connection returns.
	afterEach(() => {
		audioPlayer.destroy();
		resetConnectivityForTests();
	});

	async function mountPlayingFromNightdrive(): Promise<void> {
		queueContext.set({ type: 'album', albumId: 'a1' });
		albumList.set([albumItem({ share_slug: null, cover: null, title: 'Nightdrive' })]);
		audioPlayer.loadStream(manifest([track(0)]), 0, { autoplay: false });
		component = mount(PlayerBar, { target });
		await tick();
	}

	async function failPlayback(): Promise<string> {
		vi.spyOn(audio, 'play').mockRejectedValue(new Error('decode failed'));
		audio.readyState = HTMLMediaElement.HAVE_FUTURE_DATA;
		target.querySelector<HTMLButtonElement>('.play-btn')?.click();
		await tick();
		audio.fire('canplay');
		await vi.waitFor(() => expect(audioPlayer.error).toBeTruthy());
		await tick();
		return audioPlayer.error ?? '';
	}

	it.each([
		{
			layout: "phone, in the bar's empty right side beside the source line",
			arrange: () => {},
			failure: '.phone-side:not(.track-info)',
			detailBeside: () => nowPlayingFromLabel('Nightdrive')
		},
		{
			layout: 'desktop, after the take line',
			arrange: useDesktopLayout,
			failure: '.track-detail .error-text',
			detailBeside: (why: string) => `${nowPlayingTakeLabel(null, 1)}${why}`
		}
	])('shows why playback stopped on the $layout', async ({ arrange, failure, detailBeside }) => {
		arrange();
		await mountPlayingFromNightdrive();

		const why = await failPlayback();

		expect(target.querySelector(failure)?.textContent?.trim()).toBe(why);
		expect(target.querySelector('.track-detail')?.textContent).toBe(detailBeside(why));
	});

	it.each([
		{ layout: 'phone', arrange: () => {} },
		{ layout: 'desktop', arrange: useDesktopLayout }
	])('offline, the $layout bar adds no failure text beside the strip', async ({ arrange }) => {
		arrange();
		await mountPlayingFromNightdrive();
		reportResourceStreamReachable(false);
		vi.spyOn(audio, 'play').mockRejectedValue(new Error('decode failed'));
		audio.readyState = HTMLMediaElement.HAVE_FUTURE_DATA;

		target.querySelector<HTMLButtonElement>('.play-btn')?.click();
		await tick();
		audio.fire('canplay');
		await vi.waitFor(() => expect(audioPlayer.status).toBe('error'));
		await tick();

		expect(target.querySelector('.offline-strip')).not.toBeNull();
		expect(target.querySelector('.phone-failure, .error-text')).toBeNull();
		expect(target.querySelector('.play-btn')?.getAttribute('aria-label')).toBe('Retry');
	});

	// The target's own label replaces its words for a screen reader.
	it("describes the phone's cover-and-title target by its source line, then by why playback stopped", async () => {
		await mountPlayingFromNightdrive();
		const titleTarget = target.querySelector<HTMLButtonElement>('.track-info.open-now-playing');
		const description = (): string =>
			(titleTarget?.getAttribute('aria-describedby') ?? '')
				.split(' ')
				.map((id) => document.getElementById(id)?.textContent?.trim())
				.join(' ');
		expect(description()).toContain(nowPlayingFromLabel('Nightdrive'));

		const why = await failPlayback();

		expect(description()).toBe(`${nowPlayingFromLabel('Nightdrive')} ${why}`);
	});
});

describe('PlayerBar offline strip (#1080)', () => {
	function offlineStrip(): HTMLElement | null {
		return target.querySelector('.offline-strip');
	}

	beforeEach(() => {
		audioPlayer.loadStream(manifest([track(0)]), 0, { autoplay: false });
		component = mount(PlayerBar, { target });
	});

	afterEach(() => {
		resetConnectivityForTests();
	});

	it('sits on the top edge of the bar while the page is offline', async () => {
		browserReportsOnline(false);
		await tick();

		expect(offlineStrip()?.textContent?.trim()).toBe(OFFLINE_STRIP_MESSAGE);
		expect(offlineStrip()?.closest('.offline-edge')?.nextElementSibling).toHaveClass('player-bar');
	});

	it('hides with the bar in full Now Playing and comes back with it', async () => {
		browserReportsOnline(false);
		nowPlayingSurface.set('full');
		await tick();
		expect(offlineStrip()).toBeNull();

		closeNowPlaying();
		await tick();
		expect(offlineStrip()).not.toBeNull();
	});

	it('steps aside with the bar while typing on the phone', async () => {
		browserReportsOnline(false);
		const closeKeyboard = openOnScreenKeyboard();
		const stopWatching = watchTypingOnPhone(document, true);
		const lyrics = document.createElement('textarea');
		document.body.append(lyrics);

		lyrics.focus();
		await tick();
		expect(offlineStrip()).toBeNull();

		lyrics.blur();
		await tick();
		expect(offlineStrip()).not.toBeNull();
		stopWatching();
		closeKeyboard();
	});
});

describe('PlayerBar while typing on the phone', () => {
	it('steps aside for the keyboard and comes back on leaving the field, with playback untouched', async () => {
		audioPlayer.loadStream(manifest([track(0)]), 0, { autoplay: false });
		component = mount(PlayerBar, { target });
		await tick();
		audio.readyState = HTMLMediaElement.HAVE_FUTURE_DATA;
		target.querySelector<HTMLButtonElement>('.play-btn')?.click();
		await tick();
		audio.fire('canplay');
		await tick();
		expect(audio.paused).toBe(false);
		const closeKeyboard = openOnScreenKeyboard();
		const stopWatching = watchTypingOnPhone(document, true);
		const lyrics = document.createElement('textarea');
		document.body.append(lyrics);

		lyrics.focus();
		await tick();
		expect(target.querySelector('.player-bar')).toBeNull();
		expect(audio.paused).toBe(false);

		lyrics.blur();
		await tick();
		expect(target.querySelector('.player-bar')).not.toBeNull();
		expect(audio.paused).toBe(false);
		stopWatching();
		closeKeyboard();
	});
});

describe('PlayerBar while a take stalls (#1234)', () => {
	const PAST_THE_RECOVERY_DEADLINE_MS = 3 * 60 * 1000;

	afterEach(() => {
		vi.useRealTimers();
		resetConnectivityForTests();
	});

	async function stallWhilePlaying(arrange: () => void = () => {}): Promise<void> {
		vi.useFakeTimers({
			toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date']
		});
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
		arrange();
		loadTake();
		component = mount(PlayerBar, { target });
		await tick();
		await audio.play();
		audio.fire('playing');
		audio.fire('waiting');
		await tick();
	}

	async function giveUpWhileOfflineAfterStall(): Promise<void> {
		reportResourceStreamReachable(false);
		await vi.advanceTimersByTimeAsync(PAST_THE_RECOVERY_DEADLINE_MS);
		await tick();
	}

	async function giveUpWhileOffline(arrange: () => void = () => {}): Promise<void> {
		await stallWhilePlaying(arrange);
		await giveUpWhileOfflineAfterStall();
	}

	async function mountWithAlbumStartNotice(
		notice: 'awaiting-network' | 'gave-up-on-network',
		arrange: () => void = () => {}
	): Promise<void> {
		arrange();
		holdAlbumStart(notice);
		component = mount(PlayerBar, { target });
		await tick();
	}

	async function tapATakeRowOffline(): Promise<void> {
		reportResourceStreamReachable(false);
		audioPlayer.load(barTake());
		component = mount(PlayerBar, { target });
		await tick();
	}

	function transportFacts(lockScreen: Pick<MediaSession, 'playbackState'>) {
		return {
			main: playButton().getAttribute('aria-label'),
			spinner: playButton().querySelector('.spinner') !== null,
			lockScreen: lockScreen.playbackState
		};
	}

	it.each([
		{ start: 'album header', tap: () => mountWithAlbumStartNotice('awaiting-network') },
		{ start: 'take row', tap: tapATakeRowOffline }
	])(
		'an offline $start shows the waiting transport from the tap: Pause with its spinner (#1312)',
		async ({ tap }) => {
			const lockScreen = installLockScreen();
			await tap();

			expect(transportFacts(lockScreen)).toEqual({
				main: TRANSPORT_PAUSE_LABEL,
				spinner: true,
				lockScreen: 'playing'
			});
		}
	);

	it('pausing an offline take row start leaves a bar that names the take Play would start (#1312)', async () => {
		await tapATakeRowOffline();

		await clickAndSettle();

		expect({
			title: target.querySelector('.track-title')?.textContent,
			main: playButton().getAttribute('aria-label')
		}).toEqual({ title: 'Opening Move', main: TRANSPORT_PLAY_LABEL });
	});

	it.each([
		{ moment: 'while it buffers', wait: 0 },
		{ moment: 'while a recovery reload runs', wait: STALL_RECOVERY_MS }
	])('offers Pause $moment, and Pause stops the recovery', async ({ wait }) => {
		await stallWhilePlaying();
		await vi.advanceTimersByTimeAsync(wait);
		await tick();
		const whileRecovering = playButton().getAttribute('aria-label');
		const load = vi.spyOn(audio, 'load');

		await clickAndSettle();
		await vi.advanceTimersByTimeAsync(60_000);
		await tick();

		expect({
			whileRecovering,
			afterPause: playButton().getAttribute('aria-label'),
			spinner: target.querySelector('.play-btn .spinner') !== null,
			reloads: load.mock.calls.length
		}).toEqual({
			whileRecovering: TRANSPORT_PAUSE_LABEL,
			afterPause: TRANSPORT_PLAY_LABEL,
			spinner: false,
			reloads: 0
		});
	});

	const giveUpTake = giveUpWhileOffline;
	const giveUpAlbumStart = (arrange: () => void) =>
		mountWithAlbumStartNotice('gave-up-on-network', arrange);

	it.each([
		{ waiting: 'take', layout: 'phone', arrange: () => {}, giveUp: giveUpTake },
		{ waiting: 'take', layout: 'desktop', arrange: useDesktopLayout, giveUp: giveUpTake },
		{ waiting: 'album start', layout: 'phone', arrange: () => {}, giveUp: giveUpAlbumStart },
		{
			waiting: 'album start',
			layout: 'desktop',
			arrange: useDesktopLayout,
			giveUp: giveUpAlbumStart
		}
	])(
		'given up offline, the $layout bar of a $waiting waits calmly with no Retry to press (#1312)',
		async ({ arrange, giveUp }) => {
			await giveUp(arrange);

			expect({
				words: target.querySelector('.waiting-notice [role="status"]')?.textContent?.trim(),
				redFailure: target.querySelector('.error-text, .phone-failure, .play-btn.errored') !== null,
				main: playButton().getAttribute('aria-label'),
				retryOffered: target.textContent?.includes(TRANSPORT_RETRY_LABEL)
			}).toEqual({
				words: PLAYER_WAITING_FOR_NETWORK,
				redFailure: false,
				main: TRANSPORT_PAUSE_LABEL,
				retryOffered: false
			});
		}
	);

	it.each([
		{ moment: 'while it buffers', reach: () => vi.advanceTimersByTimeAsync(0) },
		{
			moment: 'while a recovery reload runs',
			reach: () => vi.advanceTimersByTimeAsync(STALL_RECOVERY_MS)
		},
		{ moment: 'while it waits for the network', reach: () => giveUpWhileOfflineAfterStall() }
	])('the lock screen offers Pause $moment, like the bar', async ({ reach }) => {
		const lockScreen = installLockScreen();
		await stallWhilePlaying();
		await reach();
		await tick();
		const whileWaiting = lockScreen.playbackState;

		await clickAndSettle();

		expect({ whileWaiting, afterPause: lockScreen.playbackState }).toEqual({
			whileWaiting: 'playing',
			afterPause: 'paused'
		});
	});

	it.each([
		// The lock screen's pause action is the player's own pause (stores/player.ts).
		{ how: 'from the lock screen', pause: async () => audioPlayer.pause() },
		{ how: "with the bar's Pause", pause: () => clickAndSettle() }
	])('a take given up offline and paused $how shows Paused at once', async ({ pause }) => {
		await giveUpWhileOffline();

		await pause();
		await tick();

		expect({
			main: playButton().getAttribute('aria-label'),
			waiting: target.querySelector('.waiting-notice') !== null
		}).toEqual({ main: TRANSPORT_PLAY_LABEL, waiting: false });
	});
});
