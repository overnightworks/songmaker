import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
	TRANSPORT_PAUSE_LABEL,
	TRANSPORT_PLAY_LABEL,
	SONG_NEXT_LABEL,
	SONG_PREVIOUS_LABEL
} from '$lib/constants';
import { shownTransportFace } from '$lib/test-utils/transport-face';
import { NOW_PLAYING_PLAY_AGAIN_LABEL } from '$lib/constants/now-playing';
import { SHARE_NO_AUDIO_NOTICE } from '$lib/constants/share';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import type { PlaybackInfo } from '$lib/services/playbackTypes';
import {
	trackPlaybackInfo,
	type SharedCollectionView,
	type SharedTrack
} from '$lib/share/sharedCollection';
import { accessibleName, getByRoleButton } from '$lib/test-utils/accessible-name';
import { LEGAL_SECTIONS } from '$lib/constants/legal';
import nowPlayingFrameSource from '../NowPlayingFrame.svelte?raw';
import sharedCollectionSource from './SharedCollection.svelte?raw';
import SharedCollection from './SharedCollection.svelte';

// jsdom never computes layout (dvh/overflow), so the scroll contract is
// pinned at the source level, matching layout.test.ts's `.app-shell.mobile`
// check for the private app shell.
function extractRule(source: string, selector: string): string {
	const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
	const match = new RegExp(`${escaped}\\s*{([^}]*)}`).exec(source);
	if (!match) throw new Error(`Expected rule ${selector} in stylesheet`);
	return match[1];
}

let mounted: ReturnType<typeof mount> | undefined;
const originalScrollIntoView = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollIntoView');

// jsdom plays no media: its element neither loads nor pauses, and says so
// on every share page, since each one first clears the player it takes over.
beforeEach(() => {
	// jsdom has no intersections; visibility scenarios install a controllable observer.
	vi.stubGlobal(
		'IntersectionObserver',
		vi.fn(
			class {
				observe = vi.fn();
				disconnect = vi.fn();
			}
		)
	);
	vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {});
	vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	audioPlayer.status = 'idle';
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
	if (originalScrollIntoView)
		Object.defineProperty(Element.prototype, 'scrollIntoView', originalScrollIntoView);
	else Reflect.deleteProperty(Element.prototype, 'scrollIntoView');
});

const DETAIL_COVER = { card: '/covers/card.jpg', detail: '/covers/detail.jpg' };

async function renderShare(view: Partial<SharedCollectionView> = {}): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(SharedCollection, {
		target,
		props: {
			loading: false,
			errorKind: null,
			resource: 'album',
			view: {
				kind: 'album',
				title: 'Open Windows',
				artist: 'Felix',
				albumTitle: null,
				year: null,
				cover: null,
				playlistCovers: [],
				tracks: [],
				...view
			},
			fetchStream: null
		}
	});
	await tick();
	return target;
}

function sharedTrack(key: string, title: string, media: Partial<SharedTrack> = {}): SharedTrack {
	return {
		key,
		title,
		subtitle: null,
		audioUrl: `/shared/playlist/mix/audio/${key}.mp3`,
		durationSec: 120,
		lyrics: null,
		cues: null,
		cover: null,
		albumTitle: null,
		...media
	};
}

function stubLayout(stacked: boolean): void {
	vi.stubGlobal(
		'matchMedia',
		vi.fn(() => ({ matches: stacked, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
	);
}

function observeTransports(): Map<Element, (visible: boolean) => void> {
	const observed = new Map<Element, (visible: boolean) => void>();
	vi.stubGlobal(
		'IntersectionObserver',
		class {
			private target?: Element;
			constructor(
				private callback: (entries: Pick<IntersectionObserverEntry, 'isIntersecting'>[]) => void
			) {}
			observe(target: Element): void {
				this.target = target;
				observed.set(target, (visible) => this.callback([{ isIntersecting: visible }]));
			}
			disconnect(): void {
				if (this.target) observed.delete(this.target);
			}
		}
	);
	return observed;
}

function buttonNames(root: ParentNode): string[] {
	return Array.from(root.querySelectorAll('button')).map(accessibleName);
}

describe('SharedCollection page root', () => {
	it('is its own scroll container, filling the viewport height html/body clip to', () => {
		const rule = extractRule(sharedCollectionSource, '.shared-page');
		expect(rule).toContain('height: 100dvh');
		expect(rule).toContain('overflow-y: auto');
	});

	// A phone keeps the sung line on screen (#1391): the page is a column of
	// the screen's height, the stacked player is exactly that height and its
	// words take what the player leaves; Play again keeps Play's row height at
	// the end. The e2e share spec measures it at every phone height.
	it.each([
		{ source: sharedCollectionSource, selector: '.shared-page.player-page', rule: 'display: flex' },
		{
			source: nowPlayingFrameSource,
			selector: '.now-playing.page.stacked',
			rule: 'container-type: size'
		},
		{
			source: nowPlayingFrameSource,
			selector: '.now-playing.page.stacked .np-player-col',
			rule: 'align-self: stretch'
		},
		{
			source: nowPlayingFrameSource,
			selector: '.now-playing.page.stacked .np-page-lyrics',
			rule: 'flex: 1 1 0'
		},
		{
			source: nowPlayingFrameSource,
			selector: '.now-playing.page .transport',
			rule: 'min-height: var(--page-play-size)'
		}
	])('lays the player page out with $selector { $rule }', ({ source, selector, rule }) => {
		expect(extractRule(source, selector)).toContain(rule);
	});

	it('shows an album cover on a shared album and falls back cleanly without one', async () => {
		const withCover = await renderShare({
			cover: DETAIL_COVER,
			tracks: [sharedTrack('e1', 'Tide')]
		});
		const image = withCover.querySelector<HTMLImageElement>('.cover-art img');
		expect(image?.src).toContain('/covers/detail.jpg');
		expect(image?.alt).toBe('');

		if (mounted) await unmount(mounted);
		mounted = undefined;
		withCover.remove();

		const withoutCover = await renderShare({ tracks: [sharedTrack('e1', 'Tide')] });
		expect(withoutCover.querySelector('.cover-art img')).toBeNull();
		expect(withoutCover.querySelector('h1')?.textContent).toBe('Open Windows');
	});

	it('1374_rule_10 shows a shared playlist upload, mosaic, and fallback through the player artwork', async () => {
		const upload = await renderShare({
			kind: 'playlist',
			tracks: [sharedTrack('first', 'Tide')],
			cover: {
				card: '/shared/playlist/mix/cover?variant=card&v=uploaded.png',
				detail: '/shared/playlist/mix/cover?variant=detail&v=uploaded.png'
			}
		});
		expect(
			upload.querySelector<HTMLImageElement>('.cover-art .playlist-cover-image')?.src
		).toContain('/shared/playlist/mix/cover?variant=card&v=uploaded.png');

		if (mounted) await unmount(mounted);
		mounted = undefined;
		upload.remove();

		const mosaic = await renderShare({
			kind: 'playlist',
			tracks: [sharedTrack('first', 'Tide')],
			playlistCovers: [
				{
					card: '/shared/playlist/mix/album-cover/a1?variant=card&v=album.png',
					detail: '/shared/playlist/mix/album-cover/a1?variant=detail&v=album.png'
				}
			]
		});
		expect(mosaic.querySelectorAll('.playlist-cover-cell')).toHaveLength(4);
		expect(mosaic.querySelector<HTMLImageElement>('.playlist-cover-cell img')?.src).toContain(
			'/shared/playlist/mix/album-cover/a1?variant=card&v=album.png'
		);

		if (mounted) await unmount(mounted);
		mounted = undefined;
		mosaic.remove();

		const fallback = await renderShare({
			kind: 'playlist',
			tracks: [sharedTrack('first', 'Tide')]
		});
		expect(fallback.querySelectorAll('.playlist-cover-cell')).toHaveLength(4);
		expect(fallback.querySelectorAll('.playlist-cover-cell img')).toHaveLength(0);
		expect(fallback.querySelectorAll('.playlist-cover-initials')).toHaveLength(4);
	});
});

describe('SharedCollection player page (#1391)', () => {
	const LYRIC_LINE = 'Streetlights hum a borrowed tune';
	const PAGE_CASES = (['song', 'take'] as const).flatMap((kind) =>
		[true, false].map((stacked) => ({ kind, stacked }))
	);

	function renderSharedSong(
		kind: 'song' | 'take',
		media: Partial<SharedTrack> = {}
	): Promise<HTMLElement> {
		return renderShare({
			kind,
			title: 'Neon Tide',
			artist: 'Mara Lind',
			albumTitle: 'Glass Rivers',
			cover: DETAIL_COVER,
			tracks: [sharedTrack('single', 'Neon Tide', { durationSec: 180, ...media })]
		});
	}

	it.each(PAGE_CASES)(
		'opens a shared $kind as the player and offers nothing else (stacked: $stacked)',
		async ({ kind, stacked }) => {
			stubLayout(stacked);
			const target = await renderSharedSong(kind, { lyrics: LYRIC_LINE });

			expect(target.querySelector('h1')?.textContent).toBe('Neon Tide');
			expect(target.textContent).toContain('Glass Rivers · Mara Lind');
			expect(target.querySelector<HTMLImageElement>('.cover-art img')?.src).toContain(
				'/covers/detail.jpg'
			);
			expect(target.querySelector('.progress-times')?.textContent).toContain('3:00');
			expect(target.querySelector('.np-lyrics')?.textContent).toContain(LYRIC_LINE);
			expect(buttonNames(document.body)).toEqual([TRANSPORT_PLAY_LABEL]);
			expect(
				Array.from(document.querySelectorAll('a')).map((link) => link.getAttribute('href'))
			).toEqual(['/', ...LEGAL_SECTIONS.map((section) => section.href)]);
			expect(target.querySelectorAll('.track-row')).toHaveLength(0);
			expect(document.querySelector('.player-bar')).toBeNull();
			expect(document.querySelector('[role="dialog"]')).toBeNull();
		}
	);

	// Two lines sung two seconds each, the first from 0:00.
	const SUNG_LINES = ['Streetlights hum a borrowed tune', 'Every window holds the moon'];
	const TIMED_LYRICS: Partial<SharedTrack> = {
		lyrics: SUNG_LINES.join('\n'),
		cues: [
			{ start: 0, end: 2, text: SUNG_LINES[0] },
			{ start: 2, end: 4, text: SUNG_LINES[1] }
		]
	};

	// A take of the listener's own library, playing in the signed-in app.
	function appTake(): PlaybackInfo {
		const library: SharedCollectionView = {
			kind: 'album',
			title: 'Private Drafts',
			artist: 'Felix',
			albumTitle: null,
			year: null,
			cover: null,
			playlistCovers: [],
			tracks: []
		};
		return trackPlaybackInfo(
			library,
			sharedTrack('private-take', 'Private Draft', { durationSec: 240 })
		);
	}

	function shownTimes(target: HTMLElement): string[] {
		return Array.from(target.querySelectorAll('.progress-times .time')).map(
			(time) => time.textContent ?? ''
		);
	}

	async function litLines(target: HTMLElement): Promise<string[]> {
		await vi.waitFor(() =>
			expect(target.querySelectorAll('.lyrics-line')).toHaveLength(SUNG_LINES.length)
		);
		return Array.from(target.querySelectorAll('.lyrics-line.active')).map(
			(line) => line.textContent?.trim() ?? ''
		);
	}

	it.each(['song', 'take'] as const)(
		'shows none of the take the app was playing when a shared %s opens',
		async (kind) => {
			stubLayout(true);
			audioPlayer.loadUrl(appTake(), '/audio/private-take.mp3', { autoplay: false, startAt: 75 });

			const target = await renderSharedSong(kind);

			expect({
				times: shownTimes(target),
				held: audioPlayer.current,
				named: document.body.textContent?.includes('Private Draft')
			}).toEqual({ times: ['0:00', '3:00'], held: null, named: false });
		}
	);

	it.each(['song', 'take'] as const)(
		'keeps playing a shared %s once Play is pressed, while the app still owned the player',
		async (kind) => {
			stubLayout(true);
			// The app's own callbacks read the player's state when its take goes
			// (stores/player#handleCurrentChange), and the page takes the player
			// over while they are installed.
			const appCallbacks = audioPlayer.swapCallbacks({
				...audioPlayer.currentCallbacks,
				onCurrentChange: () => void audioPlayer.status
			});
			const target = await renderSharedSong(kind);

			getByRoleButton(target, TRANSPORT_PLAY_LABEL).click();
			await tick();
			const playing = audioPlayer.current?.songTitle ?? null;
			if (mounted) await unmount(mounted);
			mounted = undefined;
			audioPlayer.restoreCallbacks(appCallbacks);

			expect(playing).toBe('Neon Tide');
		}
	);

	it('shows where Play will start once the slider is tapped before Play', async () => {
		stubLayout(true);
		const target = await renderSharedSong('song');
		const slider = target.querySelector<HTMLInputElement>('.seek-input');
		if (!slider) throw new Error('Expected the seek slider');

		slider.value = '60';
		slider.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();

		expect({
			times: shownTimes(target),
			play: getByRoleButton(target, TRANSPORT_PLAY_LABEL) !== undefined
		}).toEqual({ times: ['1:00', '3:00'], play: true });
	});

	it('lights no line before the first Play, though the first one is sung from 0:00', async () => {
		stubLayout(true);
		const target = await renderSharedSong('song', TIMED_LYRICS);

		expect(await litLines(target)).toEqual([]);
	});

	it('at the end offers Play again, keeps the slider there and lights no line', async () => {
		stubLayout(true);
		const target = await renderSharedSong('song', TIMED_LYRICS);
		getByRoleButton(target, TRANSPORT_PLAY_LABEL).click();
		audioPlayer.currentTime = 3;
		await tick();
		const whilePlaying = await litLines(target);

		audioPlayer.getElement()?.dispatchEvent(new Event('ended'));
		await tick();

		expect({
			whilePlaying,
			atTheEnd: await litLines(target),
			times: shownTimes(target),
			again: target
				.querySelector('.play-again')
				?.textContent?.includes(NOW_PLAYING_PLAY_AGAIN_LABEL)
		}).toEqual({
			whilePlaying: [SUNG_LINES[1]],
			atTheEnd: [],
			times: ['3:00', '3:00'],
			again: true
		});
	});

	it.each(['song', 'take'] as const)(
		'defect:#1374 dims Play on a shared %s without audio, says why and shows no lyrics block',
		async (kind) => {
			stubLayout(true);
			const target = await renderSharedSong(kind, { audioUrl: null });

			expect(getByRoleButton(target, TRANSPORT_PLAY_LABEL).disabled).toBe(true);
			expect(target.querySelector('[role="status"]')?.textContent).toBe(SHARE_NO_AUDIO_NOTICE);
			expect(target.querySelector('.np-page-lyrics')).toBeNull();
			expect(target.textContent).not.toContain('No lyrics');
		}
	);
});

describe.each(['album', 'playlist'] as const)('Shared %s player page', (kind) => {
	const renderCollection = (view: Partial<SharedCollectionView> = {}) =>
		renderShare({ kind, ...view });
	it('1374_rule_2 A6 shows No lyrics for the staged first song', async () => {
		stubLayout(true);
		const target = await renderCollection({ tracks: [sharedTrack('first', 'Tide')] });
		expect(target.querySelector('h1')?.textContent).toBe('Open Windows');
		expect(target.querySelector('.lyrics-heading')?.textContent).toBe('Lyrics · Tide');
		expect(target.querySelector('.lyrics-empty')?.textContent).toBe('No lyrics');
		expect(target.querySelector('.now-playing-line')?.textContent).toBe(
			'Now playing · Tide · 1 of 1'
		);
		expect(audioPlayer.current).toBeNull();
	});

	it('1374_rule_5 B5 lists and stages only playable songs', async () => {
		stubLayout(false);
		const target = await renderCollection({
			tracks: [
				sharedTrack('silent', 'Unpicked', { audioUrl: null, lyrics: 'Private words' }),
				sharedTrack('first', 'Tide', { lyrics: 'Public words' })
			]
		});
		expect(
			Array.from(target.querySelectorAll('.queue-title')).map((row) => row.textContent)
		).toEqual(['Tide']);
		expect(target.querySelector('.np-page-lyrics')?.textContent).toContain('Public words');
		expect(target.textContent).not.toContain('Unpicked');
		expect(target.textContent).not.toContain('Private words');
		getByRoleButton(target, TRANSPORT_PLAY_LABEL).click();
		await tick();
		expect(audioPlayer.current?.songTitle).toBe('Tide');
	});

	it.each([{ tracks: [] }, { tracks: [sharedTrack('silent', 'Unpicked', { audioUrl: null })] }])(
		'1374_rule_2 B6 shows only the title and notice when no song is playable (%j)',
		async ({ tracks }) => {
			const target = await renderCollection({ tracks });
			expect(target.querySelector('h1')?.textContent).toBe('Open Windows');
			expect(target.querySelector('[role="status"]')?.textContent).toBe(SHARE_NO_AUDIO_NOTICE);
			expect(target.querySelector('.now-playing, .np-lyrics, .np-queue')).toBeNull();
			expect(audioPlayer.current).toBeNull();
		}
	);

	it('1374_rule_14 C3 seeking before Play readies song 1 paused', async () => {
		stubLayout(true);
		const target = await renderCollection({
			tracks: [sharedTrack('first', 'Tide'), sharedTrack('second', 'Ebb')]
		});
		const slider = target.querySelector<HTMLInputElement>('.seek-input');
		if (!slider) throw new Error('Expected the album seek slider');
		slider.value = '45';
		slider.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();
		expect(audioPlayer.current?.songTitle).toBe('Tide');
		expect(audioPlayer.currentTime).toBe(45);
		expect(audioPlayer.transport).toBe('paused');
		expect(getByRoleButton(target, TRANSPORT_PLAY_LABEL)).toBeDefined();
	});

	it('1374_rule_2 C1 skips from the staged song to song 2 and back', async () => {
		stubLayout(false);
		const target = await renderCollection({
			tracks: [sharedTrack('first', 'Tide'), sharedTrack('second', 'Ebb')]
		});
		expect(getByRoleButton(target, SONG_PREVIOUS_LABEL).disabled).toBe(true);
		expect(getByRoleButton(target, SONG_NEXT_LABEL).disabled).toBe(false);
		getByRoleButton(target, SONG_NEXT_LABEL).click();
		await tick();
		expect(audioPlayer.current?.songTitle).toBe('Ebb');
		expect(getByRoleButton(target, SONG_NEXT_LABEL).disabled).toBe(true);
		getByRoleButton(target, SONG_PREVIOUS_LABEL).click();
		await tick();
		expect(audioPlayer.current?.songTitle).toBe('Tide');
		expect(target.querySelectorAll('h1')).toHaveLength(1);
		expect(target.querySelector('h1')?.textContent).toBe('Open Windows');
	});

	it.each([true, false])(
		'1374_rule_2 F1 shows no editing or source affordances (stacked: %s)',
		async (stacked) => {
			stubLayout(stacked);
			const target = await renderCollection({ tracks: [sharedTrack('first', 'Tide')] });
			expect(target.querySelector('.queue-heading')?.textContent).toBe('Songs');
			expect(
				target.querySelector('.queue-take, .from-link, .go-to-song, [data-icon="pencil"]')
			).toBeNull();
			expect(buttonNames(target).some((name) => /edit|go to song|take/i.test(name))).toBe(false);
			expect(
				Array.from(target.querySelectorAll('a')).map((link) => link.getAttribute('href'))
			).toEqual(['/', ...LEGAL_SECTIONS.map((section) => section.href)]);
		}
	);

	it('1374_rule_5 B2 B3 changes the marked song and pauses its playing row', async () => {
		stubLayout(false);
		const target = await renderCollection({
			tracks: [sharedTrack('first', 'Tide'), sharedTrack('second', 'Ebb', { lyrics: 'Ebb words' })]
		});
		target.querySelectorAll<HTMLButtonElement>('.queue-row')[1].click();
		await tick();
		audioPlayer.status = 'playing';
		await tick();
		expect(target.querySelector('.queue-row.current .queue-title')?.textContent).toBe('Ebb');
		expect(getByRoleButton(target, TRANSPORT_PAUSE_LABEL)).toBeDefined();
		expect(target.querySelector('.now-playing-line')?.textContent).toBe(
			'Now playing · Ebb · 2 of 2'
		);
		expect(target.querySelector('.np-page-lyrics')?.textContent).toContain('Ebb words');
		target.querySelector<HTMLButtonElement>('.queue-row.current')?.click();
		await tick();
		expect(audioPlayer.transport).toBe('paused');
	});
});

describe('Shared collection scroll bar', () => {
	it.each(['album', 'playlist', 'song', 'take'] as const)(
		'1374_rule_16 E5 reserves room and follows transport visibility for collections (%s)',
		async (kind) => {
			stubLayout(true);
			const observed = observeTransports();
			const scrollIntoView = vi.fn();
			Object.defineProperty(Element.prototype, 'scrollIntoView', {
				configurable: true,
				value: scrollIntoView
			});
			const target = await renderShare({
				kind,
				tracks: [sharedTrack('first', 'Tide'), sharedTrack('second', 'Ebb')]
			});
			const reportVisibility = async (visible: boolean) => {
				for (const report of observed.values()) report(visible);
				await tick();
			};
			await reportVisibility(false);
			expect(document.querySelector('footer.player-bar')).toBeNull();
			getByRoleButton(target, TRANSPORT_PLAY_LABEL).click();
			await tick();
			expect(target.querySelector('.bar-room') !== null).toBe(
				kind === 'album' || kind === 'playlist'
			);
			await reportVisibility(false);
			expect(document.querySelector('footer.player-bar') !== null).toBe(
				kind === 'album' || kind === 'playlist'
			);
			if (kind === 'album' || kind === 'playlist') {
				getByRoleButton(target, SONG_NEXT_LABEL).click();
				await tick();
				await reportVisibility(false);
				expect(document.querySelector('footer.player-bar')).not.toBeNull();
				expect(document.querySelector('footer.player-bar')?.textContent).toContain('Ebb');
				document.querySelector<HTMLButtonElement>('footer.player-bar .open-now-playing')?.click();
				expect(scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth' });
				await reportVisibility(true);
				expect(document.querySelector('footer.player-bar')).toBeNull();
			}
			if (mounted) await unmount(mounted);
			mounted = undefined;
			expect(observed.size).toBe(0);
		}
	);
});

describe('Shared playlist metadata and artwork', () => {
	it('1374_rule_5 keeps album subtitles with entry identities through shuffle and row selection', async () => {
		stubLayout(false);
		const tracks = ['a', 'b', 'c'].map((key, index) =>
			sharedTrack(key, `Song ${key}`, {
				albumTitle: `Album ${key}`,
				subtitle: `Artist ${key}`,
				durationSec: 60 + index
			})
		);
		const target = await renderShare({ kind: 'playlist', tracks });
		expect(target.querySelector('.cover-line')?.textContent).toBe('Playlist · 3 songs');
		const rows = () => Array.from(target.querySelectorAll<HTMLButtonElement>('.queue-row'));
		const assertLabels = () => {
			for (const row of rows()) {
				const key = row.querySelector('.queue-title')?.textContent?.slice(-1);
				expect(row.querySelector('.queue-subtitle')?.textContent).toBe(`Album ${key}`);
			}
		};
		assertLabels();
		expect(rows().map((row) => row.querySelector('.queue-duration')?.textContent)).toEqual([
			'1:00',
			'1:01',
			'1:02'
		]);
		rows()[1].click();
		await tick();
		getByRoleButton(target, 'Shuffle').click();
		await tick();
		assertLabels();
		expect(audioPlayer.current?.albumTitle).toBe('Album b');
		expect(target.querySelector('.queue-row.current .queue-title')?.textContent).toBe('Song b');
		getByRoleButton(target, 'Disable shuffle').click();
		await tick();
		expect(rows().map((row) => row.querySelector('.queue-title')?.textContent)).toEqual([
			'Song a',
			'Song b',
			'Song c'
		]);
		assertLabels();
	});

	it('1374_rule_10 recovers transport artwork after missing and failed song covers', async () => {
		stubLayout(false);
		const observed = observeTransports();
		const target = await renderShare({
			kind: 'playlist',
			cover: DETAIL_COVER,
			tracks: [
				sharedTrack('missing', 'Missing Cover'),
				sharedTrack('broken', 'Broken Cover', {
					cover: { card: '/broken.jpg', detail: '/broken.jpg' }
				}),
				sharedTrack('covered', 'Covered Song', {
					cover: { card: '/song.jpg', detail: '/song.jpg' }
				})
			]
		});
		const select = async (index: number) => {
			target.querySelectorAll<HTMLButtonElement>('.queue-row')[index].click();
			await tick();
			for (const report of observed.values()) report(false);
			await tick();
		};
		await select(0);
		expect(target.querySelector('.track-cover')?.textContent?.trim()).toBe('MC');
		await select(1);
		const failed = target.querySelector<HTMLImageElement>('.track-cover img');
		expect(failed?.getAttribute('src')).toBe('/broken.jpg');
		failed?.dispatchEvent(new Event('error'));
		await tick();
		expect(target.querySelector('.track-cover')?.textContent?.trim()).toBe('BC');
		await select(2);
		expect(target.querySelector('.track-cover img')?.getAttribute('src')).toBe('/song.jpg');
		expect(target.querySelector('.cover-art .playlist-cover-image')?.getAttribute('src')).toBe(
			DETAIL_COVER.card
		);
		expect(target.querySelector('[role="dialog"], .now-playing-btn')).toBeNull();
	});

	it.each([
		{ status: 'playing', busy: 'false', face: 'pause' },
		{ status: 'buffering', busy: 'true', face: 'spinner' },
		{ status: 'error', busy: 'false', face: 'refresh-cw' }
	] as const)(
		'1374_rule_2 shows the $status transport state on the player',
		async ({ status, busy, face }) => {
			stubLayout(false);
			const target = await renderShare({
				kind: 'playlist',
				tracks: [sharedTrack('first', 'Tide')]
			});
			getByRoleButton(target, TRANSPORT_PLAY_LABEL).click();
			await tick();
			audioPlayer.status = status;
			await tick();
			const button = target.querySelector('.play-btn');
			expect({ busy: button?.getAttribute('aria-busy'), face: shownTransportFace(button) }).toEqual(
				{ busy, face }
			);
		}
	);
});
