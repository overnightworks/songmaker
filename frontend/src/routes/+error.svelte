<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import Icon from '#lib/components/Icon.svelte';
	import { offline, whenBackOnline } from '#lib/stores/connectivity.ts';

	const OFFLINE_WORDS = 'This page needs the network. It opens by itself when you are back online.';
	const LOAD_FAILED_STATUS = 500;

	// A page chunk that fails to load is a 500 to the router; offline it is the lost network.
	const waitsForNetwork = $derived(page.status === LOAD_FAILED_STATUS && $offline);

	// The router keeps the failed status until the retry's chunk has loaded.
	let retrying = $state(false);

	$effect(() => {
		if (!waitsForNetwork) return;
		return whenBackOnline(() => {
			retrying = true;
			// eslint-disable-next-line svelte/no-navigation-without-resolve -- re-runs the failed navigation to the address kit already resolved
			void goto(page.url.href, { replace: true, refreshAll: true }).finally(() => {
				retrying = false;
			});
		});
	});
</script>

<section class="route-error" role="alert">
	{#if waitsForNetwork || retrying}
		<Icon name="cloud-off" size={32} class="route-error-glyph" />
		<p class="route-error-words">{OFFLINE_WORDS}</p>
	{:else}
		<h1 class="route-error-status">{page.status}</h1>
		<p class="route-error-words">{page.error?.message}</p>
	{/if}
</section>

<style>
	.route-error {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 10px;
		padding: 48px 16px;
		text-align: center;
		color: var(--text);
	}

	.route-error :global(.route-error-glyph) {
		color: var(--text-muted);
	}

	.route-error-status {
		margin: 0;
		font-family: var(--font-display);
		font-weight: 400;
		letter-spacing: 1px;
	}

	.route-error-words {
		margin: 0;
		max-width: 32ch;
		color: var(--text-light);
	}
</style>
