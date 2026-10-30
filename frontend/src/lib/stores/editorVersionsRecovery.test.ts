import { makeSong, makeVersion } from '#lib/test-utils/factories.ts';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import * as api from '#lib/api/client.ts';
import { ApiError, NetworkError } from '#lib/api/fetch.ts';
import { selectedSongId } from '#lib/stores/player.ts';
import { reportResourceStreamReachable } from '#lib/stores/connectivity.ts';
import { toasts } from '#lib/stores/toast.ts';
import {
	discardDraft,
	draftLoadedFrom,
	editAudioDuration,
	editBpm,
	editGenParams,
	editKeyScale,
	editLyrics,
	editPrompt,
	isDirty,
	loadSongData,
	loadVersionAsDraft,
	setDraftLyrics,
	versions
} from './editor';

function revertedDraft() {
	discardDraft();
	return {
		lyrics: get(editLyrics),
		prompt: get(editPrompt),
		bpm: get(editBpm),
		audioDuration: get(editAudioDuration),
		keyScale: get(editKeyScale),
		genParams: get(editGenParams)
	};
}

describe('versions recovery', () => {
	beforeEach(() => {
		vi.spyOn(api, 'fetchVersions').mockResolvedValue([]);
		discardDraft();
		selectedSongId.set('s1');
		toasts.set([]);
		versions.set([]);
		reportResourceStreamReachable(false);
	});
	afterEach(() => {
		selectedSongId.set(null);
		reportResourceStreamReachable(true);
		vi.restoreAllMocks();
	});

	it.each(['typed', 'loaded'])(
		'1160-F40-versions reconnect restores versions and preserves a %s draft',
		async (draft) => {
			const { fetchVersions } = await import('#lib/api/client.ts');
			const latest = makeVersion({ id: 'v2', version_number: 2 });
			const older = makeVersion({ id: 'v1', version_number: 1, lyrics: 'older lyrics' });
			vi.mocked(fetchVersions).mockRejectedValueOnce(
				new NetworkError('/versions', new TypeError('unreachable'))
			);
			loadSongData(makeSong({ id: 's1' }));
			await Promise.resolve();
			const startDraft = () => {
				if (draft === 'loaded') {
					versions.set([latest, older]);
					loadVersionAsDraft(older);
				} else setDraftLyrics('typed lyrics');
			};
			startDraft();
			const savedBefore = revertedDraft();
			startDraft();
			expect(get(toasts)).toEqual([]);
			vi.mocked(fetchVersions).mockResolvedValueOnce([latest, older]);
			reportResourceStreamReachable(true);
			await Promise.resolve();
			expect(get(versions)).toEqual([latest, older]);
			expect(get(editLyrics)).toBe(draft === 'loaded' ? 'older lyrics' : 'typed lyrics');
			expect(get(draftLoadedFrom)).toBe(draft === 'loaded' ? 1 : null);
			expect(get(isDirty)).toBe(true);
			expect(revertedDraft()).toEqual(savedBefore);
		}
	);

	it.each(['success', 'network failure', 'refusal'])(
		'1160-F40-versions ignores an old song response: %s',
		async (result) => {
			const { fetchVersions } = await import('#lib/api/client.ts');
			let finish!: (value: ReturnType<typeof makeVersion>[]) => void;
			let fail!: (error: Error) => void;
			vi.mocked(fetchVersions).mockReturnValueOnce(
				new Promise((resolve, reject) => {
					finish = resolve;
					fail = reject;
				})
			);
			loadSongData(makeSong({ id: 's1' }));
			selectedSongId.set('s2');
			const current = [makeVersion({ id: 's2-version' })];
			vi.mocked(fetchVersions).mockResolvedValueOnce(current);
			loadSongData(makeSong({ id: 's2' }));
			await Promise.resolve();
			if (result === 'success') finish([makeVersion({ id: 'stale' })]);
			else
				fail(
					result === 'refusal'
						? new ApiError(403, 'Forbidden', '/versions')
						: new NetworkError('/versions', new TypeError('unreachable'))
				);
			await Promise.resolve();
			reportResourceStreamReachable(true);
			await Promise.resolve();
			expect(get(versions)).toEqual(current);
			expect(get(toasts)).toEqual([]);
		}
	);

	it('1160-F40-versions cancels a pending reconnect reload when leaving the song', async () => {
		const { fetchVersions } = await import('#lib/api/client.ts');
		vi.mocked(fetchVersions).mockRejectedValueOnce(
			new NetworkError('/versions', new TypeError('unreachable'))
		);
		loadSongData(makeSong({ id: 's1' }));
		await Promise.resolve();
		selectedSongId.set('s2');
		reportResourceStreamReachable(true);
		await Promise.resolve();
		expect(fetchVersions).toHaveBeenCalledTimes(1);
		expect(get(versions)).toEqual([]);
		expect(get(toasts)).toEqual([]);
	});

	it('1160-F40-versions names a refusal and does not retry on reconnect', async () => {
		const { fetchVersions } = await import('#lib/api/client.ts');
		vi.mocked(fetchVersions).mockClear();
		vi.mocked(fetchVersions).mockRejectedValueOnce(new ApiError(403, 'Forbidden', '/versions'));
		loadSongData(makeSong({ id: 's1' }));
		await Promise.resolve();
		expect(get(toasts)).toEqual([expect.objectContaining({ message: 'Forbidden' })]);
		reportResourceStreamReachable(true);
		await Promise.resolve();
		expect(get(versions)).toEqual([]);
		expect(fetchVersions).toHaveBeenCalledTimes(1);
	});
});
