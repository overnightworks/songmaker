import { makeSong, makeVersion } from '#lib/test-utils/factories.ts';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('#lib/api/client.ts', () => ({
	fetchVersions: vi.fn().mockResolvedValue([]),
	updateSong: vi.fn(),
	deleteVersion: vi.fn(),
	fetchSong: vi.fn()
}));

import {
	discardDraft,
	followUnsavedDraftAtUnload,
	loadSongData,
	loadVersionAsDraft,
	setDraftLyrics,
	versions
} from './editor';

const SAVED_LYRICS = 'saved lyrics';

function unloadIsAsked(): boolean {
	const unload = new Event('beforeunload', { cancelable: true });
	window.dispatchEvent(unload);
	return unload.defaultPrevented;
}

let stopFollowing: () => void;

beforeEach(async () => {
	discardDraft();
	versions.set([]);
	loadSongData(makeSong({ id: 's1', lyrics: SAVED_LYRICS }));
	await Promise.resolve();
	stopFollowing = followUnsavedDraftAtUnload();
});

afterEach(() => stopFollowing());

describe('followUnsavedDraftAtUnload', () => {
	it('asks before the document unloads while the draft holds typed text no version holds', () => {
		setDraftLyrics('typed draft');

		expect(unloadIsAsked()).toBe(true);
	});

	it('stays silent when the song was just loaded', () => {
		expect(unloadIsAsked()).toBe(false);
	});

	it('stays silent when the draft is retyped to the saved text', () => {
		setDraftLyrics('typed draft');
		setDraftLyrics(SAVED_LYRICS);

		expect(unloadIsAsked()).toBe(false);
	});

	it('stays silent for a draft that only holds an older version untouched', () => {
		const older = makeVersion({ id: 'v1', version_number: 1, lyrics: 'older lyrics' });
		versions.set([makeVersion({ id: 'v2', version_number: 2, lyrics: SAVED_LYRICS }), older]);
		loadVersionAsDraft(older);

		expect(unloadIsAsked()).toBe(false);
	});

	it('stays silent after Discard', () => {
		setDraftLyrics('typed draft');
		discardDraft();

		expect(unloadIsAsked()).toBe(false);
	});

	it('stays silent once the returned function stops following', () => {
		setDraftLyrics('typed draft');
		stopFollowing();

		expect(unloadIsAsked()).toBe(false);
	});
});
