export function playerTakeIdForSong(
	currentSongId: string,
	playing: { songId: string; generationId: string } | null
): string | null {
	if (!playing || !currentSongId || playing.songId !== currentSongId) {
		return null;
	}
	return playing.generationId;
}
