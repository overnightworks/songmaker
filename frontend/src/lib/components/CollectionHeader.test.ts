import { createRawSnippet, mount, tick, unmount, type ComponentProps } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/stores/toast', () => ({ addToast: vi.fn() }));
vi.mock('$lib/stores/navigation', () => ({ openLibraryWall: vi.fn() }));

import { ALBUM_ADD_SONG_LABEL } from '$lib/constants';
import { openLibraryWall } from '$lib/stores/navigation';
import CollectionHeader from './CollectionHeader.svelte';
import { getByRoleButton, getByRoleHeading } from '$lib/test-utils/accessible-name';

let mounted: ReturnType<typeof mount> | undefined;

function requireElement<T extends Element>(root: ParentNode, selector: string): T {
	const element = root.querySelector<T>(selector);
	if (!element) throw new Error(`Expected ${selector} to be rendered`);
	return element;
}

type CollectionHeaderProps = ComponentProps<typeof CollectionHeader>;

function baseProps(): CollectionHeaderProps {
	return {
		kind: 'album',
		title: 'Night Drive',
		coverUrl: null,
		coverAlt: 'Album Night Drive',
		initials: 'ND',
		artFill: null,
		onplay: vi.fn(),
		onrename: vi.fn().mockResolvedValue(undefined),
		isShared: false,
		shareSlug: null,
		onshare: vi.fn().mockResolvedValue({
			status: 'ok',
			share_url: 'https://x/y',
			share_slug: 'y',
			songs_without_playable_take: []
		}),
		onunshare: vi.fn().mockResolvedValue(undefined),
		ondelete: vi.fn(),
		oncover: vi.fn(),
		onremovecover: vi.fn(),
		onaddtoplaylist: vi.fn()
	};
}

async function render(props: CollectionHeaderProps): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(CollectionHeader, { target, props });
	await tick();
	return target;
}

async function openMenu(target: HTMLElement): Promise<HTMLElement> {
	requireElement<HTMLButtonElement>(target, '.collection-menu [aria-haspopup="dialog"]').click();
	await tick();
	return requireElement<HTMLElement>(document.body, '.menu-panel');
}

beforeEach(() => {
	Object.defineProperty(navigator, 'clipboard', {
		configurable: true,
		value: { writeText: vi.fn().mockResolvedValue(undefined) }
	});
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

describe('CollectionHeader', () => {
	it('shows cover, title, a Library › title breadcrumb, and calls onplay from the Play button', async () => {
		const props = baseProps();
		const target = await render(props);
		expect(target.querySelector('.header-title')?.textContent).toContain('Night Drive');
		const crumbs = Array.from(target.querySelectorAll('.crumb')).map((el) => el.textContent);
		expect(crumbs).toEqual(['Library', 'Night Drive']);
		requireElement<HTMLButtonElement>(target, '.play-btn').click();
		expect(props.onplay).toHaveBeenCalledTimes(1);
	});

	it('shows a Playlists › title breadcrumb for a playlist', async () => {
		const target = await render({ ...baseProps(), kind: 'playlist' as const });
		const crumbs = Array.from(target.querySelectorAll('.crumb')).map(
			(element) => element.textContent
		);

		expect(crumbs).toEqual(['Playlists', 'Night Drive']);
	});

	it('uses the album art fill when an album has no cover', async () => {
		const target = await render({ ...baseProps(), artFill: 'rgb(12, 34, 56)' });
		const fallback = requireElement<HTMLElement>(target, '.header-cover-fallback');

		expect(fallback.style.background).toBe('rgb(12, 34, 56)');
	});

	it('uses album initials when an album has neither cover nor art fill', async () => {
		const target = await render(baseProps());
		const fallback = requireElement<HTMLElement>(target, '.header-cover-initials');

		expect(fallback.textContent).toBe('ND');
	});

	it('uses the playlist mosaic when a playlist has no own cover', async () => {
		const target = await render({
			...baseProps(),
			kind: 'playlist' as const,
			playlistCovers: []
		});

		expect(target.querySelectorAll('.header-cover .playlist-cover-cell')).toHaveLength(4);
	});

	it('opens the Library wall from the breadcrumb', async () => {
		const target = await render(baseProps());
		requireElement<HTMLButtonElement>(target, '.crumb-link').click();
		expect(openLibraryWall).toHaveBeenCalledTimes(1);
	});

	it('renders only Play and the … menu, no separate visible share icon', async () => {
		const target = await render(baseProps());
		expect(target.querySelector('.play-btn')).not.toBeNull();
		expect(target.querySelector('.collection-menu')).not.toBeNull();
		expect(target.querySelector('.share-btn')).toBeNull();
	});

	it('names the object first in the menu and lists album entries in order, without Remove cover when there is no cover', async () => {
		const target = await render(baseProps());
		const menu = await openMenu(target);
		expect(menu.querySelector('.menu-heading')?.textContent).toBe('Album · Night Drive');
		const items = Array.from(menu.querySelectorAll('.menu-item')).map((el) =>
			el.textContent?.trim()
		);
		expect(items).toEqual(['Upload…', 'Rename', 'Add to playlist', 'Delete album']);
	});

	it('adds Remove cover once a cover exists and wires it to onremovecover', async () => {
		const props = { ...baseProps(), coverUrl: 'https://x/cover.jpg' };
		const target = await render(props);
		const menu = await openMenu(target);
		const items = Array.from(menu.querySelectorAll('.menu-item')).map((el) =>
			el.textContent?.trim()
		);
		expect(items).toEqual(['Upload…', 'Remove cover', 'Rename', 'Add to playlist', 'Delete album']);
		const removeItem = Array.from(menu.querySelectorAll<HTMLButtonElement>('.menu-item')).find(
			(el) => el.textContent?.trim() === 'Remove cover'
		);
		removeItem?.click();
		expect(props.onremovecover).toHaveBeenCalledTimes(1);
	});

	it('lists playlist cover actions alongside its existing actions', async () => {
		const props = { ...baseProps(), kind: 'playlist' as const, onsaveoffline: vi.fn() };
		const target = await render(props);
		const menu = await openMenu(target);
		expect(menu.querySelector('.menu-row-label')?.textContent).toBe('Share playlist');
		const items = Array.from(menu.querySelectorAll('.menu-item')).map((el) =>
			el.textContent?.trim()
		);
		expect(items).toEqual(['Upload…', 'Save offline', 'Rename', 'Delete playlist']);
	});

	it('shares via the embedded ShareButton and copies the link, without duplicating the logic', async () => {
		const props = baseProps();
		const target = await render(props);
		const menu = await openMenu(target);
		requireElement<HTMLButtonElement>(menu, '.share-btn').click();
		await vi.waitFor(() => expect(props.onshare).toHaveBeenCalledTimes(1));
		await vi.waitFor(() =>
			expect(navigator.clipboard.writeText).toHaveBeenCalledWith('https://x/y')
		);
	});

	it('calls ondelete for the destructive entry and closes the menu', async () => {
		const props = baseProps();
		const target = await render(props);
		const menu = await openMenu(target);
		requireElement<HTMLButtonElement>(menu, '.menu-item.destructive').click();
		await tick();
		expect(props.ondelete).toHaveBeenCalledTimes(1);
		expect(document.body.querySelector('.menu-panel')).toBeNull();
	});

	it('offers Add song next to the collection menu only when the surface can create one', async () => {
		// #141/6: the rail is navigation — creating a song is a header action.
		const withoutCreate = await render(baseProps());
		expect(withoutCreate.querySelector('.add-song-btn')).toBeNull();
		if (mounted) await unmount(mounted);

		const onaddsong = vi.fn();
		const target = await render({ ...baseProps(), onaddsong });
		const addSong = requireElement<HTMLButtonElement>(target, '.add-song-btn');
		expect(addSong.getAttribute('aria-label')).toBe(ALBUM_ADD_SONG_LABEL);
		expect(requireElement(addSong, '.add-song-full').textContent?.trim()).toBe(
			ALBUM_ADD_SONG_LABEL
		);

		// Sizing itself is pinned once for the shared mechanism in
		// frequent-hitbox.test.ts; here the contract is that this control opts in.
		expect(addSong.dataset.hitbox).toBe('frequent');

		addSong.click();
		expect(onaddsong).toHaveBeenCalledTimes(1);
	});

	it('announces the album title as the heading name, with a separately named edit button', async () => {
		const target = await render(baseProps());
		const heading = getByRoleHeading(target, 'Night Drive');
		expect(heading.tagName).toBe('H2');
		const editButton = getByRoleButton(heading, 'Edit album title');
		expect(editButton.textContent?.trim()).toBe('Night Drive');
	});

	it('announces the playlist title as the heading name, with a separately named edit button', async () => {
		const target = await render({
			...baseProps(),
			kind: 'playlist' as const,
			title: 'Late Night Mix'
		});
		const heading = getByRoleHeading(target, 'Late Night Mix');
		expect(heading.tagName).toBe('H2');
		const editButton = getByRoleButton(heading, 'Edit playlist title');
		expect(editButton.textContent?.trim()).toBe('Late Night Mix');
	});

	it('renders the album-only metaEditor snippet under the title, above the breadcrumb', async () => {
		const metaEditor = createRawSnippet(() => ({
			render: () => `<p class="album-meta-stub">Live at the Roxy · 1994</p>`
		}));
		const target = await render({ ...baseProps(), metaEditor });
		const heading = getByRoleHeading(target, 'Night Drive');
		expect(heading.tagName).toBe('H2');
		const titles = requireElement(target, '.header-titles');
		const stub = requireElement(titles, '.album-meta-stub');
		expect(stub.textContent).toBe('Live at the Roxy · 1994');
		const breadcrumb = requireElement(titles, 'nav');
		expect(
			stub.compareDocumentPosition(breadcrumb) & Node.DOCUMENT_POSITION_FOLLOWING
		).toBeTruthy();
	});

	it('renders no metaEditor area when the caller passes none, as playlists do', async () => {
		const target = await render({ ...baseProps(), kind: 'playlist' as const });
		expect(target.querySelector('.album-meta-stub')).toBeNull();
	});

	it('forwards Rename in the menu to the title EditableTitle interaction', async () => {
		const target = await render(baseProps());
		const menu = await openMenu(target);
		const renameItem = Array.from(menu.querySelectorAll<HTMLButtonElement>('.menu-item')).find(
			(el) => el.textContent?.trim() === 'Rename'
		);
		renameItem?.click();
		await tick();
		expect(target.querySelector('.editable-title-input')).not.toBeNull();
	});
});
