<script lang="ts">
	// The library's three addresses (`/`, `/album/<slug>`, `/album/<slug>/<song-slug>`)
	// are entrances to one workspace, not three of them (issue #276): each used to
	// mount LibraryWorkspace itself, so crossing between addresses swapped the leaf
	// `+page.svelte` and tore the workspace down with it. This group layout is what
	// stands across that crossing, so LibraryWorkspace mounts here, once, for as
	// long as the browser stays on any of the three. A leaf page still resolves its
	// own address and renders an overlay in `children` while it does — stacked over
	// the workspace rather than replacing it, so the workspace underneath never
	// unmounts for a resolution that fails or is still in flight.
	import { onMount } from 'svelte';
	import LibraryWorkspace from '#lib/components/LibraryWorkspace.svelte';
	import { inertWhileAddressOverlay } from '#lib/stores/libraryAddressOverlay.ts';
	import { restoreLastPlayback } from '#lib/stores/player.ts';

	let { children } = $props();

	// The root layout renders this group only once auth has a user, so the
	// take that user last played here can come back, paused (#1187 P2).
	onMount(() => {
		void restoreLastPlayback();
	});
</script>

<div class="library-stack">
	<!-- Inert while an address overlay is up, so the stale workspace leaves the tab order. -->
	<div class="workspace-wrapper" {@attach inertWhileAddressOverlay}>
		<LibraryWorkspace />
	</div>
	{@render children()}
</div>

<style>
	.library-stack {
		position: relative;
		display: flex;
		flex: 1;
		flex-direction: column;
		min-width: 0;
		min-height: 0;
	}

	.workspace-wrapper {
		display: flex;
		flex: 1;
		flex-direction: column;
		min-width: 0;
		min-height: 0;
	}
</style>
