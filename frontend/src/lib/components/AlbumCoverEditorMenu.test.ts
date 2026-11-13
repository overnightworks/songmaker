import { makeAlbum as album, makeSong as song } from '#lib/test-utils/factories.ts';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { resetConnectivityForTests } from '#lib/stores/connectivity.ts';
import { words } from '#lib/words/en.ts';
import {
	createComponentMount,
	openCollectionMenu,
	requireElement
} from './shell/rail-test-fixtures';
import { albumList, resetLibraryDataForTests, songList } from '#lib/stores/libraryData.ts';
import { selectedAlbumId } from '#lib/stores/player.ts';
import { activeJobs } from '#lib/stores/jobs.ts';
import {
	FakeJobEventSource,
	coverSuggestions,
	coverJob,
	UPLOADED,
	coveredAlbum,
	editor,
	openCoverEditing,
	editingClosed,
	pressEditorButton
} from '#lib/test-utils/album-cover-editor.ts';

const createAlbumCoverSuggestions = vi.fn();
const fetchAlbumCoverSuggestions = vi.fn();
const selectAlbumCoverSuggestion = vi.fn();
const discardAlbumCoverSuggestions = vi.fn();
const deleteAlbumCover = vi.fn();
const uploadAlbumCover = vi.fn();
const cancelJob = vi.fn();

vi.mock('#lib/api/songs.ts', () => ({
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false })
}));
vi.mock('#lib/api/albums.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/albums.ts')>()),
	createAlbumCoverSuggestions: (...args: unknown[]) => createAlbumCoverSuggestions(...args),
	fetchAlbumCoverSuggestions: (...args: unknown[]) => fetchAlbumCoverSuggestions(...args),
	selectAlbumCoverSuggestion: (...args: unknown[]) => selectAlbumCoverSuggestion(...args),
	discardAlbumCoverSuggestions: (...args: unknown[]) => discardAlbumCoverSuggestions(...args)
}));
vi.mock('#lib/api/jobs.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/jobs.ts')>()),
	cancelJob: (...args: unknown[]) => cancelJob(...args)
}));
vi.mock('#lib/api/client.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/client.ts')>()),
	deleteAlbumCover: (...args: unknown[]) => deleteAlbumCover(...args),
	uploadAlbumCover: (...args: unknown[]) => uploadAlbumCover(...args)
}));
vi.mock('#lib/stores/toast.ts', () => ({
	addToast: vi.fn(),
	addUndoToast: vi.fn()
}));

import AlbumDetailView from './AlbumDetailView.svelte';
import { addToast } from '#lib/stores/toast.ts';

const { render: renderDetail, cleanup } = createComponentMount(AlbumDetailView);

beforeEach(() => {
	albumList.set([album({ id: 'a-local', title: 'Night Drive' })]);
	songList.set([
		song({ id: 's-local', album_id: 'a-local', album_title: 'Night Drive', generation_count: 1 })
	]);
	selectedAlbumId.set('a-local');
	createAlbumCoverSuggestions.mockReset();
	fetchAlbumCoverSuggestions.mockReset().mockResolvedValue(coverSuggestions());
	selectAlbumCoverSuggestion.mockReset();
	discardAlbumCoverSuggestions.mockReset().mockResolvedValue(undefined);
	deleteAlbumCover.mockReset();
	uploadAlbumCover.mockReset();
	cancelJob.mockReset().mockResolvedValue(coverJob({ status: 'cancelled' }));
	vi.mocked(addToast).mockReset();
	activeJobs.set([]);
	FakeJobEventSource.sources.length = 0;
});

afterEach(async () => {
	await cleanup();
	selectedAlbumId.set(null);
	albumList.set([]);
	songList.set([]);
	activeJobs.set([]);
	vi.unstubAllGlobals();
	vi.useRealTimers();
	resetConnectivityForTests();
	resetLibraryDataForTests();
});

describe('AlbumCoverEditor menu', () => {
	it('Upload picks a file, and the uploaded cover closes the editor', async () => {
		albumList.set([coveredAlbum()]);
		uploadAlbumCover.mockResolvedValue(coveredAlbum(UPLOADED));
		const target = await renderDetail();
		await openCoverEditing(target);
		const input = requireElement<HTMLInputElement>(target, '.cover-file-input');
		const picker = vi.spyOn(input, 'click').mockImplementation(() => undefined);

		pressEditorButton(target, 'albumCover.upload');
		expect(picker).toHaveBeenCalledTimes(1);
		const file = new File([new Uint8Array([1, 2, 3])], 'cover.jpg', { type: 'image/jpeg' });
		Object.defineProperty(input, 'files', { configurable: true, value: [file] });
		input.dispatchEvent(new Event('change', { bubbles: true }));

		await editingClosed(target);
		expect(target.querySelector('.header-cover img')?.getAttribute('src')).toBe(UPLOADED.detail);
	});

	it('Cover in the menu opens the cover editing without making anything', async () => {
		albumList.set([coveredAlbum()]);
		const target = await renderDetail();
		const menu = await openCollectionMenu(target);
		const items = Array.from(menu.querySelectorAll<HTMLButtonElement>('.menu-item'));

		items
			.find((item) => item.textContent?.trim().startsWith(words['collectionMenu.cover']))
			?.click();

		await vi.waitFor(() => expect(editor(target)).not.toBeNull());
		expect(createAlbumCoverSuggestions).not.toHaveBeenCalled();
	});
});
