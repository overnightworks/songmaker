<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { APP_NAME } from '$lib/constants';
	import LegalContent from '../LegalContent.svelte';

	let legalSection: string | null = $state(null);

	function onWindowKeydown(event: KeyboardEvent): void {
		if (event.key !== 'Escape' || !legalSection) return;
		event.preventDefault();
		legalSection = null;
	}
</script>

<svelte:window onkeydown={onWindowKeydown} />

<p class="powered">
	Powered by <a href="/">{APP_NAME}</a>
	· <button class="link-btn" onclick={() => (legalSection = 'impressum')}>Impressum</button>
	· <button class="link-btn" onclick={() => (legalSection = 'datenschutz')}>Datenschutz</button>
	·
	<button class="link-btn" onclick={() => (legalSection = 'nutzungsbedingungen')}
		>Nutzungsbedingungen</button
	>
</p>

{#if legalSection}
	<div class="legal-overlay">
		<!-- svelte-ignore a11y_click_events_have_key_events -->
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="legal-backdrop" onclick={() => (legalSection = null)}></div>
		<div class="legal-modal" role="dialog" aria-modal="true" aria-label="Legal information">
			<LegalContent initialSection={legalSection} onback={() => (legalSection = null)} />
		</div>
	</div>
{/if}

<style>
	.powered {
		text-align: center;
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

	.powered a:hover,
	.powered .link-btn:hover {
		-webkit-text-fill-color: transparent;
	}

	.link-btn {
		background: none;
		border: none;
		padding: 0;
		font: inherit;
		cursor: pointer;
		color: var(--text-muted, #888);
		background: linear-gradient(90deg, var(--primary), var(--accent));
		-webkit-background-clip: text;
		background-clip: text;
	}

	.legal-overlay {
		position: fixed;
		inset: 0;
		z-index: 100;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.legal-backdrop {
		position: absolute;
		inset: 0;
		background: rgba(0, 0, 0, 0.8);
		backdrop-filter: blur(4px);
	}

	.legal-modal {
		position: relative;
		max-height: 85dvh;
		max-width: 700px;
		width: 95%;
		overflow-y: auto;
		background: var(--bg, #0a0a0a);
		border: 1px solid var(--border, #333);
		border-radius: 8px;
		box-shadow: 0 0 40px color-mix(in srgb, var(--accent) 10%, transparent);
	}
</style>
