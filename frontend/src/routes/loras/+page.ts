import { redirect } from '@sveltejs/kit';

// /loras moved under Settings; keep the old URL working for existing links
// and bookmarks.
export function load() {
	redirect(308, '/settings/voices');
}
