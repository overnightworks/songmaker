import { redirect } from '@sveltejs/kit';

// Settings › Playback lost its last setting (#1187 P4), and a settings
// section with no setting does not exist; old links and bookmarks land on
// Settings itself.
export function load() {
	redirect(308, '/settings');
}
