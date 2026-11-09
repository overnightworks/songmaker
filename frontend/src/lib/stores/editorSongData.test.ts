import { makeSong } from '#lib/test-utils/factories.ts';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import * as api from '#lib/api/client.ts';
import { selectedSongId } from '#lib/stores/player.ts';
import { discardDraft, editAudioDuration, editBpm, editKeyScale, loadSongData } from './editor';

beforeEach(() => {
	vi.spyOn(api, 'fetchVersions').mockResolvedValue([]);
	selectedSongId.set('s1');
});
afterEach(() => {
	selectedSongId.set(null);
	vi.restoreAllMocks();
});

it('a song with no bpm, duration or key opens in the editor as 0, 0 and empty', () => {
	loadSongData(makeSong({ id: 's1', bpm: null, audio_duration: null, key_scale: null }));
	discardDraft();

	expect([get(editBpm), get(editAudioDuration), get(editKeyScale)]).toEqual([0, 0, '']);
});
