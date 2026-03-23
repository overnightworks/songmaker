const API_KEY =
	typeof window !== 'undefined'
		? (new URLSearchParams(window.location.search).get('key') ?? '')
		: '';

function apiUrl(path: string): string {
	const sep = path.includes('?') ? '&' : '?';
	return API_KEY ? `${path}${sep}api_key=${API_KEY}` : path;
}

export interface SongDetail {
	id: string;
	title: string;
	album_id: string;
	track_number: number;
	language: string;
	lyrics: string;
	prompt: string;
	bpm: number;
	duration: number;
	key: string;
	revision_count: number;
	version_count: number;
	created_at: string | null;
}

export interface CreateSongParams {
	title: string;
	album_id: string;
	lyrics?: string;
	prompt?: string;
	bpm?: number;
	duration?: number;
	key?: string;
	language?: string;
}

export async function listSongs(albumId?: string): Promise<SongDetail[]> {
	let path = '/api/songs';
	if (albumId) path += `?album_id=${albumId}`;
	const resp = await fetch(apiUrl(path));
	if (!resp.ok) throw new Error(`List songs failed: ${resp.status}`);
	return resp.json();
}

export async function createSong(params: CreateSongParams): Promise<SongDetail> {
	const resp = await fetch(apiUrl('/api/songs'), {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(params)
	});
	if (!resp.ok) throw new Error(`Create song failed: ${resp.status}`);
	return resp.json();
}

export async function getSong(songId: string): Promise<SongDetail> {
	const resp = await fetch(apiUrl(`/api/songs/${songId}`));
	if (!resp.ok) throw new Error(`Get song failed: ${resp.status}`);
	return resp.json();
}

export async function updateSong(
	songId: string,
	params: Partial<Pick<SongDetail, 'lyrics' | 'prompt' | 'bpm' | 'duration' | 'key'>>
): Promise<SongDetail> {
	const resp = await fetch(apiUrl(`/api/songs/${songId}`), {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(params)
	});
	if (!resp.ok) throw new Error(`Update song failed: ${resp.status}`);
	return resp.json();
}
