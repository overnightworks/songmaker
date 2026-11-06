<script lang="ts">
	// The Home address names no resource, so it only has the library show Home,
	// through the frame every address route resolves in. Any query on it is
	// dropped by `openHomeAddress`.
	import { onMount } from 'svelte';
	import { openHomeAddress } from '#lib/stores/libraryContext.ts';

	onMount(() => {
		void openHomeAddress();
	});
</script>
