import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
	PLAYING_MARK_LABEL,
	collectionActionLabel,
	TRANSPORT_PAUSE_LABEL,
	TRANSPORT_PLAY_LABEL
} from '$lib/constants';
import { SHARE_NO_AUDIO_NOTICE } from '$lib/constants/share';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import type { SharedCollectionView, SharedTrack } from '$lib/share/sharedCollection';
import { accessibleName, getByRoleButton } from '$lib/test-utils/accessible-name';
import { LEGAL_SECTIONS } from '../LegalLinks.svelte';
import { shownTransportFace } from '$lib/test-utils/transport-face';
import { findElementByRoleAndName } from '../shell/rail-test-fixtures';
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

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	audioPlayer.status = 'idle';
	vi.unstubAllGlobals();
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
		...media
	};
}

function stubLayout(stacked: boolean): void {
	vi.stubGlobal(
		'matchMedia',
		vi.fn(() => ({ matches: stacked, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
	);
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

	it('shows an album cover on a shared album and falls back cleanly without one', async () => {
		const withCover = await renderShare({ cover: DETAIL_COVER });
		const image = withCover.querySelector<HTMLImageElement>('.header-cover img');
		expect(image?.src).toContain('/covers/detail.jpg');
		expect(image?.alt).toBe('Album Open Windows');

		if (mounted) await unmount(mounted);
		mounted = undefined;
		withCover.remove();

		const withoutCover = await renderShare();
		expect(withoutCover.querySelector('.header-cover img')).toBeNull();
		expect(withoutCover.querySelector('.header-cover-initials')?.textContent).toBe('OW');
	});

	it('shows a shared playlist upload, mosaic, and fallback through the shared cover tile', async () => {
		const upload = await renderShare({
			kind: 'playlist',
			cover: {
				card: '/shared/playlist/mix/cover?variant=card&v=uploaded.png',
				detail: '/shared/playlist/mix/cover?variant=detail&v=uploaded.png'
			}
		});
		expect(upload.querySelector<HTMLImageElement>('.playlist-cover-image')?.src).toContain(
			'/shared/playlist/mix/cover?variant=card&v=uploaded.png'
		);

		if (mounted) await unmount(mounted);
		mounted = undefined;
		upload.remove();

		const mosaic = await renderShare({
			kind: 'playlist',
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

		const fallback = await renderShare({ kind: 'playlist' });
		expect(fallback.querySelectorAll('.playlist-cover-cell')).toHaveLength(4);
		expect(fallback.querySelectorAll('.playlist-cover-cell img')).toHaveLength(0);
		expect(fallback.querySelectorAll('.playlist-cover-initials')).toHaveLength(4);
	});
});

describe('SharedCollection track rows', () => {
	it('marks the row that plays, and only that row', async () => {
		// The transport a playing row brings up asks the media query for its visualizer.
		stubLayout(false);
		const target = await renderShare({
			kind: 'playlist',
			tracks: [sharedTrack('e1', 'Tide'), sharedTrack('e2', 'Ebb')]
		});
		const rows = Array.from(target.querySelectorAll<HTMLButtonElement>('.track-row'));

		rows[1].click();
		await tick();
		audioPlayer.status = 'playing';
		await tick();

		expect(
			rows.map((row) => findElementByRoleAndName(row, 'img', PLAYING_MARK_LABEL) !== null)
		).toEqual([false, true]);
	});

	it('shows the header the glyph it acts on: pause while the share plays, play once paused', async () => {
		stubLayout(false);
		const target = await renderShare({ kind: 'playlist', tracks: [sharedTrack('e1', 'Tide')] });
		target.querySelector<HTMLButtonElement>('.track-row')?.click();
		await tick();
		const header = target.querySelector('.collection-header');
		if (!header) throw new Error('Expected the collection header');

		audioPlayer.status = 'playing';
		await tick();
		expect(
			getByRoleButton(header, collectionActionLabel(TRANSPORT_PAUSE_LABEL, 'playlist'))
		).not.toBeNull();

		audioPlayer.status = 'paused';
		await tick();
		expect(
			getByRoleButton(header, collectionActionLabel(TRANSPORT_PLAY_LABEL, 'playlist'))
		).not.toBeNull();
		expect(findElementByRoleAndName(target, 'img', PLAYING_MARK_LABEL)).not.toBeNull();
	});

	it('offers Pause in the header while a stalled take recovers, and a press pauses', async () => {
		stubLayout(false);
		const target = await renderShare({ kind: 'playlist', tracks: [sharedTrack('e1', 'Tide')] });
		target.querySelector<HTMLButtonElement>('.track-row')?.click();
		await tick();
		const header = target.querySelector('.collection-header');
		if (!header) throw new Error('Expected the collection header');

		audioPlayer.status = 'buffering';
		await tick();
		getByRoleButton(header, collectionActionLabel(TRANSPORT_PAUSE_LABEL, 'playlist')).click();
		await tick();

		expect(
			getByRoleButton(header, collectionActionLabel(TRANSPORT_PLAY_LABEL, 'playlist'))
		).not.toBeNull();
	});

	it.each([
		{ status: 'playing', busy: 'false', face: 'pause' },
		{ status: 'buffering', busy: 'true', face: 'spinner' },
		{ status: 'error', busy: 'false', face: 'refresh-cw' }
	] as const)(
		'shows on the header circle of a $status share take the face the bar shows (#1330)',
		async ({ status, busy, face }) => {
			stubLayout(false);
			const target = await renderShare({ kind: 'playlist', tracks: [sharedTrack('e1', 'Tide')] });
			target.querySelector<HTMLButtonElement>('.track-row')?.click();
			await tick();

			audioPlayer.status = status;
			await tick();
			const circle = target.querySelector('.collection-header .play-circle');

			expect({ busy: circle?.getAttribute('aria-busy'), face: shownTransportFace(circle) }).toEqual(
				{
					busy,
					face
				}
			);
		}
	);

	it('dims the header play circle of a share without audio', async () => {
		const target = await renderShare();

		expect(
			getByRoleButton(target, collectionActionLabel(TRANSPORT_PLAY_LABEL, 'album')).disabled
		).toBe(true);
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
			expect(buttonNames(document.body)).toEqual([
				TRANSPORT_PLAY_LABEL,
				...LEGAL_SECTIONS.map((section) => section.label)
			]);
			expect(
				Array.from(document.querySelectorAll('a')).map((link) => link.getAttribute('href'))
			).toEqual(['/']);
			expect(target.querySelectorAll('.track-row')).toHaveLength(0);
			expect(document.querySelector('.player-bar')).toBeNull();
			expect(document.querySelector('[role="dialog"]')).toBeNull();
		}
	);

	it.each(['song', 'take'] as const)(
		'dims Play on a shared %s without audio and says why',
		async (kind) => {
			stubLayout(true);
			const target = await renderSharedSong(kind, { audioUrl: null });

			expect(getByRoleButton(target, TRANSPORT_PLAY_LABEL).disabled).toBe(true);
			expect(target.querySelector('[role="status"]')?.textContent).toBe(SHARE_NO_AUDIO_NOTICE);
		}
	);
});
