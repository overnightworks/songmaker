import type { SeedApi } from './seed';

export interface ShareLink {
	share_slug: string;
}

/** The addresses a shared song and a shared take open at, which need no session. */
export interface SongAndTakeShares {
	songShareUrl: string;
	takeShareUrl: string;
}

/** Shares one seeded song and its take. */
export async function seedSongAndTakeShares(
	seed: SeedApi,
	baseUrl: string,
	song: { songId: string; takeId: string }
): Promise<SongAndTakeShares> {
	const songShare = await seed.postJson<ShareLink>(`/api/songs/${song.songId}/share`, {});
	const takeShare = await seed.postJson<ShareLink>(`/api/generations/${song.takeId}/share`, {});
	return {
		songShareUrl: `${baseUrl}/share/song/${songShare.share_slug}`,
		takeShareUrl: `${baseUrl}/share/gen/${takeShare.share_slug}`
	};
}
