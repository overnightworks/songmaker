export function escHtml(s: string): string {
	return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

export function trackFileToRoute(file: string): { album: string; version: string } {
	const parts = file.split('/');
	const album = parts[0];
	const version = parts[parts.length - 1].replace('.mp3', '');
	return { album, version };
}
