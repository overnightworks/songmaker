<script lang="ts">
	import { tick } from 'svelte';
	import type { ShareResult, UnplayableSongSummary } from '$lib/api/types';
	import { focusFirstIn, handleFocusTrapKeydown } from '$lib/utils/focus-trap';
	import {
		ALBUM_COVER_SUGGESTIONS_REPLACE_LABEL,
		ALBUM_COVER_UPLOAD_LABEL,
		COLLECTION_MENU_ADD_TO_PLAYLIST_LABEL,
		COLLECTION_MENU_ARCHIVE_LABEL,
		COLLECTION_MENU_CLOSE_LABEL,
		COLLECTION_MENU_COVER_REMOVE_LABEL,
		COLLECTION_MENU_CURATE_LABEL,
		COLLECTION_MENU_DELETE_PREFIX,
		COLLECTION_MENU_LABEL,
		COLLECTION_MENU_RENAME_LABEL,
		COLLECTION_MENU_SAVE_OFFLINE_LABEL,
		COLLECTION_MENU_SAVE_OFFLINE_REMOVE_LABEL,
		COLLECTION_MENU_SAVE_OFFLINE_SAVING_LABEL,
		COLLECTION_MENU_SHARE_PREFIX
	} from '$lib/constants';
	import Icon from './Icon.svelte';
	import ShareButton from './ShareButton.svelte';
	import ShareDialog from './ShareDialog.svelte';

	interface Props {
		kind: 'album' | 'playlist';
		title: string;
		isShared: boolean;
		shareSlug: string | null | undefined;
		onshare: () => Promise<ShareResult>;
		onunshare: () => Promise<void>;
		onrename: () => void;
		ondelete: () => void;
		onarchive?: () => void;
		oncover?: () => void;
		oncoversuggest?: () => void;
		hasCover?: boolean;
		onremovecover?: () => void;
		onaddtoplaylist?: () => void;
		oncurate?: () => void;
		onsaveoffline?: () => void;
		offlineSaved?: boolean;
		offlineSaving?: boolean;
		offlineProgressLabel?: string | null;
	}

	let {
		kind,
		title,
		isShared,
		shareSlug,
		onshare,
		onunshare,
		onrename,
		ondelete,
		onarchive,
		oncover,
		oncoversuggest,
		hasCover = false,
		onremovecover,
		onaddtoplaylist,
		oncurate,
		onsaveoffline,
		offlineSaved = false,
		offlineSaving = false,
		offlineProgressLabel = null
	}: Props = $props();

	const kindLabel = $derived(kind === 'album' ? 'Album' : 'Playlist');
	const shareLabel = $derived(`${COLLECTION_MENU_SHARE_PREFIX} ${kind}`);
	const deleteLabel = $derived(`${COLLECTION_MENU_DELETE_PREFIX} ${kind}`);

	let menuOpen = $state(false);
	let triggerButton: HTMLButtonElement | undefined = $state();
	let menu: HTMLDivElement | undefined = $state();
	let missingTakeSongs: UnplayableSongSummary[] = $state([]);

	async function shareAndWarnIfIncomplete(): Promise<ShareResult> {
		const result = await onshare();
		if (kind === 'album' && result.songs_without_playable_take.length > 0) {
			missingTakeSongs = result.songs_without_playable_take;
			// Close the menu so its own focus-trapped dialog doesn't stack with
			// ShareDialog's -- two independent window keydown handlers would
			// otherwise both react to a single Escape press.
			closeMenu(false);
		}
		return result;
	}

	function closeShareWarning(): void {
		missingTakeSongs = [];
	}

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

<div class="collection-menu">
	<button
		bind:this={triggerButton}
		class="menu-trigger"
		data-hitbox="frequent"
		aria-haspopup="dialog"
		aria-expanded={menuOpen}
		aria-label={COLLECTION_MENU_LABEL}
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
			aria-label={COLLECTION_MENU_LABEL}
			tabindex="-1"
		>
			<p class="menu-heading">{kindLabel} · {title}</p>
			<div class="menu-row">
				<span class="menu-row-label">{shareLabel}</span>
				<ShareButton {isShared} {shareSlug} onshare={shareAndWarnIfIncomplete} {onunshare} />
			</div>
			{#if oncover}
				<button class="menu-item" onclick={() => runAndClose(oncover)}
					>{ALBUM_COVER_UPLOAD_LABEL}</button
				>
			{/if}
			{#if kind === 'album' && oncoversuggest}
				<button class="menu-item" onclick={() => runAndClose(oncoversuggest)}
					>{ALBUM_COVER_SUGGESTIONS_REPLACE_LABEL}</button
				>
			{/if}
			{#if hasCover && onremovecover}
				<button class="menu-item" onclick={() => runAndClose(onremovecover)}
					>{COLLECTION_MENU_COVER_REMOVE_LABEL}</button
				>
			{/if}
			{#if kind === 'playlist' && onsaveoffline}
				<button
					class="menu-item"
					onclick={() => runAndClose(onsaveoffline)}
					disabled={offlineSaving}
				>
					{#if offlineSaved}
						{COLLECTION_MENU_SAVE_OFFLINE_REMOVE_LABEL}
					{:else if offlineSaving}
						{offlineProgressLabel ?? COLLECTION_MENU_SAVE_OFFLINE_SAVING_LABEL}
					{:else}
						{COLLECTION_MENU_SAVE_OFFLINE_LABEL}
					{/if}
				</button>
			{/if}
			<button class="menu-item" onclick={() => runAndClose(onrename)}
				>{COLLECTION_MENU_RENAME_LABEL}</button
			>
			{#if kind === 'album' && onaddtoplaylist}
				<button class="menu-item" onclick={() => runAndClose(onaddtoplaylist)}
					>{COLLECTION_MENU_ADD_TO_PLAYLIST_LABEL}</button
				>
			{/if}
			{#if kind === 'album' && oncurate}
				<button class="menu-item" onclick={() => runAndClose(oncurate)}
					>{COLLECTION_MENU_CURATE_LABEL}</button
				>
			{/if}
			{#if kind === 'album' && onarchive}
				<button class="menu-item" onclick={() => runAndClose(onarchive)}
					>{COLLECTION_MENU_ARCHIVE_LABEL}</button
				>
			{/if}
			<button class="menu-item destructive" onclick={() => runAndClose(ondelete)}>
				<Icon name="trash" size={14} />
				{deleteLabel}
			</button>
		</div>
	{/if}
	<ShareDialog songs={missingTakeSongs} onclose={closeShareWarning} />
</div>

<style>
	.collection-menu {
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
		background: color-mix(in srgb, #000 42%, transparent);
		cursor: default;
	}

	.menu-panel {
		position: absolute;
		top: calc(100% + 0.5rem);
		right: 0;
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
		font-size: 0.7rem;
		letter-spacing: 0.5px;
		text-transform: uppercase;
		color: var(--text-subtle);
		border-bottom: 1px solid var(--border);
		margin-bottom: 0.25rem;
		overflow-wrap: anywhere;
	}

	.menu-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.5rem;
		padding: 0.25rem 0.6rem;
	}

	.menu-row-label {
		font-size: 0.87rem;
		color: var(--text);
	}

	.menu-item {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		min-height: var(--hitbox-frequent);
		padding: 0.5rem 0.6rem;
		border-radius: 4px;
		font-size: 0.87rem;
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
		opacity: 0.5;
		cursor: default;
	}

	.menu-item.destructive {
		color: var(--score-bad);
	}
</style>
