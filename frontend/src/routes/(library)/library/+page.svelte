<script lang="ts">
	// The Library's address (#1506) names no resource, so like the Playlists
	// page it only has the library show its wall, through the frame every
	// address route resolves in. Any query on it is ignored.
	import { onMount } from 'svelte';
	import { openLibraryAddress } from '#lib/stores/libraryContext.ts';

	onMount(() => {
		void openLibraryAddress();
	});
</script>
