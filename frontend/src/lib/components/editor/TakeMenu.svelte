<script lang="ts">
	import { tick } from 'svelte';
	import { focusFirstIn, handleFocusTrapKeydown } from '$lib/utils/focus-trap';
	import type { GenerationItem, ShareResult } from '$lib/api/types';
	import {
		TAKE_REPAINT_LABEL,
		TAKE_COVER_LABEL,
		TAKE_DELETE_LABEL,
		TAKE_OVERFLOW_LABEL,
		TAKE_PLAYLIST_LABEL,
		TAKE_SHARE_LABEL
	} from '$lib/constants';
	import Icon from '../Icon.svelte';
	import ShareButton from '../ShareButton.svelte';

	interface Props {
		gen: GenerationItem;
		onrepaint: () => void;
		oncover: () => void;
		onshare: () => Promise<ShareResult>;
		onunshare: () => Promise<void>;
		onaddtoplaylist: () => void;
		ondelete: () => void;
	}

	let { gen, onrepaint, oncover, onshare, onunshare, onaddtoplaylist, ondelete }: Props = $props();

	const takeLabel = $derived(
		gen.version_number !== null
			? `Take · v${gen.version_number} · ${gen.generation_number}`
			: `Take · ${gen.generation_number}`
	);

	let open = $state(false);
	let trigger: HTMLButtonElement | undefined = $state();
	let menuEl: HTMLDivElement | undefined = $state();
	let flipUp = $state(false);

	async function toggle(e: MouseEvent): Promise<void> {
		e.stopPropagation();
		open = !open;
		if (!open) return;
		await tick();
		if (!menuEl) return;
		flipUp = menuEl.getBoundingClientRect().bottom > window.innerHeight;
		focusFirstIn(menuEl);
	}

	function runAndClose(action: () => void): void {
		open = false;
		trigger?.focus();
		action();
	}

	$effect(() => {
		if (!open) return;
		function onDocClick(): void {
			open = false;
		}
		function onDocKeydown(event: KeyboardEvent): void {
			if (!menuEl) return;
			handleFocusTrapKeydown(menuEl, event, () => {
				open = false;
				trigger?.focus();
			});
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
		bind:this={trigger}
		type="button"
		class="overflow-btn"
		data-hitbox="frequent"
		data-hitbox-face
		aria-haspopup="menu"
		aria-expanded={open}
		aria-label={TAKE_OVERFLOW_LABEL}
		title={TAKE_OVERFLOW_LABEL}
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
			<button
				type="button"
				role="menuitem"
				class="overflow-item"
				data-hitbox="text"
				onclick={() => runAndClose(onrepaint)}
			>
				<Icon name="paintbrush" />{TAKE_REPAINT_LABEL}
			</button>
			<button
				type="button"
				role="menuitem"
				class="overflow-item"
				data-hitbox="text"
				onclick={() => runAndClose(oncover)}
			>
				<Icon name="layers" />{TAKE_COVER_LABEL}
			</button>
			<button
				type="button"
				role="menuitem"
				class="overflow-item"
				data-hitbox="text"
				onclick={() => runAndClose(onaddtoplaylist)}
			>
				<Icon name="list-plus" />{TAKE_PLAYLIST_LABEL}
			</button>
			<div class="share-row" role="none">
				<span>{TAKE_SHARE_LABEL}</span>
				<ShareButton isShared={gen.is_shared} shareSlug={gen.share_slug} {onshare} {onunshare} />
			</div>
			<button
				type="button"
				role="menuitem"
				class="overflow-item destructive"
				data-hitbox="text"
				onclick={() => runAndClose(ondelete)}
			>
				<Icon name="trash" />{TAKE_DELETE_LABEL}
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
		width: 14rem;
		max-width: calc(100vw - 2rem);
		display: flex;
		flex-direction: column;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		padding: 0.25rem;
	}

	.overflow-menu.flip-up {
		top: auto;
		bottom: calc(100% + 4px);
	}

	.menu-heading {
		margin: 0;
		padding: 0.3rem 0.55rem 0.4rem;
		font-family: var(--font-display);
		font-size: var(--label-font-size);
		letter-spacing: 0.5px;
		color: var(--text-subtle);
		border-bottom: 1px solid var(--border);
		margin-bottom: 0.25rem;
	}

	.overflow-item {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		background: none;
		border: none;
		text-align: left;
		padding: 0.4rem 0.55rem;
		color: var(--text-muted);
		font-size: var(--btn-font-size);
		font-family: var(--font-body);
		cursor: pointer;
		border-radius: var(--btn-radius-sm);
	}

	.overflow-item:hover:not(:disabled) {
		background: var(--surface-hover);
		color: var(--text);
	}

	.overflow-item.destructive,
	.overflow-item.destructive:hover:not(:disabled) {
		color: var(--score-bad);
	}

	.share-row {
		position: relative;
		display: flex;
		align-items: center;
		min-height: var(--hitbox-frequent);
		padding: 0.4rem 0.55rem 0.4rem calc(0.55rem + 16px + 0.6rem);
		color: var(--text-muted);
		font-family: var(--font-body);
		font-size: var(--btn-font-size);
	}

	.share-row :global(.share-btn) {
		position: absolute;
		inset: 0;
		display: flex;
		align-items: center;
		padding: 0.4rem 0.55rem;
		border: none;
		border-radius: var(--btn-radius-sm);
	}

	.share-row :global(.share-btn:hover:not(:disabled)) {
		background: var(--surface-hover);
	}

	.share-row span {
		position: relative;
		z-index: 1;
		pointer-events: none;
	}
</style>
