<script lang="ts">
	// The Playlists page's address (#1402) names no resource, so unlike its
	// sibling addresses it has nothing to look up, no verdict to state and no
	// overlay over the workspace: it only has the library show the page,
	// through the frame every address route resolves in.
	import { onMount } from 'svelte';
	import { openPlaylistsAddress } from '#lib/stores/libraryContext.ts';

	onMount(() => {
		void openPlaylistsAddress();
	});
</script>
