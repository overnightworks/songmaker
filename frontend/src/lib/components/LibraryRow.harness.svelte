<!--
	Test-only: mounts LibraryRow the way LibraryWorkspace.svelte does in
	production -- collection comes from the real openCollection store, not a
	one-shot prop -- so a test can change what's open on a *live* instance by
	writing to that store, the same way a click or a route change does at
	runtime. Svelte's low-level mount() takes props as a plain, non-reactive
	object; only a real compiled parent re-evaluates a child's prop
	expressions when its own state changes, which is what this harness is
	for.
-->
<script lang="ts">
	import { openCollection } from '$lib/stores/collection';
	import LibraryRow from './LibraryRow.svelte';

	const collection = $derived($openCollection);
</script>

{#if collection}
	<LibraryRow {collection} />
{/if}
