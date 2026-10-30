<script module lang="ts">
	export const SEARCH_SHEET_LABEL = 'Search';
	export const SEARCH_CLOSE_LABEL = 'Close search';
</script>

<script lang="ts">
	import { page } from '$app/state';
	import { APP_NAME, SEARCH_OPEN_LABEL, SONG_TITLE_LABEL } from '#lib/constants.ts';
	import { backLabel, backTargetName, pageBackShown } from '#lib/routes/pageBack.ts';
	import { standingPage } from '#lib/routes/standingAddress.ts';
	import { historyLayerState } from '#lib/stores/layers.ts';
	import { inertWhileAddressOverlay } from '#lib/stores/libraryAddressOverlay.ts';
	import { albumList, songList } from '#lib/stores/libraryData.ts';
	import { openHome, stepBackFromPage } from '#lib/stores/navigation.ts';
	import { playlistList } from '#lib/stores/playlists.ts';
	import { phoneAppBar } from '#lib/stores/ui.ts';
	import { handleFocusTrapKeydown } from '#lib/utils/focus-trap.ts';
	import AccountMenu from './AccountMenu.svelte';
	import EditableTitle from './EditableTitle.svelte';
	import ShareButton from './ShareButton.svelte';
	import SongMenu from './editor/SongMenu.svelte';
	import RailSearch from './shell/RailSearch.svelte';

	let { username, onlogout }: { username: string; onlogout: () => void } = $props();

	let titleEditor: { startEdit: () => void } | undefined = $state();
	let sheet: HTMLDivElement | undefined = $state();

	const searchSheet = historyLayerState('search-sheet', false);

	const standing = $derived(standingPage(page.state));
	const backShown = $derived(pageBackShown({ ...standing, shell: 'phone' }));
	const targetName = $derived(
		backTargetName({
			...standing,
			shell: 'phone',
			titles: { albums: $albumList, playlists: $playlistList, songs: $songList }
		})
	);

	function goBack(): void {
		void stepBackFromPage(standing.pathname);
	}

	function closeSearch(): void {
		searchSheet.set(false);
	}

	function focusSearchField(sheetPanel: HTMLElement): void {
		sheetPanel.querySelector<HTMLInputElement>('input[type="search"]')?.focus();
	}

	function onWindowKeydown(event: KeyboardEvent): void {
		if (!$searchSheet || !sheet) return;
		handleFocusTrapKeydown(sheet, event);
	}
</script>

<svelte:window onkeydown={onWindowKeydown} />

{#snippet searchButton()}
	<button
		type="button"
		class="bar-icon"
		data-hitbox="frequent"
		aria-haspopup="dialog"
		aria-expanded={$searchSheet}
		aria-label={SEARCH_OPEN_LABEL}
		onclick={() => searchSheet.set(true)}
	>
		<svg
			width="20"
			height="20"
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			stroke-width="2"
			stroke-linecap="round"
			aria-hidden="true"
		>
			<circle cx="11" cy="11" r="7" />
			<path d="m20 20-4-4" />
		</svg>
	</button>
{/snippet}

{#snippet backChevron()}
	<svg
		width="20"
		height="20"
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		aria-hidden="true"
	>
		<path d="M15 5l-7 7 7 7" />
	</svg>
{/snippet}

<header class="mobile-strip">
	{#if $phoneAppBar}
		{#if backShown}
			<button
				type="button"
				class="bar-icon"
				data-hitbox="frequent"
				aria-label={backLabel(targetName)}
				onclick={goBack}
			>
				{@render backChevron()}
			</button>
		{/if}
		<h1 class="bar-title" aria-label={$phoneAppBar.title} {@attach inertWhileAddressOverlay}>
			<EditableTitle
				bind:this={titleEditor}
				value={$phoneAppBar.title}
				onsave={$phoneAppBar.onrename}
				ariaLabel={SONG_TITLE_LABEL}
			/>
		</h1>
		{@render searchButton()}
		<div class="song-control" {@attach inertWhileAddressOverlay}>
			<ShareButton {...$phoneAppBar.share} iconOnly />
		</div>
		<div class="song-control" {@attach inertWhileAddressOverlay}>
			<SongMenu
				{...$phoneAppBar.menu}
				title={$phoneAppBar.title}
				onrename={() => titleEditor?.startEdit()}
			/>
		</div>
	{:else if backShown}
		<button
			type="button"
			class="back"
			data-hitbox="frequent"
			aria-label={backLabel(targetName)}
			onclick={goBack}
		>
			<span class="back-chevron">{@render backChevron()}</span>
			<span class="back-name">{targetName}</span>
		</button>
		{@render searchButton()}
	{:else}
		<button type="button" class="brand" onclick={() => openHome()} data-text={APP_NAME}
			>{APP_NAME}</button
		>
		{@render searchButton()}
		<AccountMenu {username} {onlogout} />
	{/if}
</header>

{#if $searchSheet}
	<div
		bind:this={sheet}
		class="search-sheet"
		role="dialog"
		aria-modal="true"
		aria-label={SEARCH_SHEET_LABEL}
		{@attach focusSearchField}
	>
		<button
			type="button"
			class="search-sheet-close"
			data-hitbox="frequent"
			aria-label={SEARCH_CLOSE_LABEL}
			onclick={closeSearch}
		>
			{@render backChevron()}
		</button>
		<RailSearch onchoose={closeSearch} />
	</div>
{/if}

<style>
	.mobile-strip {
		position: fixed;
		top: 0;
		left: 0;
		right: 0;
		height: var(--header-height);
		display: flex;
		align-items: center;
		gap: var(--row-gap);
		padding: 0 var(--row-gap);
		background: var(--header-bg);
		border-bottom: 1px solid var(--border);
		z-index: 200;
	}

	.bar-icon {
		flex: none;
		border: none;
		background: none;
		color: var(--text);
	}

	.bar-title {
		flex: 1;
		min-width: 0;
		margin: 0;
		font-family: var(--font-display);
		font-size: var(--input-font-size);
		color: var(--text);
		letter-spacing: var(--btn-letter-spacing);
	}

	.song-control {
		display: contents;
	}

	.bar-title :global(.editable-title-display) {
		display: block;
		max-width: 100%;
		box-sizing: border-box;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.back {
		flex: 1;
		min-width: 0;
		display: flex;
		align-items: center;
		justify-content: flex-start;
		padding: 0 10px 0 0;
		border: none;
		background: none;
		color: var(--text);
		font-family: var(--font-display);
		font-size: 1.1rem;
		font-weight: 500;
		letter-spacing: 0.03em;
		white-space: nowrap;
		cursor: pointer;
	}

	.back-chevron {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex: none;
		width: var(--hitbox-frequent);
	}

	.back-name {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.brand {
		margin-right: auto;
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
		font-family: var(--font-display);
		font-size: var(--input-font-size);
		font-weight: 700;
		color: var(--accent);
		letter-spacing: var(--btn-letter-spacing);
		text-transform: uppercase;
	}

	.search-sheet {
		position: fixed;
		inset: 0;
		z-index: 250;
		display: flex;
		flex-direction: column;
		padding-top: calc((var(--header-height) - var(--hitbox-frequent)) / 2);
		background: var(--bg);
	}

	.search-sheet-close {
		position: absolute;
		top: calc((var(--header-height) - var(--hitbox-frequent)) / 2);
		left: var(--row-gap);
		border: none;
		background: none;
		color: var(--text);
	}

	.search-sheet :global(.rail-search-region) {
		display: flex;
		flex: 1;
		flex-direction: column;
		min-height: 0;
	}

	.search-sheet :global(.rail-search-region .rail-search) {
		min-height: var(--hitbox-frequent);
		margin: 0 var(--row-gap) var(--row-gap)
			calc(var(--row-gap) + var(--hitbox-frequent) + var(--row-gap));
	}

	.search-sheet :global(.rail-search-region input) {
		font-size: var(--input-font-size);
	}
</style>
