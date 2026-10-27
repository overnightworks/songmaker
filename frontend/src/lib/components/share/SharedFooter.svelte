<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { APP_NAME } from '$lib/constants';
	import { HOME_ROUTE_PATH } from '$lib/routes/addresses';
	import LegalLinks from '../LegalLinks.svelte';
</script>

<footer class="powered">
	<LegalLinks newTab>
		{#snippet lead()}Powered by <a href={HOME_ROUTE_PATH}>{APP_NAME}</a>{/snippet}
	</LegalLinks>
</footer>

<style>
	.powered {
		margin-top: 3rem;
		padding-bottom: calc(var(--player-height, 88px) + 1rem);
		font-size: 0.75rem;
		color: var(--text-subtle, #888);
	}

	.powered a {
		color: var(--text-muted, #888);
		text-decoration: none;
		background: linear-gradient(90deg, var(--primary), var(--accent));
		-webkit-background-clip: text;
		background-clip: text;
	}

	.powered a:hover {
		-webkit-text-fill-color: transparent;
	}
</style>
