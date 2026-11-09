import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { QueueStreamManifest } from '#lib/api/types.ts';
import { resetConnectivityForTests } from '#lib/stores/connectivity.ts';
import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import {
	fromSharedAlbum,
	fromSharedPlaylist,
	playableTracks,
	type SharedCollectionView
} from './sharedCollection';
import { SharePlayback } from './sharePlayback.svelte';
import {
	albumSong,
	albumView,
	installFakeAudio,
	NO_CALLBACKS,
	streamManifest,
	type FakeAudio
} from './sharePlayback-test-fixtures';

let fakeAudio: FakeAudio;

beforeEach(() => {
	fakeAudio = installFakeAudio();
	vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200 }));
	audioPlayer.destroy();
	audioPlayer.swapCallbacks(NO_CALLBACKS);
});

afterEach(() => {
	resetConnectivityForTests();
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

function nothingPlayableView(): SharedCollectionView {
	return fromSharedAlbum({
		title: 'Album',
		artist: 'Artist',
		subtitle: '',
		year: '',
		songs: [albumSong('s1', 'First', 1, null, null)]
	});
}

function streamHolding(...keys: string[]) {
	const manifest = streamManifest(false);
	return {
		...manifest,
		tracks: manifest.tracks.filter((track) => keys.includes(track.song_id ?? ''))
	};
}

// A rebuilt stream whose one track is none of the share's.
function streamOfOtherTakes() {
	const manifest = streamManifest(false);
	const [first] = manifest.tracks;
	return {
		...manifest,
		stream_url: '/shared-stream-fresh.mp3',
		tracks: [{ ...first, song_id: 'other-song', generation_id: 'other-take' }]
	};
}

describe('shuffle before the first Play', () => {
	it('reorders the queue and starts nothing', () => {
		vi.spyOn(Math, 'random').mockReturnValue(0);
		const playback = new SharePlayback();
		playback.start(albumView(), null);

		playback.setShuffle(true);

		expect({
			order: playback.queueRows.map((row) => row.key),
			shuffle: playback.shuffle,
			current: audioPlayer.current,
			loaded: fakeAudio.src
		}).toEqual({ order: ['s2', 's1'], shuffle: true, current: null, loaded: '' });
		playback.stop();
	});
});

describe('a share with no playable track', () => {
	it.each([
		['Play', (playback: SharePlayback) => playback.play()],
		['a seek', (playback: SharePlayback) => playback.seek(30)]
	])('does nothing on %s', (_name, act) => {
		const playback = new SharePlayback();
		playback.start(nothingPlayableView(), null);

		act(playback);

		expect({ current: audioPlayer.current, loaded: fakeAudio.src }).toEqual({
			current: null,
			loaded: ''
		});
		playback.stop();
	});
});

describe('Next and Previous in stream mode', () => {
	it("move to the stream's next or previous track", async () => {
		const playback = new SharePlayback();
		const view = albumView();
		playback.start(view, vi.fn().mockResolvedValue(streamManifest(false)));
		playback.toggle(playableTracks(view.tracks)[0]);
		await vi.waitFor(() => expect(audioPlayer.mode).toBe('stream'));

		playback.next();
		const afterNext = { key: playback.currentTrack?.key, canPrev: playback.canPrev };
		playback.prev();

		expect({ afterNext, afterPrev: playback.currentTrack?.key }).toEqual({
			afterNext: { key: 's2', canPrev: true },
			afterPrev: 's1'
		});
		playback.stop();
	});
});

describe('a playlist share with a stream', () => {
	it('plays each entry from the stream by its entry', async () => {
		const view = fromSharedPlaylist({
			title: 'Mix',
			album_covers: [],
			entries: ['e1', 'e2'].map((entryId, index) => ({
				entry_id: entryId,
				song_title: `Entry ${entryId}`,
				album_title: 'Album',
				artist: 'Artist',
				generation_number: 1,
				audio_url: `/shared/slug/audio/${entryId}.mp3`,
				generation_id: `g${index + 1}`,
				audio_duration: 50,
				lyrics: null,
				whisper_cues: null
			}))
		});
		const manifest = streamManifest(false);
		const stream = {
			...manifest,
			tracks: manifest.tracks.map((track, index) => ({ ...track, entry_id: `e${index + 1}` }))
		};
		const playback = new SharePlayback();
		playback.start(view, vi.fn().mockResolvedValue(stream));

		playback.toggle(playableTracks(view.tracks)[1]);
		await vi.waitFor(() => expect(audioPlayer.mode).toBe('stream'));

		expect({
			key: playback.currentTrack?.key,
			durations: playback.queueRows.map((r) => r.durationSec)
		}).toEqual({
			key: 'e2',
			durations: [10, 10]
		});
		playback.stop();
	});
});

describe('a track the stream does not hold', () => {
	it('plays on its own, with its duration from the payload', async () => {
		const playback = new SharePlayback();
		const view = albumView();
		playback.start(view, vi.fn().mockResolvedValue(streamHolding('s1')));
		playback.toggle(playableTracks(view.tracks)[0]);
		await vi.waitFor(() => expect(audioPlayer.mode).toBe('stream'));
		const durations = playback.queueRows.map((row) => row.durationSec);

		playback.toggle(playableTracks(view.tracks)[1]);
		await vi.waitFor(() => expect(audioPlayer.mode).toBe('classic'));

		expect({ durations, mode: audioPlayer.mode, loaded: fakeAudio.src }).toEqual({
			durations: [10, 96],
			mode: 'classic',
			loaded: '/shared/slug/audio/s2.mp3'
		});
		playback.stop();
	});
});

describe('a stream rebuild whose manifest lacks the playing take', () => {
	it('leaves no row active', async () => {
		let answerRebuild: (manifest: QueueStreamManifest) => void = () => {};
		const fetchStream = vi
			.fn()
			.mockResolvedValueOnce(streamManifest(false))
			.mockReturnValueOnce(
				new Promise<QueueStreamManifest>((resolve) => (answerRebuild = resolve))
			);
		const playback = new SharePlayback();
		const view = albumView();
		playback.start(view, fetchStream);
		playback.toggle(playableTracks(view.tracks)[0]);
		await vi.waitFor(() => expect(audioPlayer.mode).toBe('stream'));
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404 }));
		fakeAudio.currentTime = 4;
		fakeAudio.fire('timeupdate');
		fakeAudio.fire('error');
		await vi.waitFor(() => expect(fetchStream).toHaveBeenCalledTimes(2));

		audioPlayer.pause();
		answerRebuild(streamOfOtherTakes());
		await vi.waitFor(() =>
			expect(playback.queueRows.map((row) => row.durationSec)).toEqual([128, 96])
		);
		playback.next();

		expect(playback.queue.currentIndex).toBe(-1);
		playback.stop();
	});
});
