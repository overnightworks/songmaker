<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import Icon from '#lib/components/Icon.svelte';
	import { offline, whenBackOnline } from '#lib/stores/connectivity.ts';

	const OFFLINE_WORDS = 'This page needs the network. It opens by itself when you are back online.';
	const LOAD_FAILED_STATUS = 500;

	// A page chunk that fails to load is a 500 to the router; offline it is the lost network.
	const waitsForNetwork = $derived(page.status === LOAD_FAILED_STATUS && $offline);

	$effect(() => {
		if (!waitsForNetwork) return;
		return whenBackOnline(() => {
			void goto(page.url.href, { replaceState: true, invalidateAll: true });
		});
	});
</script>

<section class="route-error" role="alert">
	{#if waitsForNetwork}
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
