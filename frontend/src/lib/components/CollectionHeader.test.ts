import { createRawSnippet, mount, tick, unmount, type ComponentProps } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/stores/toast', () => ({ addToast: vi.fn() }));
vi.mock('$lib/stores/navigation', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/stores/navigation')>()),
	openLibraryWall: vi.fn()
}));

import { get } from 'svelte/store';
import {
	COLLECTION_MENU_LABEL,
	collectionPauseLabel,
	collectionPlayLabel,
	collectionShuffleLabel
} from '$lib/constants';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import { albumList } from '$lib/stores/libraryData';
import { openLibraryWall } from '$lib/stores/navigation';
import { queueContext, setShuffle, shuffleEnabled } from '$lib/stores/player';
import { makeAlbum, makeGeneration } from '$lib/test-utils/factories';
import CollectionHeader from './CollectionHeader.svelte';
import { openCollectionMenu } from './shell/rail-test-fixtures';
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
		collectionId: 'c-night-drive',
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

// A stand-in for the album's cover editor: its one button hands back the
// close the header passed in, so a test sees the header's side of the seam.
function fakeCoverEditor(): NonNullable<CollectionHeaderProps['coverEditor']> {
	return createRawSnippet((close: () => () => void) => ({
		render: () => '<div class="fake-cover-editor"><button type="button">Done</button></div>',
		setup: (element: Element) => {
			element.querySelector('button')?.addEventListener('click', () => close()());
		}
	}));
}

// The same seam for the album's details editor, which stands in for the title.
function fakeDetailsEditor(): NonNullable<CollectionHeaderProps['detailsEditor']> {
	return createRawSnippet((close: () => () => void) => ({
		render: () => '<div class="fake-details-editor"><button type="button">Done</button></div>',
		setup: (element: Element) => {
			element.querySelector('button')?.addEventListener('click', () => close()());
		}
	}));
}

function detailsEditingAlbum(): CollectionHeaderProps {
	return { ...baseProps(), onrename: undefined, detailsEditor: fakeDetailsEditor() };
}

async function render(props: CollectionHeaderProps): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(CollectionHeader, { target, props });
	await tick();
	return target;
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
	setShuffle(false);
	queueContext.set({ type: 'library' });
	albumList.set([]);
	audioPlayer.current = null;
	audioPlayer.status = 'idle';
	vi.restoreAllMocks();
	document.body.replaceChildren();
});

type HeaderKind = CollectionHeaderProps['kind'];

// The queue plays `collectionId` of `kind`, sounding or paused. jsdom gives the
// player no media element, so pause and play are stubbed to move the status
// the way a real element does and a click's effect reads as state.
function queuePlays(kind: HeaderKind, collectionId: string, status: 'playing' | 'paused'): void {
	if (kind === 'album') {
		albumList.set([makeAlbum({ id: collectionId, title: 'Queued' })]);
		queueContext.set({ type: 'album', albumId: collectionId });
	} else {
		queueContext.set({
			type: 'playlist',
			playlist: { id: collectionId, title: 'Queued' },
			entries: [],
			index: 0
		});
	}
	audioPlayer.current = {
		generation: makeGeneration(),
		songId: 's1',
		songTitle: 'Song',
		artist: 'Artist',
		albumTitle: 'Queued',
		lyrics: null
	};
	audioPlayer.status = status;
	vi.spyOn(audioPlayer, 'pause').mockImplementation(() => {
		audioPlayer.status = 'paused';
	});
	vi.spyOn(audioPlayer, 'play').mockImplementation(() => {
		audioPlayer.status = 'playing';
	});
}

describe('CollectionHeader', () => {
	it('shows cover, title and a Library › title breadcrumb', async () => {
		const target = await render(baseProps());
		expect(target.querySelector('.header-title')?.textContent).toContain('Night Drive');
		const crumbs = Array.from(target.querySelectorAll('.crumb')).map((el) => el.textContent);
		expect(crumbs).toEqual(['Library', 'Night Drive']);
	});

	it.each(['album', 'playlist'] as const)(
		'starts the %s in order from its play circle',
		async (kind) => {
			setShuffle(true);
			const props = { ...baseProps(), kind };
			const target = await render(props);

			getByRoleButton(target, collectionPlayLabel(kind)).click();

			expect(props.onplay).toHaveBeenCalledExactlyOnceWith('top');
			expect(get(shuffleEnabled)).toBe(false);
		}
	);

	it.each(['album', 'playlist'] as const)(
		'starts the %s shuffled from a drawn song from its shuffle square',
		async (kind) => {
			const props = { ...baseProps(), kind };
			const target = await render(props);

			getByRoleButton(target, collectionShuffleLabel(kind)).click();

			expect(props.onplay).toHaveBeenCalledExactlyOnceWith('random');
			expect(get(shuffleEnabled)).toBe(true);
		}
	);

	it.each(['album', 'playlist'] as const)(
		'pauses the %s from its circle while it plays and resumes it on the next tap',
		async (kind) => {
			setShuffle(true);
			const props = { ...baseProps(), kind };
			queuePlays(kind, props.collectionId, 'playing');
			const target = await render(props);

			getByRoleButton(target, collectionPauseLabel(kind)).click();
			await tick();

			expect(audioPlayer.status).toBe('paused');
			getByRoleButton(target, collectionPlayLabel(kind)).click();
			await tick();

			expect(audioPlayer.status).toBe('playing');
			expect(getByRoleButton(target, collectionPauseLabel(kind))).not.toBeNull();
			expect(props.onplay).not.toHaveBeenCalled();
			expect(get(shuffleEnabled)).toBe(true);
		}
	);

	it.each(['album', 'playlist'] as const)(
		'starts the %s from the top while another collection plays',
		async (kind) => {
			const props = { ...baseProps(), kind };
			queuePlays(kind, 'c-other', 'playing');
			const target = await render(props);

			getByRoleButton(target, collectionPlayLabel(kind)).click();

			expect(props.onplay).toHaveBeenCalledExactlyOnceWith('top');
			expect(audioPlayer.status).toBe('playing');
		}
	);

	it.each(['album', 'playlist'] as const)(
		'still pauses the %s from its circle once it empties while playing, with shuffle dimmed',
		async (kind) => {
			const props = { ...baseProps(), kind, onplay: null };
			queuePlays(kind, props.collectionId, 'playing');
			const target = await render(props);
			const shuffle = getByRoleButton(target, collectionShuffleLabel(kind));

			getByRoleButton(target, collectionPauseLabel(kind)).click();
			await tick();

			expect(audioPlayer.status).toBe('paused');
			expect(shuffle.disabled).toBe(true);
		}
	);

	it.each(['album', 'playlist'] as const)(
		'dims the circle and shuffle while the %s has nothing to start, and a tap changes nothing',
		async (kind) => {
			setShuffle(true);
			const target = await render({ ...baseProps(), kind, onplay: null });
			const circle = getByRoleButton(target, collectionPlayLabel(kind));
			const shuffle = getByRoleButton(target, collectionShuffleLabel(kind));

			circle.click();
			shuffle.click();

			expect([circle, shuffle].map((button) => button.disabled)).toEqual([true, true]);
			expect(get(shuffleEnabled)).toBe(true);
		}
	);

	it('offers no word Play button, only the play circle and the shuffle square', async () => {
		const target = await render(baseProps());
		const actions = requireElement(target, '.header-actions');

		expect(actions.textContent).not.toMatch(/play/i);
		expect(requireElement(actions, '.play-circle').getAttribute('aria-label')).toBe('Play album');
		expect(requireElement(actions, '.shuffle-btn').getAttribute('aria-label')).toBe(
			'Shuffle album'
		);
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

	it.each(['album', 'playlist'] as const)(
		'puts Play, Shuffle and ⋯ of the %s on their own row under cover and title',
		async (kind) => {
			const target = await render({ ...baseProps(), kind });
			const identity = requireElement(target, '.header-identity');
			const actionRow = requireElement(target, '.header-actions');

			expect(identity.querySelector('.header-cover')).not.toBeNull();
			expect(identity.querySelector('.header-title')).not.toBeNull();
			expect(identity.contains(actionRow)).toBe(false);
			expect(identity.compareDocumentPosition(actionRow)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
			const actions = Array.from(
				actionRow.querySelectorAll('.play-circle, .shuffle-btn, .collection-menu')
			).map((element) => element.className.split(' ')[0]);
			expect(actions).toEqual(['play-circle', 'shuffle-btn', 'collection-menu']);
		}
	);

	it('renders only play, shuffle and the … menu, no separate visible share icon', async () => {
		const target = await render(baseProps());
		expect(target.querySelector('.play-circle')).not.toBeNull();
		expect(target.querySelector('.shuffle-btn')).not.toBeNull();
		expect(target.querySelector('.collection-menu')).not.toBeNull();
		expect(target.querySelector('.share-btn')).toBeNull();
	});

	it('names the object first in the menu and lists album entries in order, without Remove cover when there is no cover', async () => {
		const target = await render(baseProps());
		const menu = await openCollectionMenu(target);
		expect(menu.querySelector('.menu-heading')?.textContent).toBe('Album · Night Drive');
		const items = Array.from(menu.querySelectorAll('.menu-item')).map((el) =>
			el.textContent?.trim()
		);
		expect(items).toEqual(['Upload…', 'Rename', 'Add to playlist', 'Delete album']);
	});

	it('adds Remove cover once a cover exists and wires it to onremovecover', async () => {
		const props = { ...baseProps(), coverUrl: 'https://x/cover.jpg' };
		const target = await render(props);
		const menu = await openCollectionMenu(target);
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

	it.each([
		{ coverUrl: null, place: 'Add cover' },
		{ coverUrl: 'https://x/cover.jpg', place: 'Edit cover' }
	])(
		'makes the album cover place, $place, open cover editing in place above Play',
		async ({ coverUrl, place }) => {
			const target = await render({ ...baseProps(), coverUrl, coverEditor: fakeCoverEditor() });

			getByRoleButton(target, place).click();
			await tick();

			const identity = requireElement(target, '.header-identity');
			expect(identity.querySelector('.fake-cover-editor')).not.toBeNull();
			expect(target.querySelector('button.header-cover')).toBeNull();
			expect(identity.querySelector('.header-title')).not.toBeNull();
			expect(target.querySelector('.play-circle')).not.toBeNull();

			getByRoleButton(target, 'Done').click();
			await tick();

			expect(target.querySelector('.fake-cover-editor')).toBeNull();
			expect(getByRoleButton(target, place)).not.toBeNull();
		}
	);

	it('keeps the cover a plain picture where no cover editor is given', async () => {
		const target = await render({ ...baseProps(), kind: 'playlist' as const });

		expect(target.querySelector('.header-cover')).not.toBeNull();
		expect(target.querySelector('button.header-cover')).toBeNull();
		expect(target.textContent).not.toContain('Add cover');
	});

	it('opens cover editing from Replace… in the menu once a cover exists', async () => {
		const target = await render({
			...baseProps(),
			coverUrl: 'https://x/cover.jpg',
			coverEditor: fakeCoverEditor()
		});
		const menu = await openCollectionMenu(target);
		const items = Array.from(menu.querySelectorAll<HTMLButtonElement>('.menu-item'));
		expect(items.map((el) => el.textContent?.trim())).toEqual([
			'Upload…',
			'Replace…',
			'Remove cover',
			'Rename',
			'Add to playlist',
			'Delete album'
		]);

		items.find((el) => el.textContent?.trim() === 'Replace…')?.click();
		await tick();

		expect(target.querySelector('.fake-cover-editor')).not.toBeNull();
	});

	it('lists playlist cover actions alongside its existing actions', async () => {
		const props = { ...baseProps(), kind: 'playlist' as const, onsaveoffline: vi.fn() };
		const target = await render(props);
		const menu = await openCollectionMenu(target);
		expect(menu.querySelector('.menu-row-label')?.textContent).toBe('Share playlist');
		const items = Array.from(menu.querySelectorAll('.menu-item')).map((el) =>
			el.textContent?.trim()
		);
		expect(items).toEqual(['Upload…', 'Save offline', 'Rename', 'Delete playlist']);
	});

	it('shares via the embedded ShareButton and copies the link, without duplicating the logic', async () => {
		const props = baseProps();
		const target = await render(props);
		const menu = await openCollectionMenu(target);
		requireElement<HTMLButtonElement>(menu, '.share-btn').click();
		await vi.waitFor(() => expect(props.onshare).toHaveBeenCalledTimes(1));
		await vi.waitFor(() =>
			expect(navigator.clipboard.writeText).toHaveBeenCalledWith('https://x/y')
		);
	});

	it('calls ondelete for the destructive entry and closes the menu', async () => {
		const props = baseProps();
		const target = await render(props);
		const menu = await openCollectionMenu(target);
		requireElement<HTMLButtonElement>(menu, '.menu-item.destructive').click();
		await tick();
		expect(props.ondelete).toHaveBeenCalledTimes(1);
		expect(document.body.querySelector('.menu-panel')).toBeNull();
	});

	it('keeps its action row to Play, Shuffle and the menu: a new song is made from the track list', async () => {
		const target = await render(baseProps());

		const actions = [...requireElement(target, '.header-actions').querySelectorAll('button')];
		expect(actions.map((button) => button.getAttribute('aria-label'))).toEqual([
			collectionPlayLabel('album'),
			collectionShuffleLabel('album'),
			COLLECTION_MENU_LABEL
		]);
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

	it('reads the meta line under the title, above the breadcrumb', async () => {
		const target = await render({ ...baseProps(), meta: 'Live at the Roxy · 1994' });
		const titles = requireElement(target, '.header-titles');
		const meta = requireElement(titles, '.header-meta');
		expect(meta.textContent).toBe('Live at the Roxy · 1994');
		expect(
			requireElement(titles, 'h2').compareDocumentPosition(meta) & Node.DOCUMENT_POSITION_FOLLOWING
		).toBeTruthy();
		expect(
			meta.compareDocumentPosition(requireElement(titles, 'nav')) & Node.DOCUMENT_POSITION_FOLLOWING
		).toBeTruthy();
	});

	it('shows no meta line and no Add subtitle · Add year line when there is no meta', async () => {
		const target = await render(baseProps());
		expect(target.querySelector('.header-meta')).toBeNull();
		expect(target.textContent).not.toContain('Add subtitle');
		expect(target.textContent).not.toContain('Add year');
	});

	it('opens the details editor in place of the title from Edit details, and its close ends it', async () => {
		const target = await render(detailsEditingAlbum());
		const menu = await openCollectionMenu(target);
		const items = Array.from(menu.querySelectorAll<HTMLButtonElement>('.menu-item'));
		expect(items.map((el) => el.textContent?.trim())).toEqual([
			'Upload…',
			'Edit details',
			'Add to playlist',
			'Delete album'
		]);

		items.find((el) => el.textContent?.trim() === 'Edit details')?.click();
		await tick();

		const titles = requireElement(target, '.header-titles');
		expect(titles.querySelector('.fake-details-editor')).not.toBeNull();
		expect(titles.querySelector('h2')).toBeNull();
		expect(titles.querySelector('nav')).not.toBeNull();

		getByRoleButton(target, 'Done').click();
		await tick();

		expect(target.querySelector('.fake-details-editor')).toBeNull();
		expect(getByRoleHeading(target, 'Night Drive')).not.toBeNull();
	});

	it('names an album title that renames only through Edit details as a plain heading', async () => {
		const target = await render(detailsEditingAlbum());
		const heading = getByRoleHeading(target, 'Night Drive');
		expect(heading.textContent?.trim()).toBe('Night Drive');
		expect(heading.querySelector('button')).toBeNull();
	});

	it('forwards Rename in the menu to the title EditableTitle interaction', async () => {
		const target = await render(baseProps());
		const menu = await openCollectionMenu(target);
		const renameItem = Array.from(menu.querySelectorAll<HTMLButtonElement>('.menu-item')).find(
			(el) => el.textContent?.trim() === 'Rename'
		);
		renameItem?.click();
		await tick();
		expect(target.querySelector('.editable-title-input')).not.toBeNull();
	});
});
