/**
 * Load data from the DB API and convert to the manifest-compatible format
 * that the store and components expect.
 *
 * This adapter layer lets us switch from manifest.json to DB API without
 * touching the store or components. In a future refactor, the store could
 * work directly with VersionItem objects.
 */

import type { Album, Track, VersionItem } from './types';
import { fetchAlbums, fetchLibrary } from './client';

export async function loadFromApi(): Promise<Album[]> {
	const [albumItems, allVersions] = await Promise.all([
		fetchAlbums(),
		fetchLibrary(undefined, 1000)
	]);

	const versionsByAlbum = new Map<string, VersionItem[]>();
	for (const v of allVersions.items) {
		const list = versionsByAlbum.get(v.album_id) ?? [];
		list.push(v);
		versionsByAlbum.set(v.album_id, list);
	}

	const albums: Album[] = [];

	// "All" pseudo-album
	const allTracks = allVersions.items.map(versionToTrack);
	if (allTracks.length > 0) {
		albums.push({
			id: '_all',
			title: 'All',
			artist: albumItems[0]?.artist ?? '',
			subtitle: 'All versions, newest first',
			year: '',
			colors: { primary: '#22cc44', bg: '#0d0d0d' },
			tracks: allTracks
		});
	}

	for (const ai of albumItems) {
		const versions = versionsByAlbum.get(ai.id) ?? [];
		const tracks = versions.map(versionToTrack);
		albums.push({
			id: ai.id,
			title: ai.title,
			artist: ai.artist,
			subtitle: ai.subtitle,
			year: ai.year,
			colors: ai.colors,
			tracks
		});
	}

	return albums;
}

function versionToTrack(v: VersionItem): Track {
	const versionLabel = v.version_number > 0 ? ` v${v.version_number}` : '';
	const whisperLines = v.whisper_text
		? v.whisper_text
				.trim()
				.split('\n')
				.filter((l) => l.trim())
				.map((line) => {
					const trimmed = line.trim();
					if (trimmed.includes('|') && trimmed.split('|', 1)[0].replace('.', '').match(/^\d+$/)) {
						const [confStr, text] = trimmed.split('|', 2);
						return { time: -1, text: text.trim(), section: false, confidence: parseFloat(confStr) };
					}
					return { time: -1, text: trimmed, section: false };
				})
		: [];

	return {
		file: v.mp3_path,
		title: `${v.title}${versionLabel}`,
		number: String(v.track_number || '?'),
		lines: whisperLines,
		intended: [],
		has_sung: whisperLines.length > 0,
		generation: v.generation,
		scores: v.scores
	};
}
