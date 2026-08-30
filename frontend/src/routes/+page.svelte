<script lang="ts">
	// The library workspace lives in a component because two addresses mount
	// it: this one and /album/<slug> (issue #269). Its live-sync and history
	// lifecycle belongs to +layout.svelte, so swapping between those two
	// routes costs nothing.
	import LibraryWorkspace from '$lib/components/LibraryWorkspace.svelte';
</script>

<LibraryWorkspace />
