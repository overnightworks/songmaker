import { makeAlbum as album } from '$lib/test-utils/factories';
import { flushSync, mount, tick, unmount } from 'svelte';
import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { goto } from '$app/navigation';
import { ApiError } from '$lib/api/fetch';
import { openCollection, resetCollectionForTests } from '$lib/stores/collection';
import { albumList } from '$lib/stores/libraryData';
import { addToast } from '$lib/stores/toast';
import { replaceHistoryEntry } from '$lib/test-utils/library-history';

const createAlbum = vi.fn();

vi.mock('$app/navigation', async () =>
	(await import('$lib/test-utils/app-navigation')).fakeAppNavigation()
);
vi.mock('$app/paths', () => ({ resolve: vi.fn((path: string) => path) }));
vi.mock('$lib/api/client', () => ({
	createAlbum: (...args: unknown[]) => createAlbum(...args),
	fetchAlbums: vi.fn(),
	fetchSongs: vi.fn().mockResolvedValue({ items: [], has_more: false })
}));
vi.mock('$lib/api/songs', () => ({ fetchSong: vi.fn(), fetchSongs: vi.fn() }));
vi.mock('$lib/stores/toast', () => ({ addToast: vi.fn() }));

import NewAlbumCard from './NewAlbumCard.svelte';

const NIGHT_DRIVE = album({ id: 'a-night', title: 'Night Drive', artist: '' });

let mounted: ReturnType<typeof mount> | undefined;
let cancels: number;
let creates: number;
let restoreUnhandledRejections: (() => void) | undefined;

beforeEach(() => {
	createAlbum.mockReset().mockResolvedValue(NIGHT_DRIVE);
	vi.mocked(addToast).mockClear();
	albumList.set([]);
	resetCollectionForTests();
	replaceHistoryEntry('/');
	cancels = 0;
	creates = 0;
});

afterEach(async () => {
	restoreUnhandledRejections?.();
	restoreUnhandledRejections = undefined;
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

async function render(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(NewAlbumCard, {
		target,
		props: { oncancel: () => (cancels += 1), oncreated: () => (creates += 1) }
	});
	await tick();
	return target;
}

function field(root: ParentNode, label: string): HTMLInputElement {
	const input = [...root.querySelectorAll('label')]
		.find((candidate) => candidate.textContent?.trim().startsWith(label))
		?.querySelector('input');
	if (!input) throw new Error(`no ${label} field`);
	return input;
}

function type(input: HTMLInputElement, value: string): void {
	input.value = value;
	input.dispatchEvent(new Event('input', { bubbles: true }));
	flushSync();
}

function createButton(root: ParentNode): HTMLButtonElement {
	const button = [...root.querySelectorAll('button')].find(
		(candidate) => candidate.textContent?.trim() === 'Create'
	);
	if (!button) throw new Error('no Create button');
	return button;
}

// The submit handler's promise has no caller to reject into, so a failure it
// lets escape surfaces as an unhandled rejection; the test collects those
// instead of letting the runner report them as a crash.
function captureUnhandledRejections(): unknown[] {
	const escaped: unknown[] = [];
	const runnerListeners = process.listeners('unhandledRejection');
	process.removeAllListeners('unhandledRejection');
	process.on('unhandledRejection', (reason) => escaped.push(reason));
	restoreUnhandledRejections = () => {
		process.removeAllListeners('unhandledRejection');
		for (const listener of runnerListeners) process.on('unhandledRejection', listener);
	};
	return escaped;
}

async function createSettled(): Promise<void> {
	await vi.waitFor(() => expect(createAlbum).toHaveBeenCalled());
	await tick();
	await tick();
}

describe('NewAlbumCard', () => {
	it('names itself New album and puts the cursor in Title', async () => {
		const root = await render();

		expect(root.querySelector('[aria-label="New album"]')).not.toBeNull();
		expect(document.activeElement).toBe(field(root, 'Title'));
		expect(field(root, 'Artist').required).toBe(false);
	});

	it.each([
		{ case: 'no title', title: '' },
		{ case: 'a title of spaces', title: '   ' }
	])('offers no Create for $case', async ({ title }) => {
		const root = await render();

		type(field(root, 'Title'), title);

		expect(createButton(root).disabled).toBe(true);
	});

	it('creates the album with its title and optional artist, lists it and opens its page', async () => {
		const root = await render();
		type(field(root, 'Title'), '  Night Drive ');
		type(field(root, 'Artist'), ' Lichtwechsel ');

		createButton(root).click();
		await createSettled();

		expect(createAlbum).toHaveBeenCalledWith('Night Drive', 'Lichtwechsel');
		expect(get(albumList).map((listed) => listed.id)).toEqual(['a-night']);
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a-night' });
		expect(creates).toBe(1);
	});

	it('creates on Enter in the title field', async () => {
		const root = await render();
		type(field(root, 'Title'), 'Night Drive');

		field(root, 'Title').form?.requestSubmit();
		await createSettled();

		expect(createAlbum).toHaveBeenCalledWith('Night Drive', '');
	});

	it('keeps the card and what was typed when the server refuses, and says why', async () => {
		createAlbum.mockRejectedValue(new ApiError(422, 'Title too long', '/api/albums'));
		const root = await render();
		type(field(root, 'Title'), 'Night Drive');

		createButton(root).click();
		await createSettled();

		expect(creates).toBe(0);
		expect(field(root, 'Title').value).toBe('Night Drive');
		expect(createButton(root).disabled).toBe(false);
		expect(get(openCollection)).toBeNull();
		expect(addToast).toHaveBeenCalledWith(expect.stringContaining('Title too long'), 'error');
	});

	it('keeps the created album listed and says nothing failed when only opening its page fails', async () => {
		const openFailure = new Error('navigation aborted');
		vi.mocked(goto).mockRejectedValueOnce(openFailure);
		const escaped = captureUnhandledRejections();
		const root = await render();
		type(field(root, 'Title'), 'Night Drive');

		createButton(root).click();
		await createSettled();

		await vi.waitFor(() => expect(escaped).toContain(openFailure));
		expect(get(albumList).map((listed) => listed.id)).toEqual(['a-night']);
		expect(addToast).not.toHaveBeenCalled();
	});

	it('× closes it and creates nothing', async () => {
		const root = await render();
		type(field(root, 'Title'), 'Night Drive');

		root.querySelector<HTMLButtonElement>('[aria-label="Close new album"]')?.click();
		await tick();

		expect(cancels).toBe(1);
		expect(createAlbum).not.toHaveBeenCalled();
	});
});
