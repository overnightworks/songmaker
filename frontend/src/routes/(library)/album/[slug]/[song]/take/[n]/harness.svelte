<!--
	Test-only: composes the group layout (which owns the single LibraryWorkspace
	mount, issue #276) around this address's page, the way SvelteKit itself
	nests them at runtime. Mounting the page alone would show nothing for the
	`open` address state, since the page no longer renders the workspace.
-->
<script lang="ts">
	import Layout from '../../../../../+layout.svelte';
	import Page from './+page.svelte';
</script>

<Layout>
	<Page />
</Layout>
