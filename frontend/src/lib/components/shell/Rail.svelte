<script lang="ts">
	import { openLibraryWall } from '$lib/stores/navigation';
	import { APP_NAME, RAIL_NAV_LABEL } from '$lib/constants';
	import RailLibraryGroup from './RailLibraryGroup.svelte';
	import RailPlaylistsGroup from './RailPlaylistsGroup.svelte';
	import RailSettings from './RailSettings.svelte';
	import UserRow from './UserRow.svelte';

	let { username, onlogout }: { username: string; onlogout: () => void } = $props();
</script>

<nav class="rail" aria-label={RAIL_NAV_LABEL}>
	<div class="rail-top">
		<button type="button" class="brand" onclick={() => openLibraryWall()} data-text={APP_NAME}
			>{APP_NAME}</button
		>
	</div>

	<div class="rail-scroll">
		<RailLibraryGroup />
		<RailPlaylistsGroup />
	</div>

	<div class="rail-settings-pin">
		<RailSettings />
	</div>

	<div class="rail-bottom">
		<UserRow {username} {onlogout} />
	</div>
</nav>

<style>
	.rail {
		display: flex;
		flex-direction: column;
		width: var(--rail-width);
		flex-shrink: 0;
		height: 100%;
		min-height: 0;
		background: var(--surface);
		border-right: 1px solid var(--border);
		overflow: hidden;
	}

	.rail-top {
		display: flex;
		align-items: center;
		height: var(--header-height);
		padding: 0 16px;
		flex-shrink: 0;
	}

	.brand {
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
		font-family: var(--font-display);
		font-size: 16px;
		font-weight: 700;
		color: var(--accent);
		letter-spacing: 3px;
		text-transform: uppercase;
		text-decoration: none;
	}

	.rail-scroll {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
	}

	.rail-settings-pin {
		flex-shrink: 0;
	}

	/* Reaches into RailGroup's own panel (rendered by RailSettings) so the
	   Settings group -- pinned outside the scroll container -- caps its own
	   height instead of pushing the Library group above it fully off-screen
	   on a short viewport; RailGroup's own .rail-group-content stays
	   overflow:hidden for every other caller (Library's scrolling already
	   happens one level up, in .rail-scroll). */
	.rail-settings-pin :global(.rail-group-content) {
		max-height: 40vh;
		overflow-y: auto;
	}

	.rail-bottom {
		flex-shrink: 0;
		border-top: 1px solid var(--border);
		padding: 4px 0;
	}
</style>
