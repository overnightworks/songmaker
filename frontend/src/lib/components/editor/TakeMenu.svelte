<script lang="ts">
	import { tick } from 'svelte';
	import type { GenerationItem } from '$lib/api/types';
	import {
		TAKE_AGAIN_LABEL,
		TAKE_COPY_LINK_LABEL,
		TAKE_DELETE_LABEL,
		TAKE_OVERFLOW_LABEL,
		TAKE_PIN_SEED_LABEL,
		TAKE_PLAYLIST_LABEL,
		TAKE_REMASTER_LABEL,
		TAKE_RESCORE_LABEL,
		TAKE_RESCORING_LABEL,
		TAKE_RESTORE_LABEL,
		TAKE_SHARE_LABEL,
		TAKE_UNSHARE_LABEL,
		TAKE_USE_AS_REFERENCE_LABEL
	} from '$lib/constants';
	import Icon from '../Icon.svelte';

	interface Props {
		gen: GenerationItem;
		rescoring: boolean;
		onagain: () => void;
		onuseasreference: () => void;
		onshare: () => void;
		onunshare: () => void;
		oncopylink: () => void;
		onpinseed: () => void;
		onaddtoplaylist: () => void;
		onremaster: () => void;
		onrescore: () => void;
		onrestore: () => void;
		ondelete: () => void;
	}

	let {
		gen,
		rescoring,
		onagain,
		onuseasreference,
		onshare,
		onunshare,
		oncopylink,
		onpinseed,
		onaddtoplaylist,
		onremaster,
		onrescore,
		onrestore,
		ondelete
	}: Props = $props();

	const takeLabel = $derived(
		gen.version_number !== null
			? `Take · v${gen.version_number} · ${gen.generation_number}`
			: `Take · ${gen.generation_number}`
	);

	let open = $state(false);
	let menuEl: HTMLDivElement | undefined = $state();
	let flipUp = $state(false);

	async function toggle(e: MouseEvent): Promise<void> {
		e.stopPropagation();
		open = !open;
		if (!open) return;
		await tick();
		if (!menuEl) return;
		flipUp = menuEl.getBoundingClientRect().bottom > window.innerHeight;
	}

	function runAndClose(action: () => void): void {
		open = false;
		action();
	}

	$effect(() => {
		if (!open) return;
		function onDocClick(): void {
			open = false;
		}
		function onDocKeydown(event: KeyboardEvent): void {
			if (event.key !== 'Escape') return;
			event.preventDefault();
			open = false;
		}
		document.addEventListener('click', onDocClick);
		document.addEventListener('keydown', onDocKeydown, true);
		return () => {
			document.removeEventListener('click', onDocClick);
			document.removeEventListener('keydown', onDocKeydown, true);
		};
	});
</script>

<div class="take-menu-anchor">
	<button
		type="button"
		class="overflow-btn"
		data-hitbox="frequent"
		data-hitbox-face
		aria-haspopup="menu"
		aria-expanded={open}
		aria-label={TAKE_OVERFLOW_LABEL}
		onclick={toggle}
	>
		<Icon name="more-horizontal" size={16} />
	</button>
	{#if open}
		<div
			bind:this={menuEl}
			class="overflow-menu"
			class:flip-up={flipUp}
			role="menu"
			data-escape-overlay="true"
			tabindex="-1"
			onclick={(e) => e.stopPropagation()}
			onkeydown={(e) => e.stopPropagation()}
		>
			<p class="menu-heading">{takeLabel}</p>
			{#if gen.is_shared}
				<button
					type="button"
					role="menuitem"
					class="overflow-item"
					onclick={() => runAndClose(oncopylink)}
				>
					{TAKE_COPY_LINK_LABEL}
				</button>
				<button
					type="button"
					role="menuitem"
					class="overflow-item"
					onclick={() => runAndClose(onunshare)}
				>
					{TAKE_UNSHARE_LABEL}
				</button>
			{:else}
				<button
					type="button"
					role="menuitem"
					class="overflow-item"
					onclick={() => runAndClose(onshare)}
				>
					{TAKE_SHARE_LABEL}
				</button>
			{/if}
			<button
				type="button"
				role="menuitem"
				class="overflow-item"
				onclick={() => runAndClose(onpinseed)}
			>
				{TAKE_PIN_SEED_LABEL}
			</button>
			<button
				type="button"
				role="menuitem"
				class="overflow-item"
				onclick={() => runAndClose(onuseasreference)}
			>
				{TAKE_USE_AS_REFERENCE_LABEL}
			</button>
			<button
				type="button"
				role="menuitem"
				class="overflow-item"
				onclick={() => runAndClose(onagain)}
			>
				{TAKE_AGAIN_LABEL}
			</button>
			<button
				type="button"
				role="menuitem"
				class="overflow-item"
				onclick={() => runAndClose(onaddtoplaylist)}
			>
				{TAKE_PLAYLIST_LABEL}
			</button>
			<button
				type="button"
				role="menuitem"
				class="overflow-item"
				onclick={() => runAndClose(onremaster)}
			>
				{TAKE_REMASTER_LABEL}
			</button>
			<button
				type="button"
				role="menuitem"
				class="overflow-item"
				disabled={rescoring}
				onclick={() => runAndClose(onrescore)}
			>
				{rescoring ? TAKE_RESCORING_LABEL : TAKE_RESCORE_LABEL}
			</button>
			{#if gen.is_archived}
				<button
					type="button"
					role="menuitem"
					class="overflow-item"
					onclick={() => runAndClose(onrestore)}
				>
					{TAKE_RESTORE_LABEL}
				</button>
			{/if}
			<button
				type="button"
				role="menuitem"
				class="overflow-item destructive"
				onclick={() => runAndClose(ondelete)}
			>
				{TAKE_DELETE_LABEL}
			</button>
		</div>
	{/if}
</div>

<style>
	.take-menu-anchor {
		position: relative;
	}

	.overflow-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		background: none;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		color: var(--text-muted);
		padding: 0.15rem 0.3rem;
		cursor: pointer;
	}

	.overflow-btn:hover,
	.overflow-btn[aria-expanded='true'] {
		border-color: var(--primary);
		color: var(--primary);
	}

	.overflow-menu {
		position: absolute;
		right: 0;
		top: calc(100% + 4px);
		z-index: 5;
		min-width: 12rem;
		display: flex;
		flex-direction: column;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		padding: 0.25rem;
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
	}

	.overflow-menu.flip-up {
		top: auto;
		bottom: calc(100% + 4px);
	}

	.menu-heading {
		margin: 0;
		padding: 0.3rem 0.55rem 0.4rem;
		font-family: var(--font-display);
		font-size: 0.65rem;
		letter-spacing: 0.5px;
		text-transform: uppercase;
		color: var(--text-subtle);
		border-bottom: 1px solid var(--border);
		margin-bottom: 0.25rem;
	}

	.overflow-item {
		background: none;
		border: none;
		text-align: left;
		padding: 0.4rem 0.55rem;
		color: var(--text-muted);
		font-size: 0.75rem;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.4px;
		cursor: pointer;
		border-radius: 3px;
	}

	.overflow-item:hover:not(:disabled) {
		background: var(--surface-hover);
		color: var(--text);
	}

	.overflow-item.destructive:hover:not(:disabled) {
		color: var(--score-bad);
	}

	.overflow-item:disabled {
		color: var(--text-subtle);
		cursor: default;
	}
</style>
