<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { APP_NAME } from '#lib/constants/app.ts';
	import { HOME_ROUTE_PATH } from '#lib/routes/addresses.ts';
	import { LegalLinks } from 'overnightworks-appkit';
	import { LEGAL_SECTIONS } from '#lib/constants/legal.ts';
</script>

<footer class="powered">
	<p class="lead">Powered by <a href={HOME_ROUTE_PATH}>{APP_NAME}</a></p>
	<LegalLinks links={LEGAL_SECTIONS} newTab />
</footer>

<style>
	.powered {
		margin-top: 3rem;
		padding-bottom: calc(var(--player-height, 88px) + 1rem);
		font-size: 0.75rem;
		color: var(--text-subtle, #888);
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: center;
		gap: 0.25rem 1rem;
	}

	.lead {
		margin: 0;
	}

	.powered a {
		color: var(--text-muted, #888);
		text-decoration: none;
	}

	.powered a:hover {
		color: var(--accent);
	}
</style>
