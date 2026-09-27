import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PLAYING_MARK_LABEL, collectionPauseLabel, collectionPlayLabel } from '$lib/constants';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import type { SharedTrack } from '$lib/share/sharedCollection';
import { getByRoleButton } from '$lib/test-utils/accessible-name';
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

async function renderShare(
	cover: { card: string; detail: string } | null,
	playlistCovers: { card: string; detail: string }[] = [],
	kind: 'song' | 'playlist' = 'song',
	tracks: SharedTrack[] = []
): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(SharedCollection, {
		target,
		props: {
			loading: false,
			errorKind: null,
			resource: 'album',
			view: {
				kind,
				title: 'Open Windows',
				artist: 'Felix',
				albumTitle: 'Open Windows',
				year: null,
				cover,
				playlistCovers,
				tracks
			},
			fetchStream: null
		}
	});
	await tick();
	return target;
}

describe('SharedCollection page root', () => {
	it('is its own scroll container, filling the viewport height html/body clip to', () => {
		const rule = extractRule(sharedCollectionSource, '.shared-page');
		expect(rule).toContain('height: 100dvh');
		expect(rule).toContain('overflow-y: auto');
	});

	it('shows an album cover on a shared song and falls back cleanly without one', async () => {
		const withCover = await renderShare({ card: '/covers/card.jpg', detail: '/covers/detail.jpg' });
		const image = withCover.querySelector<HTMLImageElement>('.header-cover img');
		expect(image?.src).toContain('/covers/detail.jpg');
		expect(image?.alt).toBe('Album Open Windows');

		if (mounted) await unmount(mounted);
		mounted = undefined;
		withCover.remove();

		const withoutCover = await renderShare(null);
		expect(withoutCover.querySelector('.header-cover img')).toBeNull();
		expect(withoutCover.querySelector('.header-cover-initials')?.textContent).toBe('OW');
	});

	it('shows a shared playlist upload, mosaic, and fallback through the shared cover tile', async () => {
		const upload = await renderShare(
			{
				card: '/shared/playlist/mix/cover?variant=card&v=uploaded.png',
				detail: '/shared/playlist/mix/cover?variant=detail&v=uploaded.png'
			},
			[],
			'playlist'
		);
		expect(upload.querySelector<HTMLImageElement>('.playlist-cover-image')?.src).toContain(
			'/shared/playlist/mix/cover?variant=card&v=uploaded.png'
		);

		if (mounted) await unmount(mounted);
		mounted = undefined;
		upload.remove();

		const mosaic = await renderShare(
			null,
			[
				{
					card: '/shared/playlist/mix/album-cover/a1?variant=card&v=album.png',
					detail: '/shared/playlist/mix/album-cover/a1?variant=detail&v=album.png'
				}
			],
			'playlist'
		);
		expect(mosaic.querySelectorAll('.playlist-cover-cell')).toHaveLength(4);
		expect(mosaic.querySelector<HTMLImageElement>('.playlist-cover-cell img')?.src).toContain(
			'/shared/playlist/mix/album-cover/a1?variant=card&v=album.png'
		);

		if (mounted) await unmount(mounted);
		mounted = undefined;
		mosaic.remove();

		const fallback = await renderShare(null, [], 'playlist');
		expect(fallback.querySelectorAll('.playlist-cover-cell')).toHaveLength(4);
		expect(fallback.querySelectorAll('.playlist-cover-cell img')).toHaveLength(0);
		expect(fallback.querySelectorAll('.playlist-cover-initials')).toHaveLength(4);
	});
});

describe('SharedCollection track rows', () => {
	function sharedTrack(key: string, title: string): SharedTrack {
		return {
			key,
			title,
			subtitle: null,
			audioUrl: `/shared/playlist/mix/audio/${key}.mp3`,
			durationSec: 120,
			lyrics: null,
			cues: null
		};
	}

	it('marks the row that plays, and only that row', async () => {
		// The transport a playing row brings up asks the media query for its visualizer.
		vi.stubGlobal(
			'matchMedia',
			vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
		);
		const target = await renderShare(null, [], 'playlist', [
			sharedTrack('e1', 'Tide'),
			sharedTrack('e2', 'Ebb')
		]);
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
		vi.stubGlobal(
			'matchMedia',
			vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
		);
		const target = await renderShare(null, [], 'playlist', [sharedTrack('e1', 'Tide')]);
		target.querySelector<HTMLButtonElement>('.track-row')?.click();
		await tick();
		const header = target.querySelector('.collection-header');
		if (!header) throw new Error('Expected the collection header');

		audioPlayer.status = 'playing';
		await tick();
		expect(getByRoleButton(header, collectionPauseLabel('playlist'))).not.toBeNull();

		audioPlayer.status = 'paused';
		await tick();
		expect(getByRoleButton(header, collectionPlayLabel('playlist'))).not.toBeNull();
		expect(findElementByRoleAndName(target, 'img', PLAYING_MARK_LABEL)).not.toBeNull();
	});

	it('dims the header play circle of a share without audio', async () => {
		const target = await renderShare(null);

		expect(getByRoleButton(target, collectionPlayLabel('song')).disabled).toBe(true);
	});
});
