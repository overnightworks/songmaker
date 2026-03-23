<script lang="ts">
	import '../app.css';
	import PlayerBar from '$lib/components/PlayerBar.svelte';

	let { children } = $props();
</script>

<svelte:head>
	<title>Songmaker</title>
</svelte:head>

<div class="app-shell">
	{@render children()}
</div>

<PlayerBar />

<style>
	.app-shell {
		display: flex;
		height: calc(100vh - var(--player-height));
		overflow: hidden;
	}
</style>
