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
	import LibraryWorkspace from '$lib/components/LibraryWorkspace.svelte';
	import { libraryAddressOverlayActive } from '$lib/stores/libraryAddressOverlay';

	let { children } = $props();
	let workspaceWrapper: HTMLDivElement | undefined = $state();

	// `position: absolute` and `z-index` on the overlay only decide paint
	// order, not the accessibility tree or the tab order -- the workspace is
	// unconditionally mounted underneath it now, so without this a keyboard or
	// screen-reader user tabs straight into the stale, invisible workspace
	// before ever reaching the overlay's own "Try again"/"Back" action. `inert`
	// removes the whole subtree from both the tab order and the accessibility
	// tree, which is what a single `{#if}/{:else}` used to give for free when
	// the overlay was the workspace's only DOM (issue #276 review fix).
	//
	// Driven imperatively rather than through a Svelte `inert={...}` attribute
	// binding: jsdom (used by the unit suite) has no `inert` IDL property, and
	// Svelte's attribute codegen detects that absence and falls back to a
	// plain property assignment invisible to `hasAttribute` -- correct in a
	// real browser, untestable here. `toggleAttribute` is the same DOM API in
	// both.
	$effect(() => {
		return libraryAddressOverlayActive.subscribe((active) => {
			workspaceWrapper?.toggleAttribute('inert', active);
		});
	});
</script>

<div class="library-stack">
	<div class="workspace-wrapper" bind:this={workspaceWrapper}>
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
