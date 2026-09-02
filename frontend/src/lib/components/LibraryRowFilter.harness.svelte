<!--
	Test-only, mirrors LibraryRow.harness.svelte: mount()'s low-level props
	take a plain, non-reactive object, so a bindable prop only round-trips
	through a real compiled parent whose own state is a Svelte rune -- a
	closure variable passed as a getter/setter pair to mount() never
	triggers the framework's own reactivity. `value` is echoed into a text
	node so a test can read what the field currently holds without needing
	that outer closure.
-->
<script lang="ts">
	import LibraryRowFilter from './LibraryRowFilter.svelte';

	interface Props {
		collectionLabel?: string;
	}

	let { collectionLabel = 'Albums' }: Props = $props();
	let value = $state('');
</script>

<p class="filter-value-probe">{value}</p>
<LibraryRowFilter bind:value {collectionLabel} />
