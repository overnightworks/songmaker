import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';

import PlaylistCover from './PlaylistCover.svelte';

let mounted: ReturnType<typeof mount> | undefined;

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

async function render(coverCount: number): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(PlaylistCover, {
		target,
		props: {
			title: 'Night Drive',
			covers: Array.from({ length: coverCount }, (_, index) => ({
				card: `/covers/${index}.jpg`,
				detail: `/covers/${index}-detail.jpg`
			}))
		}
	});
	await tick();
	return target;
}

describe('PlaylistCover', () => {
	it('uses a playlist cover instead of its album mosaic', async () => {
		const target = document.createElement('div');
		document.body.append(target);
		mounted = mount(PlaylistCover, {
			target,
			props: {
				title: 'Night Drive',
				covers: [{ card: '/covers/album.jpg', detail: '/covers/album-detail.jpg' }],
				cover: { card: '/covers/playlist.jpg', detail: '/covers/playlist-detail.jpg' }
			}
		});
		await tick();

		expect(target.querySelector('.playlist-cover-image')?.getAttribute('src')).toBe(
			'/covers/playlist.jpg'
		);
		expect(target.querySelectorAll('.playlist-cover-cell')).toHaveLength(0);
	});

	it.each([
		{ coverCount: 4, expectedImages: 4, expectedInitials: 0 },
		{ coverCount: 2, expectedImages: 2, expectedInitials: 2 },
		{ coverCount: 1, expectedImages: 1, expectedInitials: 3 },
		{ coverCount: 0, expectedImages: 0, expectedInitials: 4 }
	])(
		'renders $coverCount covers and fills the remaining cells with initials',
		async ({ coverCount, expectedImages, expectedInitials }) => {
			const target = await render(coverCount);
			const covers = Array.from(target.querySelectorAll('img'));

			expect(target.querySelectorAll('.playlist-cover-cell')).toHaveLength(4);
			expect(covers).toHaveLength(expectedImages);
			expect(
				covers.every(
					(cover) =>
						cover.getAttribute('loading') === 'lazy' && cover.getAttribute('decoding') === 'async'
				)
			).toBe(true);
			expect(target.querySelectorAll('.playlist-cover-initials')).toHaveLength(expectedInitials);
			expect(
				Array.from(target.querySelectorAll('.playlist-cover-initials')).map(
					(cell) => cell.textContent
				)
			).toEqual(Array(expectedInitials).fill('ND'));
		}
	);
});
