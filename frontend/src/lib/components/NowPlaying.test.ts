import {
	makeAlbum as album,
	makeGeneration as generation,
	makePlaylistEntry as playlistEntry,
	makeSong as song
} from '#lib/test-utils/factories.ts';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import type { SongItem } from '#lib/api/types.ts';
import type { PlaybackInfo } from '#lib/services/playbackTypes.ts';
import { UNREACHABLE_RELOAD_DELAYS_MS } from '#lib/constants/connectivity.ts';
import { nowPlayingFromLabel, nowPlayingTakeLabel } from '#lib/constants/now-playing.ts';
import { openCollection, resetCollectionForTests } from '#lib/stores/collection.ts';
import { albumList, resetLibraryDataForTests, songList } from '#lib/stores/libraryData.ts';
import {
	closeNowPlaying,
	expandNowPlaying,
	ensureGenerationsLoaded,
	libraryQueueSkipped,
	nowPlayingDockable,
	nowPlayingOpen,
	nowPlayingPanel,
	nowPlayingSurface,
	openNowPlaying,
	selectedSongId,
	setShuffle,
	shuffleEnabled,
	shuffleLabel
} from '#lib/stores/player.ts';
import { queueContext, songTakeQueue } from '#lib/stores/queue.ts';
import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import { setLibraryTakePool } from '#lib/stores/playbackSettings.ts';
import { selectedPlaylistDetail } from '#lib/stores/playlists.ts';
import { HITBOX_FREQUENT_PX } from '#lib/constants/hitbox.ts';
import {
	reportResourceStreamReachable,
	resetConnectivityForTests
} from '#lib/stores/connectivity.ts';
import { toasts } from '#lib/stores/toast.ts';
import { describeBackClosesOverlay } from '#lib/test-utils/library-history.ts';
import { setDesktopNowPlayingSurface } from '#lib/stores/playbackSettings.ts';
import { followShellLayers, resetNavigationForTests } from '#lib/stores/navigation.ts';
import {
	clearHitboxStyles,
	injectHitboxStyles,
	minHeightPx,
	setPointer
} from '#lib/test-utils/hitbox.ts';
import { laidOutSeekLine, pointerOnSeekLine } from '#lib/test-utils/seek-line.ts';
import { clearComponentStyles, injectComponentStyles } from '#lib/test-utils/component-styles.ts';
import nowPlayingFrameSource from './NowPlayingFrame.svelte?raw';

// togglePick/toggleKeep stay mocked so a key press asserts the call it makes,
// not the network + song-refresh chain behind it — takeActions.test.ts covers
// that chain.
// Stands in for the router the way the real one behaves for this app (issue
// #275): a song selection can now cross from the wall's `/` into the song's
// own `/album/<slug>/<song-slug>` address, which writeLibraryHistory sends
// through `goto` -- unmocked, that call needs a live SvelteKit router this
// harness never mounts.
vi.mock('$app/navigation', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation()
);

vi.mock('#lib/stores/takeActions.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/stores/takeActions.ts')>()),
	togglePick: vi.fn().mockResolvedValue(undefined),
	toggleKeep: vi.fn().mockResolvedValue(undefined)
}));

import { toggleKeep, togglePick } from '#lib/stores/takeActions.ts';
import NowPlaying from './NowPlaying.svelte';
import { queryButtonByLabel } from '#lib/test-utils/accessible-name.ts';
import { words } from '#lib/words/en.ts';

function playingSongDefaults(): Partial<SongItem> {
	return {
		slug: 'tide',
		title: 'Tide',
		album_title: 'Nachtstrom',
		lyrics: 'old verse',
		prompt: 'dreamy',
		created_at: '',
		generations: [
			generation({
				generation_number: 2,
				mp3_path: 'a.mp3',
				seed: 1,
				model_mode: 'sft',
				version_lyrics: 'old verse',
				created_at: ''
			})
		]
	};
}

function info(overrides: Partial<PlaybackInfo> = {}): PlaybackInfo {
	return {
		generation: generation({
			generation_number: 2,
			mp3_path: 'a.mp3',
			seed: 1,
			model_mode: 'sft',
			version_lyrics: 'old verse',
			created_at: ''
		}),
		songId: 's1',
		songTitle: 'Tide',
		artist: 'Artist',
		albumTitle: 'Nachtstrom',
		lyrics: 'old verse',
		...overrides
	};
}

// jsdom implements no media playback, and this surface's transport really
// does drive the queue — stub the element so a Next press stays as quiet and
// deterministic as the state it changes.
class SilentAudio {
	paused = true;
	ended = false;
	currentTime = 0;
	duration = 0;
	readyState = 0;
	buffered = { length: 0, end: () => 0 };
	src = '';
	preload = '';
	crossOrigin: string | null = null;
	addEventListener() {}
	removeAttribute() {}
	load() {}
	pause() {}
	play() {
		return Promise.resolve();
	}
}

let mounted: ReturnType<typeof mount> | undefined;
let target: HTMLDivElement;

beforeEach(() => {
	vi.stubGlobal(
		'Audio',
		vi.fn(function () {
			return new SilentAudio();
		})
	);
});

async function unmountSurface() {
	if (mounted) await unmount(mounted);
	mounted = undefined;
}

afterEach(async () => {
	await unmountSurface();
	// vitest 4: restoreAllMocks only rewinds vi.spyOn spies — the module-level
	// vi.fn() stubs from the takeActions mock factory above need an explicit
	// clear or their call history leaks into the next test (see player.test.ts).
	vi.clearAllMocks();
	vi.restoreAllMocks();
	document.body.replaceChildren();
	clearHitboxStyles();
	clearComponentStyles();
	document.documentElement.dataset.pointer = '';
	audioPlayer.current = null;
	audioPlayer.destroy();
	selectedSongId.set(null);
	closeNowPlaying();
	nowPlayingDockable.set(false);
	songList.set([]);
	albumList.set([]);
	// Going to the playing song loads its album's songs; a swallowed load arms
	// the library's own reload, which would fire inside a later test.
	resetLibraryDataForTests();
	toasts.set([]);
	queueContext.set({ type: 'library' });
	selectedPlaylistDetail.set(null);
	setShuffle(false);
	setLibraryTakePool('picks');
	libraryQueueSkipped.set([]);
	nowPlayingPanel.set('queue');
	resetCollectionForTests();
	vi.unstubAllGlobals();
});

// The surface reads what is playing and what the queue allows from the player
// store, so a test arranges playback rather than handing it callbacks.
async function renderSurface(playback: PlaybackInfo) {
	audioPlayer.current = playback;
	nowPlayingSurface.set('full');
	target = document.createElement('div');
	document.body.append(target);
	mounted = mount(NowPlaying, { target, props: { info: playback } });
	await tick();
}

describe('NowPlaying', () => {
	it('sizes the Queue | This take tabs to the frequent hitbox on a coarse pointer', async () => {
		// #163/6: the two tabs are the only way into the queue on a phone.
		injectHitboxStyles();
		await renderSurface(info());
		setPointer('coarse');

		const tabs = Array.from(
			target.querySelectorAll<HTMLButtonElement>('.panel-toggle [role="tab"]')
		);
		expect(tabs).toHaveLength(2);
		for (const tab of tabs) {
			expect(minHeightPx(tab, tab.textContent ?? 'tab')).toBe(HITBOX_FREQUENT_PX);
		}
	});

	it('shows the playing take and its version lyrics, not a later draft', async () => {
		songList.set([song(playingSongDefaults())]);
		await renderSurface(info({ lyrics: 'old verse' }));
		expect(target.textContent).toContain(words['transport.nowPlaying']);
		expect(target.textContent).toContain('Tide');
		expect(target.textContent).toContain('Nachtstrom · Artist');
		expect(target.textContent).toContain(nowPlayingTakeLabel(1, 2));
		expect(target.textContent).toContain('old verse');
		expect(target.textContent).not.toContain('latest draft');
	});

	it.each([
		{ take: 'a take of a version', versioned: true, empty: words['nowPlaying.noLyrics'] },
		{ take: 'an imported take', versioned: false, empty: words['nowPlaying.importedNoLyrics'] }
	])('names why $take shows no lyrics', async ({ versioned, empty }) => {
		const take = generation({
			generation_number: 2,
			mp3_path: 'a.mp3',
			version_lyrics: null,
			...(versioned ? {} : { version_id: null, version_number: null })
		});
		songList.set([song({ ...playingSongDefaults(), generations: [take] })]);
		await renderSurface(info({ generation: take, lyrics: null }));

		expect(target.textContent).toContain(empty);
		expect(target.querySelector('.lyrics')).toBeNull();
	});

	it('follows the lyrics with the resolved take once whisper_cues are loaded (#45)', async () => {
		const gen = generation({
			generation_number: 2,
			mp3_path: 'a.mp3',
			seed: 1,
			model_mode: 'sft',
			version_lyrics: 'old verse',
			created_at: '',
			whisper_cues: [{ start: 0, end: 1, text: 'old verse' }]
		});
		songList.set([song({ ...playingSongDefaults(), generations: [gen] })]);
		await renderSurface(info({ lyrics: 'old verse', generation: gen }));

		expect(target.querySelectorAll('.lyrics-line')).toHaveLength(1);
	});

	it('stays static for a thin library-pool item until its song resolves whisper_cues', async () => {
		// info.generation mirrors what a library-pool click builds before
		// ensureGenerationsLoaded resolves it against songList — whisper_cues
		// stubbed null, songList not yet carrying the real generation.
		await renderSurface(info({ lyrics: 'old verse' }));

		expect(target.querySelector('.lyrics-line')).toBeNull();
		expect(target.querySelector('.lyrics')?.textContent).toContain('old verse');
	});

	it('closes on the close button', async () => {
		await renderSurface(info());

		queryButtonByLabel(target, words['nowPlaying.close'])?.click();

		expect(get(nowPlayingSurface)).toBe('closed');
	});

	describe('as the layer the app layout follows', () => {
		let stopFollowingShellLayers: () => void = () => undefined;

		beforeEach(() => {
			stopFollowingShellLayers = followShellLayers();
		});

		afterEach(() => {
			stopFollowingShellLayers();
			resetNavigationForTests();
			setDesktopNowPlayingSurface('docked');
		});

		it('closes on Escape where no docked panel fits', async () => {
			await renderSurface(info());
			expandNowPlaying();

			window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));

			expect(get(nowPlayingSurface)).toBe('closed');
		});

		it('steps back to the docked panel on Escape where one fits', async () => {
			nowPlayingDockable.set(true);
			await renderSurface(info());
			expandNowPlaying();

			window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));

			expect(get(nowPlayingSurface)).toBe('docked');
		});
	});

	it('goes to the playing song and leaves Now Playing behind', async () => {
		songList.set([song(playingSongDefaults())]);
		await renderSurface(info());

		const go = Array.from(target.querySelectorAll('button')).find(
			(button) => button.textContent === words['nowPlaying.goToSong']
		);
		go?.click();

		await vi.waitFor(() => expect(get(selectedSongId)).toBe('s1'));
		expect(get(nowPlayingSurface)).toBe('closed');
	});

	it('offers Previous and Next only as far as the playing queue reaches', async () => {
		albumList.set([album({ created_at: '' })]);
		songList.set([song(playingSongDefaults())]);
		queueContext.set({ type: 'album', albumId: 'a1' });
		await renderSurface(info());
		expect(queryButtonByLabel(target, words['nowPlaying.nextSong'])?.disabled).toBe(true);

		songList.set([
			song(playingSongDefaults()),
			song({ ...playingSongDefaults(), id: 's2', title: 'Second' })
		]);
		await tick();

		expect(queryButtonByLabel(target, words['nowPlaying.nextSong'])?.disabled).toBe(false);
	});

	it('Next moves the playing queue on to its next entry', async () => {
		queueContext.set({
			type: 'playlist',
			playlist: { id: 'p1', title: 'Night Drive' },
			entries: [
				playlistEntry({
					generation_id: 'g-pe1',
					song_id: 's-pe1',
					song_title: 'Tide',
					album_title: 'Nachtstrom',
					mp3_path: 'pe1.mp3'
				}),
				playlistEntry({
					id: 'pe2',
					generation_id: 'g-pe2',
					song_id: 's-pe2',
					song_title: 'Second',
					album_title: 'Nachtstrom',
					mp3_path: 'pe2.mp3'
				})
			],
			index: 0
		});
		await renderSurface(info());

		queryButtonByLabel(target, words['nowPlaying.nextSong'])?.click();

		await vi.waitFor(() => {
			const ctx = get(queueContext);
			expect(ctx.type === 'playlist' && ctx.index).toBe(1);
		});
	});

	it('drops the start-over line of a song queue once the song list archives its other take', async () => {
		const [first, second] = [generation({ id: 'g1' }), generation({ id: 'g2' })];
		const playing = song({ generations: [first, second] });
		const queue = songTakeQueue(playing, 'g1');
		if (!queue) throw new Error('Expected a song queue');
		songList.set([playing]);
		queueContext.set(queue);
		await renderSurface(info());
		expect(target.querySelector('.queue-again')).not.toBeNull();

		songList.set([{ ...playing, generations: [first, { ...second, is_archived: true }] }]);
		await tick();

		expect(target.querySelector('.queue-again')).toBeNull();
	});

	it('toggles shuffle from the overlay, scoped to the current queue', async () => {
		setShuffle(false);
		queueContext.set({ type: 'album', albumId: 'a1' });
		await renderSurface(info());
		const shuffleBtn = target.querySelector<HTMLButtonElement>('[aria-pressed]');
		expect(shuffleBtn?.getAttribute('aria-label')).toBe(words['transport.shuffleAlbum']);
		shuffleBtn?.click();
		await tick();
		expect(get(shuffleEnabled)).toBe(true);
		expect(shuffleBtn?.getAttribute('aria-pressed')).toBe('true');
		expect(shuffleBtn?.getAttribute('aria-label')).toBe(words['transport.unshuffleAlbum']);
	});

	it('centres play between shuffle · previous and next · an empty slot, with no repeat', async () => {
		await renderSurface(info());

		const [before, play, after, ...rest] = Array.from(
			target.querySelector('.transport')?.children ?? []
		);
		const controlNames = (side: Element | undefined) =>
			Array.from(side?.children ?? []).map(
				(control) => control.getAttribute('aria-label') ?? 'empty slot'
			);
		expect(rest).toHaveLength(0);
		expect(play?.getAttribute('aria-label')).toBe(words['transport.play']);
		expect(controlNames(before)).toEqual([get(shuffleLabel), words['nowPlaying.previousSong']]);
		expect(controlNames(after)).toEqual([words['nowPlaying.nextSong'], 'empty slot']);
		expect(after?.lastElementChild?.getAttribute('aria-hidden')).toBe('true');
		expect(target.querySelector('[aria-label*="repeat" i]')).toBeNull();
	});

	it('plays from where a tap lands on its seek line, not only from its knob (#1382)', async () => {
		await renderSurface(info());
		audioPlayer.duration = 180;
		const seek = vi.spyOn(audioPlayer, 'seek').mockImplementation(() => {});
		await tick();
		const line = laidOutSeekLine(target);

		await pointerOnSeekLine(line, 'pointerdown', 0.75);
		await pointerOnSeekLine(line, 'pointerup', 0.75);

		expect(seek.mock.calls).toEqual([[135]]);
	});

	it.each([
		{ transport: 'loading', named: words['transport.pause'], busy: true },
		{ transport: 'recovering', named: words['transport.pause'], busy: true },
		{ transport: 'waiting-for-network', named: words['transport.pause'], busy: false },
		{ transport: 'failed', named: words['transport.retry'], busy: false },
		{ transport: 'paused', named: words['transport.play'], busy: false }
	] as const)(
		'names its play button $named, busy $busy, while the take is $transport, as the bar does (#1234, #1312)',
		async ({ transport, named, busy }) => {
			vi.spyOn(audioPlayer, 'transport', 'get').mockReturnValue(transport);
			await renderSurface(info());
			const play = target.querySelector('.transport .play-btn');

			expect({
				named: play?.getAttribute('aria-label'),
				busy: play?.getAttribute('aria-busy'),
				spinner: play?.querySelector('.spinner') !== null
			}).toEqual({ named, busy: String(busy), spinner: busy });
		}
	);

	it('paints its play button in the action colour, --accent, as the bar does (#924)', async () => {
		await renderSurface(info());
		const play = target.querySelector<HTMLElement>('.transport .play-btn');
		if (!play) throw new Error('Expected the play button');

		injectComponentStyles(nowPlayingFrameSource, 'NowPlayingFrame.svelte', play);
		const style = getComputedStyle(play);

		expect({ fill: style.background, ink: style.color }).toEqual({
			fill: 'var(--accent)',
			ink: 'var(--on-accent)'
		});
	});

	it.each([
		{ transport: 'waiting-for-network', words: words['transport.waitingForNetwork'] },
		{ transport: 'recovering', words: null }
	] as const)(
		'says why it waits once given up offline, as the bar does, and not while $transport (#1330)',
		async ({ transport, words }) => {
			vi.spyOn(audioPlayer, 'transport', 'get').mockReturnValue(transport);
			await renderSurface(info());

			expect(
				target.querySelector('.waiting-notice[role="status"]')?.textContent?.trim() ?? null
			).toBe(words);
		}
	);

	it('shows queue skip feedback while playing the library queue', async () => {
		queueContext.set({ type: 'library' });
		libraryQueueSkipped.set([{ generation_id: 'g2', song_id: 's2', reason: 'missing_file' }]);
		await renderSurface(info());
		expect(target.querySelector('.queue-feedback')?.textContent).toContain('1');
	});

	it('shows the pool trio only for a library queue context', async () => {
		queueContext.set({ type: 'library' });
		await renderSurface(info());
		expect(target.querySelectorAll('.pool-pill')).toHaveLength(3);
	});

	it('hides the trio and names the album for an album queue context', async () => {
		albumList.set([album({ created_at: '' })]);
		queueContext.set({ type: 'album', albumId: 'a1' });
		await renderSurface(info());
		expect(target.querySelectorAll('.pool-pill')).toHaveLength(0);
		expect(target.querySelector('.queue-heading')?.textContent).toBe(
			words['nowPlaying.queueHeading']({ source: 'Nachtstrom' })
		);
	});

	it('names the playlist the queue was built from, not the one the listener has open', async () => {
		selectedPlaylistDetail.set({
			id: 'p2',
			title: 'Morning Ride',
			slug: 'morning-ride',
			entry_count: 0,
			is_shared: false,
			album_covers: [],
			created_at: '',
			entries: []
		});
		queueContext.set({
			type: 'playlist',
			playlist: { id: 'p1', title: 'Night Drive' },
			entries: [],
			index: 0
		});
		await renderSurface(info());
		expect(target.querySelectorAll('.pool-pill')).toHaveLength(0);
		expect(target.querySelector('.queue-heading')?.textContent).toBe(
			words['nowPlaying.queueHeading']({ source: 'Night Drive' })
		);
	});

	it('toggles between Queue and This take', async () => {
		songList.set([song(playingSongDefaults())]);
		await renderSurface(info());
		const tabs = target.querySelectorAll<HTMLButtonElement>('[role="tab"]');
		expect(tabs).toHaveLength(2);
		expect(tabs[0]?.getAttribute('aria-selected')).toBe('true');
		expect(target.querySelector('.np-queue')).not.toBeNull();

		tabs[1]?.click();
		await tick();
		expect(tabs[1]?.getAttribute('aria-selected')).toBe('true');
		expect(target.querySelector('.np-queue')).toBeNull();
		expect(target.querySelector('.np-take')).not.toBeNull();
	});

	it('keeps the This take tab present and selected when a take is playing', async () => {
		songList.set([song(playingSongDefaults())]);
		nowPlayingPanel.set('take');
		await renderSurface(info());
		const takeTab = Array.from(target.querySelectorAll<HTMLButtonElement>('[role="tab"]')).find(
			(tab) => tab.textContent?.trim() === words['nowPlaying.takeTab']
		);
		expect(takeTab).toBeDefined();
		expect(takeTab?.getAttribute('aria-selected')).toBe('true');
		expect(target.querySelector('.np-take')).not.toBeNull();
		expect(target.querySelector('.np-queue')).toBeNull();
	});

	it('wires the panel tabs to their panel via aria-controls/role=tabpanel', async () => {
		songList.set([song(playingSongDefaults())]);
		await renderSurface(info());
		const tabs = target.querySelectorAll<HTMLButtonElement>('[role="tab"]');
		const panel = target.querySelector('[role="tabpanel"]');
		expect(panel).not.toBeNull();
		for (const tab of tabs) {
			expect(tab.getAttribute('aria-controls')).toBe(panel?.id);
		}
		expect(panel?.getAttribute('aria-labelledby')).toBe(tabs[0]?.id);
	});

	it('moves the panel tab selection and focus with the arrow keys', async () => {
		songList.set([song(playingSongDefaults())]);
		await renderSurface(info());
		const tabs = target.querySelectorAll<HTMLButtonElement>('[role="tab"]');
		tabs[0]?.focus();

		tabs[0]?.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
		await tick();
		expect(tabs[1]?.getAttribute('aria-selected')).toBe('true');
		expect(document.activeElement).toBe(tabs[1]);

		tabs[1]?.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
		await tick();
		expect(tabs[0]?.getAttribute('aria-selected')).toBe('true');
		expect(document.activeElement).toBe(tabs[0]);
	});

	it('the take panel stays absent while the generation is not yet loaded', async () => {
		songList.set([]);
		await renderSurface(info());
		const tabs = target.querySelectorAll<HTMLButtonElement>('[role="tab"]');
		tabs[1]?.click();
		await tick();
		expect(target.querySelector('.np-take')).toBeNull();
	});

	it('renders current-only, no up next, for a classic queue whose native takes have not built yet', async () => {
		queueContext.set({ type: 'library' });
		await renderSurface(info());
		const rows = target.querySelectorAll('.queue-row');
		expect(rows).toHaveLength(1);
		expect(rows[0]?.textContent).toContain('Tide');
		expect(target.textContent).not.toContain(words['nowPlaying.upNext']({ title: '' }));
	});

	it('renders the docked panel inline, with no transport and no sheet to open', async () => {
		nowPlayingDockable.set(true);
		songList.set([song(playingSongDefaults())]);
		await renderSurface(info());
		nowPlayingSurface.set('docked');
		await tick();

		expect(target.querySelector('.now-playing.docked')).not.toBeNull();
		expect(target.querySelector('.np-right-col')).not.toBeNull();
		expect(target.querySelector('.mobile-panel-trigger')).toBeNull();
		expect(target.querySelector('.transport')).toBeNull();
	});

	it('stacks into a single column and opens the panel as a sheet on a narrow/coarse layout', async () => {
		document.documentElement.dataset.pointer = 'coarse';
		await renderSurface(info());
		expect(target.querySelector('.np-right-col')).toBeNull();
		expect(target.querySelector('.mobile-sheet')).toBeNull();

		target.querySelector<HTMLButtonElement>('.mobile-panel-trigger')?.click();
		await tick();
		expect(target.querySelector('.mobile-sheet')).not.toBeNull();
		// Only × is named Close: the backdrop around the sheet closes the sheet.
		expect(
			target.querySelectorAll(`button[aria-label="${words['nowPlaying.close']}"]`)
		).toHaveLength(1);

		target
			.querySelector<HTMLButtonElement>(
				`button[aria-label="${words['nowPlaying.closeSheet']({ sheet: words['nowPlaying.rightPanel'] })}"]`
			)
			?.click();
		await tick();
		expect(target.querySelector('.mobile-sheet')).toBeNull();
	});

	it('labels the stacked trigger Queue and keeps the sheet closed when the queue panel is requested', async () => {
		document.documentElement.dataset.pointer = 'coarse';
		await renderSurface(info());
		expect(target.querySelector('.mobile-sheet')).toBeNull();
		expect(target.querySelector('.mobile-panel-trigger')?.textContent).toContain(
			words['nowPlaying.queueTab']
		);
	});

	it('seeds the sheet open from a take-row request on a stacked layout, never labelling the trigger Queue', async () => {
		document.documentElement.dataset.pointer = 'coarse';
		songList.set([song(playingSongDefaults())]);
		nowPlayingPanel.set('take');
		await renderSurface(info());

		expect(target.querySelector('.mobile-sheet')).not.toBeNull();
		expect(target.querySelector('.np-take')).not.toBeNull();
		const triggerText = target.querySelector('.mobile-panel-trigger')?.textContent ?? '';
		expect(triggerText).toContain(words['nowPlaying.takeTab']);
		expect(triggerText).not.toContain(words['nowPlaying.queueTab']);
	});

	it('moves focus into the mobile sheet when it opens', async () => {
		document.documentElement.dataset.pointer = 'coarse';
		songList.set([song(playingSongDefaults())]);
		await renderSurface(info());

		target.querySelector<HTMLButtonElement>('.mobile-panel-trigger')?.click();
		await tick();
		await tick();

		const sheet = target.querySelector('.mobile-sheet');
		expect(sheet?.contains(document.activeElement)).toBe(true);
	});

	it('scopes the mobile sheet focus trap to the sheet, not the whole surface, on Escape', async () => {
		document.documentElement.dataset.pointer = 'coarse';
		await renderSurface(info());

		target.querySelector<HTMLButtonElement>('.mobile-panel-trigger')?.click();
		await tick();
		expect(target.querySelector('.mobile-sheet')).not.toBeNull();

		window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
		await tick();
		expect(target.querySelector('.mobile-sheet')).toBeNull();
		expect(get(nowPlayingSurface)).toBe('full');
	});
});

function sheetBackdrop(target: HTMLElement): HTMLButtonElement | null {
	return target.querySelector<HTMLButtonElement>(
		`button[aria-label="${words['nowPlaying.closeSheet']({ sheet: words['nowPlaying.rightPanel'] })}"]`
	);
}

describeBackClosesOverlay({
	name: "the phone's Queue sheet over Now Playing",
	render: async () => {
		document.documentElement.dataset.pointer = 'coarse';
		const playback = info();
		audioPlayer.current = playback;
		openNowPlaying('queue');
		target = document.createElement('div');
		document.body.append(target);
		mounted = mount(NowPlaying, { target, props: { info: playback } });
		await tick();
		return target;
	},
	open: (target) => target.querySelector<HTMLButtonElement>('.mobile-panel-trigger')?.click(),
	isShown: (target) => target.querySelector('.mobile-sheet') !== null,
	closeWays: [
		{ way: 'a tap on the backdrop', close: (target) => sheetBackdrop(target)?.click() },
		{
			way: 'Escape',
			close: () =>
				window.dispatchEvent(
					new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
				)
		}
	],
	over: { name: words['transport.nowPlaying'], isShown: () => get(nowPlayingOpen) }
});

describe('NowPlaying when the take details cannot load', () => {
	afterEach(() => {
		resetConnectivityForTests();
		vi.useRealTimers();
	});

	it('adds no text of its own when the network is gone — the offline strip says it', async () => {
		reportResourceStreamReachable(false);
		vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
		await renderSurface(info());

		await ensureGenerationsLoaded('s1').catch(() => undefined);
		await tick();

		expect(fetch).toHaveBeenCalledWith('/api/songs/s1', expect.anything());
		const shown = [...get(toasts).map((toast) => toast.message), target.textContent].join(' ');
		expect(shown).not.toMatch(RegExp(`Failed to fetch|${words['nowPlaying.takeDetailsFailed']}`));
	});

	type PendingFetch = { resolve: (response: unknown) => void; reject: (error: Error) => void };

	// A retry after unmount fails too, making an unwanted reload observable.
	const settlingAfterUnmount = [
		{
			way: 'lost network',
			settle: (load: PendingFetch) => load.reject(new TypeError('Failed to fetch'))
		},
		{
			way: 'server refusal',
			settle: (load: PendingFetch) =>
				load.resolve({
					ok: false,
					status: 503,
					headers: new Headers(),
					json: async () => ({ detail: 'Song store is down' })
				})
		}
	];

	it.each(settlingAfterUnmount.map(({ way, settle }) => [way, settle] as const))(
		'1160-F46-wording defect:#1494: shows and loads nothing after unmount for %s',
		async (_way, settle) => {
			vi.useFakeTimers();
			let load!: PendingFetch;
			vi.stubGlobal(
				'fetch',
				vi
					.fn()
					.mockImplementationOnce(
						() => new Promise((resolve, reject) => (load = { resolve, reject }))
					)
					.mockRejectedValue(new TypeError('Failed to fetch'))
			);
			await renderSurface(info());
			await unmountSurface();

			settle(load);
			await vi.advanceTimersByTimeAsync(UNREACHABLE_RELOAD_DELAYS_MS.reduce((a, b) => a + b, 0));

			expect(get(toasts)).toEqual([]);
			expect(fetch).toHaveBeenCalledTimes(1);
		}
	);

	it('while no strip shows, loads again on a bounded backoff and then names the failure', async () => {
		vi.useFakeTimers();
		vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
		await renderSurface(info());
		await vi.advanceTimersByTimeAsync(0);
		expect(get(toasts)).toEqual([]);

		await vi.advanceTimersByTimeAsync(UNREACHABLE_RELOAD_DELAYS_MS.reduce((a, b) => a + b, 0));

		expect(fetch).toHaveBeenCalledTimes(1 + UNREACHABLE_RELOAD_DELAYS_MS.length);
		expect(get(toasts)).toEqual([
			expect.objectContaining({ type: 'error', message: words['nowPlaying.takeDetailsFailed'] })
		]);
	});

	it("names a refusal in the server's own words", async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn().mockResolvedValue({
				ok: false,
				status: 503,
				headers: new Headers(),
				json: async () => ({ detail: 'Song store is down' })
			})
		);
		await renderSurface(info());

		await vi.waitFor(() =>
			expect(get(toasts)).toEqual([
				expect.objectContaining({ type: 'error', message: 'Song store is down' })
			])
		);
	});
});

describe('NowPlaying source line on the phone (#1052)', () => {
	// A fetch that never answers keeps the collection a source opens from
	// reaching the network; the open itself is already visible in the stores.
	beforeEach(() => {
		document.documentElement.dataset.pointer = 'coarse';
		vi.stubGlobal(
			'fetch',
			vi.fn(() => new Promise(() => {}))
		);
	});

	const sources = [
		{
			name: 'an album',
			kind: 'album' as const,
			title: 'Nachtstrom',
			openLabel: words['nowPlaying.openAlbumSource']({ title: 'Nachtstrom' }),
			arrange: () => {
				albumList.set([album({ created_at: '' })]);
				queueContext.set({ type: 'album', albumId: 'a1' });
			},
			opens: { kind: 'album', id: 'a1' }
		},
		{
			name: 'a playlist',
			kind: 'playlist' as const,
			title: 'Night Drive',
			openLabel: words['nowPlaying.openPlaylistSource']({ title: 'Night Drive' }),
			arrange: () => {
				queueContext.set({
					type: 'playlist',
					playlist: { id: 'p1', title: 'Night Drive' },
					entries: [],
					index: 0
				});
			},
			opens: { kind: 'playlist', id: 'p1' }
		}
	];

	it.each(sources)(
		'says where $name playing comes from and opens it, leaving Now Playing',
		async ({ title, openLabel, arrange, opens }) => {
			arrange();
			await renderSurface(info());

			const from = target.querySelector<HTMLButtonElement>(`button[aria-label="${openLabel}"]`);
			expect(from?.textContent).toContain(`${nowPlayingFromLabel(title)} ›`);
			expect(from?.getAttribute('aria-label')?.startsWith(`${nowPlayingFromLabel(title)} `)).toBe(
				true
			);
			expect(target.textContent).not.toContain('Nachtstrom · Artist');
			expect(target.textContent).toContain(nowPlayingTakeLabel(1, 2));

			from?.click();

			expect(get(openCollection)).toEqual(opens);
			expect(get(nowPlayingSurface)).toBe('closed');
		}
	);

	it('names no source for a library queue and keeps the album line', async () => {
		queueContext.set({ type: 'library' });
		await renderSurface(info());

		expect(target.querySelector('.from-link')).toBeNull();
		expect(target.textContent).not.toContain('from ');
		expect(target.textContent).toContain('Nachtstrom · Artist');
	});

	it('keeps the album line on the desktop layout', async () => {
		document.documentElement.dataset.pointer = '';
		sources[0].arrange();
		await renderSurface(info());

		expect(target.querySelector('.from-link')).toBeNull();
		expect(target.textContent).toContain('Nachtstrom · Artist');
	});
});

describe('NowPlaying P and K keys', () => {
	function playingTake(isPicked: boolean, isKept: boolean): PlaybackInfo {
		const generations = [
			generation({
				generation_number: 2,
				created_at: '',
				id: 'g1',
				song_id: 's1',
				mp3_path: 's1.mp3',
				is_picked: isPicked,
				is_kept: isKept
			})
		];
		songList.set([song({ ...playingSongDefaults(), id: 's1', generations })]);
		const other = generation({ ...generations[0], id: 'g2', song_id: 's2' });
		const queued = [
			info({ generation: generations[0], songId: 's1', songTitle: 'Song 1' }),
			info({ generation: other, songId: 's2', songTitle: 'Song 2' })
		];
		queueContext.set({ type: 'album', albumId: 'a1', takes: queued, index: 0 });
		return queued[0];
	}

	function queueIndex(): number | false | undefined {
		const ctx = get(queueContext);
		return ctx.type === 'album' && ctx.index;
	}

	function press(key: string, init: KeyboardEventInit = {}): void {
		window.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, ...init }));
	}

	it.each([
		{
			name: 'P picks the playing take and stays on the song',
			key: 'p',
			picked: false,
			kept: false,
			action: togglePick
		},
		{
			name: 'P on the picked take unpicks it',
			key: 'p',
			picked: true,
			kept: false,
			action: togglePick
		},
		{
			name: 'K keeps the playing take and stays on the song',
			key: 'K',
			picked: false,
			kept: false,
			action: toggleKeep
		},
		{
			name: 'K on the kept take unkeeps it',
			key: 'k',
			picked: false,
			kept: true,
			action: toggleKeep
		}
	])('$name', async ({ key, picked, kept, action }) => {
		await renderSurface(playingTake(picked, kept));

		press(key);

		const take = expect.objectContaining({ is_picked: picked, is_kept: kept });
		await vi.waitFor(() => expect(action).toHaveBeenCalledWith('s1', take));
		expect(queueIndex()).toBe(0);
	});

	it('the keys act in a library queue too', async () => {
		await renderSurface(playingTake(false, false));
		queueContext.set({ type: 'library' });

		press('p');

		await vi.waitFor(() =>
			expect(togglePick).toHaveBeenCalledWith('s1', expect.objectContaining({ id: 'g1' }))
		);
	});

	it.each([
		{ name: 'S does nothing', key: 's', init: {} },
		{ name: 'P with a modifier held does nothing', key: 'p', init: { ctrlKey: true } }
	])('$name', async ({ key, init }) => {
		await renderSurface(playingTake(false, false));

		press(key, init);
		await tick();

		expect(queueIndex()).toBe(0);
		expect(togglePick).not.toHaveBeenCalled();
		expect(toggleKeep).not.toHaveBeenCalled();
	});

	it('ignores the keys while a text field has focus', async () => {
		await renderSurface(playingTake(false, false));
		const textarea = document.createElement('textarea');
		target.append(textarea);
		textarea.focus();

		textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'p', bubbles: true }));
		await tick();

		expect(togglePick).not.toHaveBeenCalled();
	});
});
