<!--
	Test-only: composes the group layout (which owns the single LibraryWorkspace
	mount, issue #276) around this address's page, the way SvelteKit itself
	nests them at runtime.
-->
<script lang="ts">
	import Layout from '../+layout.svelte';
	import Page from './+page.svelte';
</script>

<Layout>
	<Page />
</Layout>
