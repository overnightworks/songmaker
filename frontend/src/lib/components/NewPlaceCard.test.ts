import { makeAlbum as album } from '$lib/test-utils/factories';
import type { Component } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest';

// Drafts live for the session, which is the module's life; every test starts
// a fresh session by loading the cards -- and the Svelte runtime and helpers
// that drive them -- anew.
const svelte = () => import('svelte');
const cardHelpers = () => import('$lib/test-utils/new-place-card');

const createAlbum = vi.fn();
const createSong = vi.fn();
const createNewPlaylist = vi.fn();

vi.mock('$lib/api/client', () => ({
	createAlbum: (...args: unknown[]) => createAlbum(...args),
	createSong: (...args: unknown[]) => createSong(...args)
}));
vi.mock('$lib/stores/playlists', () => ({
	createNewPlaylist: (...args: unknown[]) => createNewPlaylist(...args),
	resetPlaylists: vi.fn()
}));
vi.mock('$lib/stores/libraryData', () => ({ addAlbumToList: vi.fn(), addSongToList: vi.fn() }));
vi.mock('$lib/stores/navigation', () => ({
	openAlbum: vi.fn().mockResolvedValue(undefined),
	openPlaylist: vi.fn().mockResolvedValue(undefined),
	selectSong: vi.fn().mockResolvedValue(undefined)
}));
vi.mock('$lib/stores/toast', () => ({ addToast: vi.fn(), dismissToast: vi.fn() }));
vi.mock('$lib/stores/jobs', () => ({ resetGenerationFailures: vi.fn() }));
vi.mock('$lib/stores/libraryOrder', () => ({ resetLibraryOrder: vi.fn() }));

const NIGHTDRIVE = album({ id: 'a-night', title: 'Nightdrive' });
const TIDEWATER = album({ id: 'a-tide', title: 'Tidewater' });

interface CardCase {
	card: string;
	field: string;
	create: Mock;
	load: () => Promise<{ default: Component<never> }>;
	props: Record<string, unknown>;
}

const CARDS: CardCase[] = [
	{
		card: 'New album',
		field: 'Title',
		create: createAlbum,
		load: () => import('./NewAlbumCard.svelte'),
		props: {}
	},
	{
		card: 'New playlist',
		field: 'Name',
		create: createNewPlaylist,
		load: () => import('./NewPlaylistCard.svelte'),
		props: {}
	},
	{
		card: 'New song',
		field: 'Title',
		create: createSong,
		load: () => import('./NewSongCard.svelte'),
		props: { album: NIGHTDRIVE }
	}
];

let mounted: object | undefined;

beforeEach(() => {
	vi.resetModules();
	createAlbum.mockReset().mockResolvedValue(NIGHTDRIVE);
	createSong.mockReset().mockResolvedValue({ id: 's-new' });
	createNewPlaylist.mockReset().mockResolvedValue({ id: 'p-new' });
});

afterEach(async () => {
	await close();
	document.body.replaceChildren();
});

async function open(
	cardCase: CardCase,
	props: Record<string, unknown> = cardCase.props
): Promise<HTMLElement> {
	const { default: Card } = await cardCase.load();
	const { mount, tick } = await svelte();
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(Card as Component<Record<string, unknown>>, {
		target,
		props: { ...props, oncancel: () => undefined, oncreated: () => undefined }
	});
	await tick();
	return target;
}

async function close(): Promise<void> {
	const { unmount } = await svelte();
	if (mounted) await unmount(mounted);
	mounted = undefined;
}

describe.each(CARDS)('$card keeps its typed text as a draft (#1184 K2)', (cardCase) => {
	it('shows the text typed before it closed when it opens again', async () => {
		const { field, type } = await cardHelpers();
		type(field(await open(cardCase), cardCase.field), 'Night');
		await close();

		expect(field(await open(cardCase), cardCase.field).value).toBe('Night');
	});

	it('opens empty again once the draft has been created', async () => {
		const { createButton, createSettled, field, type } = await cardHelpers();
		const card = await open(cardCase);
		type(field(card, cardCase.field), 'Night');
		createButton(card).click();
		await createSettled(cardCase.create);
		await close();

		expect(field(await open(cardCase), cardCase.field).value).toBe('');
	});

	it('opens empty again once the field was cleared', async () => {
		const { field, type } = await cardHelpers();
		const card = await open(cardCase);
		type(field(card, cardCase.field), 'Night');
		type(field(card, cardCase.field), '');
		await close();

		expect(field(await open(cardCase), cardCase.field).value).toBe('');
	});

	it('opens empty for the next musician once the session ended without a reload', async () => {
		const { field, type } = await cardHelpers();
		type(field(await open(cardCase), cardCase.field), 'Night');
		await close();
		const { clearAuth } = await import('$lib/stores/auth');
		clearAuth();

		expect(field(await open(cardCase), cardCase.field).value).toBe('');
	});
});

describe('New song drafts', () => {
	it('keeps one draft per album, so another album opens its card empty', async () => {
		const { field, type } = await cardHelpers();
		const songCard = CARDS[2];
		type(field(await open(songCard), songCard.field), 'Night');
		await close();

		expect(field(await open(songCard, { album: TIDEWATER }), songCard.field).value).toBe('');
	});
});
