<script lang="ts">
	import { tick } from 'svelte';
	import { focusFirstIn, handleFocusTrapKeydown } from '$lib/utils/focus-trap';
	import {
		COLLECTION_MENU_CLOSE_LABEL,
		SONG_MENU_ADD_TO_PLAYLIST_LABEL,
		SONG_MENU_DELETE_LABEL,
		SONG_MENU_RENAME_LABEL,
		SONG_MENU_SAVE_LABEL,
		SONG_MENU_LABEL
	} from '$lib/constants';
	import Icon from '../Icon.svelte';

	interface Props {
		title: string;
		saveDisabled: boolean;
		onsave: () => void;
		onrename: () => void;
		onaddtoplaylist: () => void;
		ondelete: () => void;
	}

	let { title, saveDisabled, onsave, onrename, onaddtoplaylist, ondelete }: Props = $props();

	let menuOpen = $state(false);
	let triggerButton: HTMLButtonElement | undefined = $state();
	let menu: HTMLDivElement | undefined = $state();

	async function openMenu(): Promise<void> {
		menuOpen = true;
		await tick();
		if (menu) focusFirstIn(menu);
	}

	function closeMenu(restoreFocus = true): void {
		if (!menuOpen) return;
		menuOpen = false;
		if (restoreFocus) queueMicrotask(() => triggerButton?.focus());
	}

	function toggleMenu(): void {
		if (menuOpen) closeMenu();
		else void openMenu();
	}

	function onWindowKeydown(event: KeyboardEvent): void {
		if (!menuOpen || !menu) return;
		handleFocusTrapKeydown(menu, event, () => closeMenu());
	}

	function runAndClose(action: () => void): void {
		closeMenu();
		action();
	}
</script>

<svelte:window onkeydown={onWindowKeydown} />

<div class="song-menu">
	<button
		bind:this={triggerButton}
		class="menu-trigger"
		data-hitbox="frequent"
		aria-haspopup="dialog"
		aria-expanded={menuOpen}
		aria-label={SONG_MENU_LABEL}
		onclick={toggleMenu}
	>
		<Icon name="more-horizontal" size={18} />
	</button>
	{#if menuOpen}
		<div class="menu-backdrop-layer">
			<button
				class="menu-backdrop"
				tabindex="-1"
				onclick={() => closeMenu()}
				aria-label={COLLECTION_MENU_CLOSE_LABEL}
			></button>
		</div>
		<div
			bind:this={menu}
			class="menu-panel"
			role="dialog"
			aria-modal="true"
			aria-label={SONG_MENU_LABEL}
			tabindex="-1"
		>
			<p class="menu-heading">Song · {title}</p>
			<button class="menu-item" disabled={saveDisabled} onclick={() => runAndClose(onsave)}>
				{SONG_MENU_SAVE_LABEL}
			</button>
			<button class="menu-item" onclick={() => runAndClose(onrename)}
				>{SONG_MENU_RENAME_LABEL}</button
			>
			<button class="menu-item" onclick={() => runAndClose(onaddtoplaylist)}>
				{SONG_MENU_ADD_TO_PLAYLIST_LABEL}
			</button>
			<button class="menu-item destructive" onclick={() => runAndClose(ondelete)}>
				<Icon name="trash" size={14} />
				{SONG_MENU_DELETE_LABEL}
			</button>
		</div>
	{/if}
</div>

<style>
	.song-menu {
		position: relative;
	}

	.menu-trigger {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		background: none;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		color: var(--text-muted);
		padding: 0.4rem;
	}

	.menu-trigger:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.menu-backdrop-layer {
		position: fixed;
		inset: 0;
		z-index: 300;
	}

	.menu-backdrop {
		position: absolute;
		inset: 0;
		width: 100%;
		border: 0;
		background: color-mix(in srgb, var(--bg-deep) 42%, transparent);
		cursor: default;
	}

	.menu-panel {
		position: absolute;
		top: calc(100% + 0.5rem);
		left: 0;
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 220px;
		max-width: calc(100vw - 32px);
		padding: 0.5rem;
		background: var(--header-bg);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		z-index: 301;
	}

	.menu-heading {
		margin: 0;
		padding: 0.3rem 0.6rem 0.5rem;
		font-family: var(--font-display);
		font-size: var(--label-font-size);
		letter-spacing: 0.5px;
		text-transform: uppercase;
		color: var(--text-subtle);
		border-bottom: 1px solid var(--border);
		margin-bottom: 0.25rem;
		overflow-wrap: anywhere;
	}

	.menu-item {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		min-height: var(--hitbox-frequent);
		padding: 0.5rem 0.6rem;
		border-radius: var(--btn-radius-sm);
		font-size: var(--btn-font-size-sm);
		color: var(--text);
		background: none;
		border: none;
		text-align: left;
		cursor: pointer;
	}

	.menu-item:hover:not(:disabled) {
		background: var(--surface-hover);
	}

	.menu-item:disabled {
		color: var(--text-disabled);
		cursor: default;
	}

	.menu-item.destructive {
		color: var(--score-bad);
	}
</style>
