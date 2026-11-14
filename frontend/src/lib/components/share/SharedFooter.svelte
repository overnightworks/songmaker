<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { HOME_ROUTE_PATH } from '#lib/routes/addresses.ts';
	import { LegalLinks, Marked } from 'overnightworks-design';
	import { legalLinks } from '#lib/utils/legal-links.ts';
	import { pageParts, pageText } from '#lib/utils/page-words.ts';
	import { kitWords } from '#lib/utils/kit-words.ts';
</script>

<footer class="powered">
	<p class="lead">
		<Marked
			parts={pageParts('sharedFooter.poweredBy', { app: pageText('app.name') })}
			marked={{ home }}
		/>
	</p>
	<LegalLinks links={legalLinks()} words={kitWords()} newTab />
</footer>

{#snippet home({ text }: { text: string })}<a href={HOME_ROUTE_PATH}>{text}</a>{/snippet}

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
