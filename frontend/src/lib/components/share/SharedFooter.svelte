<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { tick } from 'svelte';
	import { APP_NAME } from '$lib/constants';
	import { focusFirstIn, handleFocusTrapKeydown } from '$lib/utils/focus-trap';
	import LegalContent from '../LegalContent.svelte';

	let legalSection: string | null = $state(null);
	let modal: HTMLDivElement | undefined = $state();

	function closeLegal(): void {
		legalSection = null;
	}

	$effect(() => {
		if (!legalSection) return;
		void tick().then(() => {
			if (modal) focusFirstIn(modal);
		});
	});

	function onWindowKeydown(event: KeyboardEvent): void {
		if (!legalSection || !modal) return;
		handleFocusTrapKeydown(modal, event, closeLegal);
	}
</script>

<svelte:window onkeydown={onWindowKeydown} />

<p class="powered">
	<span class="footer-item">Powered by <a href="/">{APP_NAME}</a></span>
	<span class="footer-item"
		><button class="link-btn" onclick={() => (legalSection = 'impressum')}>Impressum</button></span
	>
	<span class="footer-item"
		><button class="link-btn" onclick={() => (legalSection = 'datenschutz')}>Datenschutz</button
		></span
	>
	<span class="footer-item">
		<button class="link-btn" onclick={() => (legalSection = 'nutzungsbedingungen')}
			>Nutzungsbedingungen</button
		>
	</span>
</p>

{#if legalSection}
	<div class="legal-overlay">
		<button class="legal-backdrop" tabindex="-1" onclick={closeLegal} aria-label="Close"></button>
		<div
			bind:this={modal}
			class="legal-modal"
			role="dialog"
			aria-modal="true"
			aria-label="Legal information"
			tabindex="-1"
		>
			<LegalContent initialSection={legalSection} onback={closeLegal} />
		</div>
	</div>
{/if}

<style>
	.powered {
		display: flex;
		flex-wrap: wrap;
		justify-content: center;
		margin-top: 3rem;
		padding-bottom: calc(var(--player-height, 88px) + 1rem);
		font-size: 0.75rem;
		color: var(--text-subtle, #888);
	}

	.footer-item:not(:first-child)::before {
		content: '·';
		margin: 0 0.35em;
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
		z-index: 150;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.legal-backdrop {
		position: absolute;
		inset: 0;
		width: 100%;
		border: 0;
		background: rgba(0, 0, 0, 0.8);
		backdrop-filter: blur(4px);
		cursor: default;
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
