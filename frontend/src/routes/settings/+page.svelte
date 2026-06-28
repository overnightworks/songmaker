<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { goto } from '$app/navigation';
	import { isAdmin } from '$lib/stores/auth';

	const admin = $derived($isAdmin);

	$effect(() => {
		const target = admin ? '/settings/generation' : '/settings/playback';
		goto(target, { replaceState: true });
	});
</script>
