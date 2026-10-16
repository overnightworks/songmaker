import { createRawSnippet, mount, tick, unmount, type Snippet } from 'svelte';
import { fromStore, writable } from 'svelte/store';
import { afterEach, describe, expect, it } from 'vitest';
import { makeGeneration } from '$lib/test-utils/factories';
import NowPlayingFrame from './NowPlayingFrame.svelte';

let mounted: ReturnType<typeof mount> | undefined;

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

describe('NowPlayingFrame', () => {
	it('1374_rule_10 shows page artwork in the cover and restores the URL cover when absent', async () => {
		const artwork = writable<Snippet | undefined>(
			createRawSnippet(() => ({ render: () => '<span>Collection mosaic</span>' }))
		);
		const reactiveArtwork = fromStore(artwork);
		const target = document.createElement('div');
		document.body.append(target);
		mounted = mount(NowPlayingFrame, {
			target,
			props: {
				surface: 'page',
				info: {
					generation: makeGeneration(),
					songId: 'song-1',
					songTitle: 'Tide',
					albumTitle: 'Night Drive',
					artist: '',
					lyrics: null
				},
				coverUrl: '/cover.webp',
				get artwork() {
					return reactiveArtwork.current;
				}
			}
		});
		await tick();
		const cover = target.querySelector('.cover-art');
		expect(cover).toHaveTextContent('Collection mosaic');
		expect(cover?.querySelector('img')).toBeNull();
		artwork.set(undefined);
		await tick();
		expect(cover).not.toHaveTextContent('Collection mosaic');
		expect(cover?.querySelector('img')).toHaveAttribute('src', '/cover.webp');
	});
});
