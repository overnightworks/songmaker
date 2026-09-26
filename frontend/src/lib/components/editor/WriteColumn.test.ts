import { makeGeneration as generation, makeSong as song } from '$lib/test-utils/factories';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

vi.mock('$lib/api/client', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/api/client')>();
	return {
		...actual,
		fetchConversations: vi.fn().mockResolvedValue([]),
		fetchConversationMessages: vi.fn().mockResolvedValue({ messages: [] }),
		startNewConversation: vi.fn(),
		deleteConversation: vi.fn(),
		fetchMemory: vi.fn().mockResolvedValue(null),
		fetchCowriterSettings: vi.fn().mockResolvedValue({ provider: 'claude', model: '' }),
		fetchVersions: vi.fn().mockResolvedValue([])
	};
});
import { editLyrics, loadSongData } from '$lib/stores/editor';
import { nowPlayingOpen } from '$lib/stores/player';
import { setQueuePlaybackMode } from '$lib/stores/playbackSettings';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import type { SongItem } from '$lib/api/types';
import WriteColumn from './WriteColumn.svelte';
import writeColumnSource from './WriteColumn.svelte?raw';
import coWriterPanelSource from '../CoWriterPanel.svelte?raw';
import takeStripSource from './TakeStrip.svelte?raw';
import { clearComponentStyles, injectComponentStyles } from '$lib/test-utils/component-styles';

function draftSongDefaults(): Partial<SongItem> {
	return {
		slug: 'test',
		title: 'Test',
		lyrics: 'verse one',
		prompt: 'rock',
		generations: [generation()],
		created_at: ''
	};
}

const mounted: Array<ReturnType<typeof mount>> = [];

beforeEach(() => {
	loadSongData(song(draftSongDefaults()));
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	clearComponentStyles();
});

async function render(overrides: Partial<Record<string, unknown>> = {}) {
	const target = document.createElement('div');
	document.body.append(target);
	const props = {
		song: song(draftSongDefaults()),
		allSongs: [song(draftSongDefaults())],
		coWriterOpen: false,
		compact: false,
		onturncompleted: vi.fn(),
		...overrides
	};
	mounted.push(mount(WriteColumn, { target, props }));
	await tick();
	await Promise.resolve();
	await tick();
	return { target, props };
}

describe('WriteColumn write mode', () => {
	it('edits Style and Lyrics against the shared editor draft', async () => {
		const { target } = await render();
		const lyrics = target.querySelector<HTMLTextAreaElement>('.lyrics-area');
		if (!lyrics) throw new Error('Expected a lyrics textarea');
		expect(lyrics.value).toBe('verse one');
		lyrics.value = 'verse two';
		lyrics.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();
		expect(get(editLyrics)).toBe('verse two');
	});
});

describe('WriteColumn Co-Writer mode', () => {
	// The phone screen that replaces the page (#990) instantiates CoWriterPanel
	// directly and never reaches WriteColumn's coWriterOpen branch, so that
	// branch no longer varies by `compact` — one shape, chat + lyrics + take
	// strip, regardless of the prop.
	it.each([
		['desktop', false],
		['a compact caller', true]
	])(
		'shows Chat, Lyrics and the take strip together with %s, no mobile sub-tabs',
		async (_, compact) => {
			const { target } = await render({ coWriterOpen: true, compact });
			expect(target.querySelector('.cowriter-chat')).not.toBeNull();
			expect(target.querySelector('.cowriter-lyrics')).not.toBeNull();
			expect(target.querySelector('.cowriter-takes')).not.toBeNull();
			expect(target.querySelector('.mobile-subtabs')).toBeNull();
		}
	);

	it('shows the kinetic take strip in compact Write mode only', async () => {
		const { target } = await render({ compact: true });
		expect(target.querySelector('.compact-takes .take-strip')).not.toBeNull();
	});

	it('plays a take from the strip on click without opening Now Playing', async () => {
		// Classic mode makes playTake's audioPlayer.load call synchronous and
		// deterministic — no library-pool API round trip to mock. Asserting on
		// audioPlayer (the real playback boundary) instead of a re-exported
		// player.ts function exercises TakeStrip's actual entry point,
		// playTake, rather than stubbing it out from under the click handler.
		// The spy is scoped and restored locally so it never bleeds into the
		// module-level $lib/api/client mocks the other tests in this file rely
		// on being set once at module load.
		setQueuePlaybackMode('classic');
		const loadSpy = vi.spyOn(audioPlayer, 'load').mockImplementation((info) => {
			audioPlayer.current = info;
		});
		try {
			const gen = generation({ id: 'g9' });
			const targetSong = song({ ...draftSongDefaults(), generations: [gen] });
			const { target } = await render({
				coWriterOpen: true,
				song: targetSong
			});
			target.querySelector<HTMLButtonElement>('.take-chip')?.click();
			await tick();
			await Promise.resolve();
			expect(audioPlayer.load).toHaveBeenCalledWith(
				expect.objectContaining({
					generation: expect.objectContaining({ id: gen.id }),
					songId: targetSong.id
				}),
				expect.objectContaining({ restart: true })
			);
			expect(get(nowPlayingOpen)).toBe(false);
		} finally {
			loadSpy.mockRestore();
			audioPlayer.current = null;
		}
	});
});

describe("WriteColumn Co-Writer at the editor's own width", () => {
	// jsdom computes no grid layout, so this pins the stylesheet; the browser
	// gate on #185 reads the Co-Writer beside a docked Now Playing.
	it('stacks chat, lyrics and the take strip until the editor has room for three', () => {
		expect(writeColumnSource).toMatch(
			/\.cowriter-columns \{[^}]*grid-template-columns: minmax\(0, 1fr\);/
		);
		expect(writeColumnSource).toMatch(
			/@container editor \(min-width: 680px\) \{[^@]*\.cowriter-columns \{\s*grid-template-columns: minmax\(0, 1fr\) minmax\(0, 1fr\) auto;/
		);
	});

	it('lets the stacked parts run on rather than share one squeezed height', () => {
		// Sharing it cut the lyrics column below its content, which then spilled
		// over the take strip; only a part with a column of its own can scroll
		// in place.
		const stacked = /\n\t\.cowriter-mode \{([^}]*)\}/.exec(writeColumnSource)?.[1];
		expect(stacked).toBeDefined();
		expect(stacked).not.toMatch(/\bheight: 100%/);
		expect(writeColumnSource).toMatch(
			/@container editor \(min-width: 680px\) \{\s*\.cowriter-mode \{\s*flex: 1;\s*min-height: 0;/
		);
	});

	// jsdom knows no container queries, so a mounted Co-Writer here is the
	// stacked one: the case where the chat column has no row to take a height
	// from. Reading the values out of the real cascade is what tells the
	// difference between a column the conversation scrolls inside and one that
	// grows past the fold, taking the composer with it.
	it('gives the stacked chat column a bound its conversation scrolls inside', async () => {
		const { target } = await render({ coWriterOpen: true, compact: false });
		const chat = target.querySelector('.cowriter-chat');
		if (!chat) throw new Error('Expected a chat column');
		injectComponentStyles(writeColumnSource, 'WriteColumn.svelte', chat);
		const messages = chat.querySelector('.messages');
		if (!messages) throw new Error('Expected a message list');
		injectComponentStyles(coWriterPanelSource, 'CoWriterPanel.svelte', messages);

		expect(getComputedStyle(chat).height).not.toBe('auto');
		expect(getComputedStyle(messages).overflowY).toBe('auto');
		expect(chat.querySelector('.input-area')).not.toBeNull();
	});

	// jsdom computes no layout, so a share of a real window's height can only
	// be read back out of the declaration, not out of getComputedStyle: this
	// pins the clamp itself rather than a number it can't produce. Docking Now
	// Playing narrows the editor below the two-up floor right where the
	// header wraps to three lines, and a bare 60dvh ran past `.editor-body`'s
	// own visible height there — the composer sat behind a scroll of the
	// wrong container (#185). The browser gate at 1100×800 and 1280×800 with
	// the dock open reads the composer against the real cascade.
	it('bounds the stacked chat height to what a narrowed editor actually has, not just the window', () => {
		expect(writeColumnSource).toMatch(
			/\.cowriter-chat \{\s*height: min\(60dvh, calc\(100dvh - \d+px\)\);/
		);
	});

	it('gives the stacked take strip the whole row it scrolls sideways in', async () => {
		const { target } = await render({ coWriterOpen: true, compact: false });
		const takes = target.querySelector('.cowriter-takes');
		if (!takes) throw new Error('Expected a take strip column');
		injectComponentStyles(writeColumnSource, 'WriteColumn.svelte', takes);
		const strip = takes.querySelector('.take-strip');
		if (!strip) throw new Error('Expected a take strip');
		injectComponentStyles(takeStripSource, 'TakeStrip.svelte', strip);

		// Centred, the strip sized to its chips rather than to the row, so
		// nothing ever overflowed it and the editor body clipped the chips past
		// the fold away instead.
		expect(getComputedStyle(takes).alignItems).toBe('stretch');
		expect(getComputedStyle(strip).overflowX).toBe('auto');
	});
});
