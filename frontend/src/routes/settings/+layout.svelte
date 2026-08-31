<script lang="ts">
	let { children } = $props();
</script>

<main class="settings-content">
	{@render children()}
</main>

<style>
	.settings-content {
		flex: 1;
		overflow-y: auto;
		min-width: 0;
	}
</style>
