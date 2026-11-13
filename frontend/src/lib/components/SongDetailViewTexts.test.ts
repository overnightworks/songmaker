import {
	clearSongDetailState,
	editableSongDefaults,
	renderView,
	resetSongDetailState
} from '#lib/test-utils/song-detail-view.ts';
import { makeGeneration as generation, makeSong as song } from '#lib/test-utils/factories.ts';
import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { fetchSong } from '#lib/api/client.ts';
import { songList } from '#lib/stores/libraryData.ts';
import { phoneAppBar } from '#lib/stores/ui.ts';
import { words } from '#lib/words/en.ts';

vi.mock('$app/navigation', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation()
);
vi.mock('#lib/api/library.ts', () => ({
	searchLibrary: vi.fn()
}));
vi.mock('#lib/api/albums.ts', async () =>
	(await import('#lib/test-utils/song-detail-mocks.ts')).albumsApiMock()
);
vi.mock('#lib/api/loras.ts', async (importOriginal) =>
	(await import('#lib/test-utils/song-detail-mocks.ts')).lorasApiMock(
		await importOriginal<typeof import('#lib/api/loras.ts')>()
	)
);
vi.mock('#lib/api/songs.ts', () => ({
	fetchSong: vi.fn(),
	fetchSongs: vi.fn()
}));
vi.mock('#lib/api/client.ts', async (importOriginal) =>
	(await import('#lib/test-utils/song-detail-mocks.ts')).clientApiMock(
		await importOriginal<typeof import('#lib/api/client.ts')>()
	)
);
vi.mock('#lib/stores/toast.ts', () => ({
	addToast: vi.fn(),
	addUndoToast: vi.fn()
}));

function appBar() {
	const state = get(phoneAppBar);
	if (!state) throw new Error('Expected the song app bar');
	return state;
}

beforeEach(resetSongDetailState);

afterEach(clearSongDetailState);

describe('SongDetailView expiry digest', () => {
	const dayMs = 24 * 60 * 60 * 1000;
	const [soonLabel, daysLabel] = [
		{ branch: 'soon', expiresInMs: -dayMs, when: () => words['songPage.expirySoon'] },
		{ branch: 'days', expiresInMs: 2 * dayMs - 1000, when: () => words['songPage.expiryDays'](2) }
	];

	it.each([
		{ takes: 1, ...soonLabel },
		{ takes: 3, ...soonLabel },
		{ takes: 1, ...daysLabel },
		{ takes: 3, ...daysLabel }
	])('words $takes expiring take(s) in the $branch branch from the catalog', async (entry) => {
		const generations = Array.from({ length: entry.takes }, (_, index) =>
			generation({
				id: `g${index}`,
				expires_at: new Date(Date.now() + entry.expiresInMs).toISOString()
			})
		);
		songList.set([song({ ...editableSongDefaults(), generation_count: entry.takes, generations })]);
		const target = await renderView();
		const digest = target.querySelector('.expiry-digest');
		expect(digest?.textContent).toContain(
			words['songPage.expiry'](entry.takes, { when: entry.when() })
		);
	});
});

describe('SongDetailView song delete confirm counts', () => {
	afterEach(() => {
		vi.mocked(fetchSong).mockRestore();
	});

	it.each([
		{ takes: 2, versions: 3 },
		{ takes: 1, versions: 1 }
	])(
		'lists $takes take(s) and $versions version(s) from the catalog',
		async ({ takes, versions }) => {
			const counted = song({
				...editableSongDefaults(),
				generation_count: takes,
				version_count: versions
			});
			songList.set([counted]);
			vi.mocked(fetchSong).mockResolvedValue(counted);
			const target = await renderView();
			appBar().menu.ondelete();
			await tick();
			const dialog = target.querySelector('[role="dialog"]');
			expect(dialog?.textContent).toContain(words['songPage.deleteTakes'](takes));
			expect(dialog?.textContent).toContain(words['songPage.deleteVersions'](versions));
		}
	);
});
