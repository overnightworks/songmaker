import type { Manifest } from './types.ts';

const API_KEY =
	typeof window !== 'undefined'
		? (new URLSearchParams(window.location.search).get('key') ?? '')
		: '';

function apiUrl(path: string): string {
	const sep = path.includes('?') ? '&' : '?';
	return API_KEY ? `${path}${sep}api_key=${API_KEY}` : path;
}

export async function fetchManifest(): Promise<Manifest> {
	const resp = await fetch(apiUrl('/manifest.json'), { cache: 'no-store' });
	if (!resp.ok) throw new Error(`Failed to fetch manifest: ${resp.status}`);
	return resp.json() as Promise<Manifest>;
}

export async function rateVersion(
	album: string,
	version: string,
	rating: number,
	notes: string
): Promise<void> {
	await fetch(apiUrl(`/rate/${album}/${version}`), {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ rating, notes })
	});
}
