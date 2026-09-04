import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';

import LibraryTileContent from './LibraryTileContent.svelte';

let mounted: ReturnType<typeof mount> | undefined;

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

async function render(coverUrl: string | null): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(LibraryTileContent, {
		target,
		props: {
			title: 'Open Windows',
			subtitle: '8 songs',
			coverAlt: 'Album Open Windows',
			coverUrl,
			fill: '#37154a'
		}
	});
	await tick();
	return target;
}

describe('LibraryTileContent', () => {
	it('renders the album cover in its fixed square with meaningful alternative text', async () => {
		const target = await render('/covers/open-windows.jpg');
		const cover = target.querySelector<HTMLImageElement>('.tile-cover img');

		expect(cover?.src).toContain('/covers/open-windows.jpg');
		expect(cover?.alt).toBe('Album Open Windows');
		expect(target.querySelector('.tile-cover')?.getAttribute('style')).toBeNull();
	});

	it('retains the color fallback when an album has no cover', async () => {
		const target = await render(null);

		expect(target.querySelector('.tile-cover img')).toBeNull();
		expect(target.querySelector('.tile-cover-fill')).not.toBeNull();
	});
});
