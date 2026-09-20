<script lang="ts">
	import { APP_NAME, RAIL_DRAWER_OPEN_LABEL, SONG_TITLE_LABEL } from '$lib/constants';
	import { openLibraryWall } from '$lib/stores/navigation';
	import { phoneAppBar, sidebarOpen, toggleSidebar } from '$lib/stores/ui';
	import EditableTitle from './EditableTitle.svelte';
	import ShareButton from './ShareButton.svelte';
	import SongMenu from './editor/SongMenu.svelte';

	let titleEditor: { startEdit: () => void } | undefined = $state();
</script>

<header class="mobile-strip">
	<button
		class="drawer-trigger"
		data-hitbox="frequent"
		aria-haspopup="dialog"
		aria-expanded={$sidebarOpen}
		aria-label={RAIL_DRAWER_OPEN_LABEL}
		onclick={toggleSidebar}
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
			<path d="M4 7h16M4 12h16M4 17h16" />
		</svg>
	</button>
	{#if $phoneAppBar}
		<h1 class="song-title" aria-label={$phoneAppBar.title}>
			<EditableTitle
				bind:this={titleEditor}
				value={$phoneAppBar.title}
				onsave={$phoneAppBar.onrename}
				ariaLabel={SONG_TITLE_LABEL}
			/>
		</h1>
		<ShareButton {...$phoneAppBar.share} iconOnly />
		<SongMenu
			{...$phoneAppBar.menu}
			title={$phoneAppBar.title}
			onrename={() => titleEditor?.startEdit()}
		/>
	{:else}
		<button type="button" class="brand" onclick={() => openLibraryWall()} data-text={APP_NAME}
			>{APP_NAME}</button
		>
	{/if}
</header>

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

	.mobile-strip :global(.menu-panel) {
		left: auto;
		right: 0;
	}

	.drawer-trigger {
		border: none;
		background: none;
		color: var(--text);
	}

	.song-title {
		flex: 1;
		min-width: 0;
		margin: 0;
		font-family: var(--font-display);
		font-size: var(--input-font-size);
		color: var(--text);
		letter-spacing: var(--btn-letter-spacing);
	}

	.song-title :global(.editable-title-display) {
		display: block;
		max-width: 100%;
		box-sizing: border-box;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.brand {
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
</style>
