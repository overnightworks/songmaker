import { createRawSnippet, mount, tick, unmount, type ComponentProps } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/stores/toast', () => ({ addToast: vi.fn() }));

import { get } from 'svelte/store';
import {
	COLLECTION_MENU_LABEL,
	collectionActionLabel,
	TRANSPORT_PLAY_LABEL,
	TRANSPORT_PAUSE_LABEL
} from '$lib/constants';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import { reportResourceStreamReachable, resetConnectivityForTests } from '$lib/stores/connectivity';
import { albumList, songList } from '$lib/stores/libraryData';
import {
	queueContext,
	setShuffle,
	shuffleEnabled,
	playAlbum,
	playStartNotice,
	pendingStart,
	toggleOrStartCollection
} from '$lib/stores/player';
import { menuRow, menuRowLabels } from '$lib/test-utils/collection-menu';
import { makeAlbum, makeGeneration, makeSong } from '$lib/test-utils/factories';
import { clearComponentStyles, injectComponentStyles } from '$lib/test-utils/component-styles';
import CollectionHeader from './CollectionHeader.svelte';
import collectionHeaderFrameSource from './CollectionHeaderFrame.svelte?raw';
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
		songCount: 5,
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
	const waiting = get(pendingStart);
	if (waiting) toggleOrStartCollection('album', waiting.albumId, null);
	resetConnectivityForTests();
	songList.set([]);
	setShuffle(false);
	queueContext.set({ type: 'library' });
	albumList.set([]);
	audioPlayer.current = null;
	audioPlayer.status = 'idle';
	vi.restoreAllMocks();
	vi.unstubAllGlobals();
	clearComponentStyles();
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
	// jsdom gives the player no media element, so the circle's press, the
	// transport's own toggle, moves the status the way a real element does.
	vi.spyOn(audioPlayer, 'toggle').mockImplementation(() => {
		audioPlayer.status = audioPlayer.status === 'playing' ? 'paused' : 'playing';
	});
}

describe('CollectionHeader', () => {
	it.each(['album', 'playlist'] as const)(
		'reads the %s title and its song count under it, where the breadcrumb stood',
		async (kind) => {
			const target = await render({ ...baseProps(), kind });
			const titles = requireElement(target, '.header-titles');

			expect(titles.querySelector('.header-title')?.textContent).toContain('Night Drive');
			expect(requireElement(titles, '.header-count').textContent).toBe('5 songs');
		}
	);

	it('fills the play circle with the action colour', async () => {
		const target = await render(baseProps());
		const circle = requireElement<HTMLElement>(target, '.play-circle');
		injectComponentStyles(collectionHeaderFrameSource, 'CollectionHeaderFrame.svelte', circle);

		expect(getComputedStyle(circle).background).toBe('var(--accent)');
	});

	it.each(['album', 'playlist'] as const)(
		'starts the %s in order from its play circle',
		async (kind) => {
			setShuffle(true);
			const props = { ...baseProps(), kind };
			const target = await render(props);

			getByRoleButton(target, collectionActionLabel(TRANSPORT_PLAY_LABEL, kind)).click();

			expect(props.onplay).toHaveBeenCalledOnce();
			expect(get(shuffleEnabled)).toBe(false);
		}
	);

	it.each(['album', 'playlist'] as const)(
		'pauses the %s from its circle while it plays and resumes it on the next tap',
		async (kind) => {
			setShuffle(true);
			const props = { ...baseProps(), kind };
			queuePlays(kind, props.collectionId, 'playing');
			const target = await render(props);

			getByRoleButton(target, collectionActionLabel(TRANSPORT_PAUSE_LABEL, kind)).click();
			await tick();

			expect(audioPlayer.status).toBe('paused');
			getByRoleButton(target, collectionActionLabel(TRANSPORT_PLAY_LABEL, kind)).click();
			await tick();

			expect(audioPlayer.status).toBe('playing');
			expect(
				getByRoleButton(target, collectionActionLabel(TRANSPORT_PAUSE_LABEL, kind))
			).not.toBeNull();
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

			getByRoleButton(target, collectionActionLabel(TRANSPORT_PLAY_LABEL, kind)).click();

			expect(props.onplay).toHaveBeenCalledOnce();
			expect(audioPlayer.status).toBe('playing');
		}
	);

	it.each(['album', 'playlist'] as const)(
		'still pauses the %s from its circle once it empties while playing',
		async (kind) => {
			const props = { ...baseProps(), kind, onplay: null };
			queuePlays(kind, props.collectionId, 'playing');
			const target = await render(props);

			getByRoleButton(target, collectionActionLabel(TRANSPORT_PAUSE_LABEL, kind)).click();
			await tick();

			expect(audioPlayer.status).toBe('paused');
		}
	);

	it.each(['album', 'playlist'] as const)(
		'dims the circle while the %s has nothing to start, and a tap changes nothing',
		async (kind) => {
			setShuffle(true);
			const target = await render({ ...baseProps(), kind, onplay: null });
			const circle = getByRoleButton(target, collectionActionLabel(TRANSPORT_PLAY_LABEL, kind));

			circle.click();

			expect(circle.disabled).toBe(true);
			expect(get(shuffleEnabled)).toBe(true);
		}
	);

	it('offers no word Play button, only the play circle', async () => {
		const target = await render(baseProps());
		const actions = requireElement(target, '.header-actions');

		expect(actions.textContent).not.toMatch(/play/i);
		expect(requireElement(actions, '.play-circle').getAttribute('aria-label')).toBe('Play album');
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

	it.each(['album', 'playlist'] as const)(
		'puts Play and ⋯ of the %s on their own row under cover and title',
		async (kind) => {
			const target = await render({ ...baseProps(), kind });
			const identity = requireElement(target, '.header-identity');
			const actionRow = requireElement(target, '.header-actions');

			expect(identity.querySelector('.header-cover')).not.toBeNull();
			expect(identity.querySelector('.header-title')).not.toBeNull();
			expect(identity.contains(actionRow)).toBe(false);
			expect(identity.compareDocumentPosition(actionRow)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
			const actions = Array.from(actionRow.querySelectorAll('.play-circle, .collection-menu')).map(
				(element) => element.className.split(' ')[0]
			);
			expect(actions).toEqual(['play-circle', 'collection-menu']);
		}
	);

	it('renders only play and the … menu, no separate visible share icon', async () => {
		const target = await render(baseProps());
		expect(target.querySelector('.play-circle')).not.toBeNull();
		expect(target.querySelector('.collection-menu')).not.toBeNull();
		expect(target.querySelector('.share-btn')).toBeNull();
	});

	it('915_C3: names the object first in the menu and lists the album rows in their order', async () => {
		const target = await render({
			...detailsEditingAlbum(),
			coverEditor: fakeCoverEditor(),
			oncurate: vi.fn(),
			onarchive: vi.fn()
		});
		const menu = await openCollectionMenu(target);
		expect(menu.querySelector('.menu-heading')?.textContent).toBe('Album · Night Drive');
		expect(menuRowLabels(menu)).toEqual([
			'Edit details',
			'Cover',
			'Curate',
			'Add to playlist',
			'Share',
			'Archive',
			'Delete'
		]);
	});

	it('adds Remove cover to a playlist once a cover exists and wires it to onremovecover', async () => {
		const props = { ...baseProps(), kind: 'playlist' as const, coverUrl: 'https://x/cover.jpg' };
		const target = await render(props);
		const menu = await openCollectionMenu(target);
		expect(menuRowLabels(menu)).toEqual([
			'Share playlist',
			'Upload…',
			'Remove cover',
			'Rename',
			'Delete playlist'
		]);
		menuRow(menu, 'Remove cover').click();
		expect(props.onremovecover).toHaveBeenCalledTimes(1);
	});

	it.each([
		{
			state: 'a running suggestion',
			coverMark: { running: true, startedAt: '2026-10-22T10:00:00Z', waiting: 0 },
			name: 'Edit cover · making a suggestion'
		},
		{
			state: 'waiting suggestions',
			coverMark: { running: false, startedAt: null, waiting: 2 },
			name: 'Edit cover · 2 waiting'
		}
	])('carries $state on the closed cover, named without the ticking time', async (arrange) => {
		const target = await render({
			...baseProps(),
			coverUrl: 'https://x/cover.jpg',
			coverEditor: fakeCoverEditor(),
			coverMark: arrange.coverMark
		});

		const cover = getByRoleButton(target, arrange.name);
		expect(cover.querySelector('.cover-mark')).not.toBeNull();

		cover.click();
		await tick();

		expect(target.querySelector('.cover-mark')).toBeNull();
	});

	it('keeps the empty cover place reading Add cover while its name carries the mark', async () => {
		const target = await render({
			...baseProps(),
			coverEditor: fakeCoverEditor(),
			coverMark: { running: false, startedAt: null, waiting: 2 }
		});

		const place = requireElement(target, '.header-cover-add');

		expect(place.textContent).toBe('Add cover');
		expect(getByRoleButton(target, 'Add cover · 2 waiting')).not.toBeNull();
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

	it.each([{ coverUrl: null }, { coverUrl: 'https://x/cover.jpg' }])(
		'opens cover editing from Cover in the menu (cover $coverUrl)',
		async ({ coverUrl }) => {
			const target = await render({ ...baseProps(), coverUrl, coverEditor: fakeCoverEditor() });
			const menu = await openCollectionMenu(target);

			Array.from(menu.querySelectorAll<HTMLButtonElement>('.menu-item'))
				.find((el) => el.textContent?.trim().startsWith('Cover'))
				?.click();
			await tick();

			expect(target.querySelector('.fake-cover-editor')).not.toBeNull();
		}
	);

	it('lists playlist cover actions alongside its existing actions', async () => {
		const props = { ...baseProps(), kind: 'playlist' as const, onsaveoffline: vi.fn() };
		const target = await render(props);
		const menu = await openCollectionMenu(target);
		expect(menuRowLabels(menu)).toEqual([
			'Share playlist',
			'Upload…',
			'Save offline',
			'Rename',
			'Delete playlist'
		]);
	});

	it('shares from the Share row and copies the link, without duplicating the logic', async () => {
		const props = baseProps();
		const target = await render(props);
		const menu = await openCollectionMenu(target);
		menuRow(menu, 'Share').click();
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

	it('keeps its action row to Play and the menu: a new song is made from the track list', async () => {
		const target = await render(baseProps());

		const actions = [...requireElement(target, '.header-actions').querySelectorAll('button')];
		expect(actions.map((button) => button.getAttribute('aria-label'))).toEqual([
			collectionActionLabel(TRANSPORT_PLAY_LABEL, 'album'),
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

	it('reads the meta line under the title, above the song count', async () => {
		const target = await render({ ...baseProps(), meta: 'Live at the Roxy · 1994' });
		const titles = requireElement(target, '.header-titles');
		const meta = requireElement(titles, '.header-meta');
		expect(meta.textContent).toBe('Live at the Roxy · 1994');
		expect(
			requireElement(titles, 'h2').compareDocumentPosition(meta) & Node.DOCUMENT_POSITION_FOLLOWING
		).toBeTruthy();
		expect(
			meta.compareDocumentPosition(requireElement(titles, '.header-count')) &
				Node.DOCUMENT_POSITION_FOLLOWING
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
		expect(menuRowLabels(menu)).toEqual(['Edit details', 'Add to playlist', 'Share', 'Delete']);

		menuRow(menu, 'Edit details').click();
		await tick();

		const titles = requireElement(target, '.header-titles');
		expect(titles.querySelector('.fake-details-editor')).not.toBeNull();
		expect(titles.querySelector('h2')).toBeNull();
		expect(titles.querySelector('.header-count')).not.toBeNull();

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

	it('forwards Rename in the playlist menu to the title EditableTitle interaction', async () => {
		const target = await render({ ...baseProps(), kind: 'playlist' as const });
		const menu = await openCollectionMenu(target);
		const renameItem = Array.from(menu.querySelectorAll<HTMLButtonElement>('.menu-item')).find(
			(el) => el.textContent?.trim() === 'Rename'
		);
		renameItem?.click();
		await tick();
		expect(target.querySelector('.editable-title-input')).not.toBeNull();
	});

	it.each(['awaiting-network', 'gave-up-on-network'] as const)(
		'defect:#1330: the header withdraws its %s start even when it has nothing new to play',
		async (notice) => {
			const props = { ...baseProps(), onplay: null };
			albumList.set([makeAlbum({ id: props.collectionId })]);
			songList.set([
				makeSong({
					id: 'waiting-song',
					album_id: props.collectionId,
					generations: [],
					generation_count: 1
				})
			]);
			reportResourceStreamReachable(false);
			vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
			await playAlbum(props.collectionId);
			playStartNotice.set(notice);
			const root = await render(props);
			const pause = getByRoleButton(root, collectionActionLabel(TRANSPORT_PAUSE_LABEL, props.kind));
			expect(pause).toBeEnabled();
			pause.click();
			await tick();
			expect(get(pendingStart)).toBeNull();
			expect(get(playStartNotice)).toBe('idle');
			expect(
				getByRoleButton(root, collectionActionLabel(TRANSPORT_PLAY_LABEL, props.kind))
			).toBeDisabled();
		}
	);
});
