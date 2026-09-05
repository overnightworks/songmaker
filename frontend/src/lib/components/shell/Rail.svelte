<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { openLibraryWall } from '$lib/stores/navigation';
	import { APP_NAME, RAIL_NAV_LABEL } from '$lib/constants';
	import { kineticScroll } from '$lib/actions/kineticScroll';
	import RailLibraryGroup from './RailLibraryGroup.svelte';
	import RailPlaylistsGroup from './RailPlaylistsGroup.svelte';
	import RailSearch from './RailSearch.svelte';
	import RailSettings from './RailSettings.svelte';
	import UserRow from './UserRow.svelte';
	import { RAIL_ITEM_SELECTOR } from './rail-item-selector';
	import { toggleRailCollapsed } from '$lib/stores/ui';

	let {
		username,
		onlogout,
		collapsed = false,
		showCollapseControl = true
	}: {
		username: string;
		onlogout: () => void;
		collapsed?: boolean;
		showCollapseControl?: boolean;
	} = $props();

	const collapseRailLabel = 'Collapse rail';
	const expandRailLabel = 'Expand rail';
</script>

<nav class="rail" class:rail-collapsed={collapsed} aria-label={RAIL_NAV_LABEL}>
	<div class="rail-top">
		<button
			type="button"
			class="brand"
			aria-label={collapsed ? APP_NAME : undefined}
			onclick={() => openLibraryWall()}
			data-text={APP_NAME}
		>
			{#if collapsed}
				<span class="brand-mark" aria-hidden="true">H</span>
			{:else}
				{APP_NAME}
			{/if}
		</button>
	</div>
	<RailSearch />

	<div class="rail-scroll" use:kineticScroll={{ itemSelector: RAIL_ITEM_SELECTOR }}>
		<RailLibraryGroup />
		<RailPlaylistsGroup />
	</div>

	<div class="rail-settings-pin">
		<RailSettings />
	</div>

	<div class="rail-bottom">
		{#if collapsed}
			<a class="collapsed-account" href="/settings/account" aria-label="Account" title="Account">
				{username.slice(0, 1).toUpperCase()}
			</a>
		{:else}
			<UserRow {username} {onlogout} />
		{/if}
	</div>

	{#if showCollapseControl}
		<button
			type="button"
			class="rail-collapse"
			aria-label={collapsed ? expandRailLabel : collapseRailLabel}
			title={collapsed ? expandRailLabel : collapseRailLabel}
			onclick={toggleRailCollapsed}
		>
			{collapsed ? '›' : '‹'}
		</button>
	{/if}
</nav>

<style>
	.rail {
		position: relative;
		display: flex;
		flex-direction: column;
		width: var(--rail-width);
		flex-shrink: 0;
		height: 100%;
		min-height: 0;
		background: var(--surface);
		border-right: 1px solid var(--border);
		overflow: visible;
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
		cursor: grab;
		user-select: none;
		-webkit-user-select: none;
	}

	.rail-scroll:global(.is-dragging) {
		cursor: grabbing;
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

	.rail-collapse {
		position: absolute;
		top: 50%;
		right: -12px;
		z-index: 2;
		display: grid;
		place-items: center;
		width: 24px;
		height: 24px;
		padding: 0;
		border: 1px solid var(--border);
		border-radius: 50%;
		background: var(--surface);
		color: var(--text-muted);
		box-shadow: 0 1px 3px rgb(0 0 0 / 20%);
	}

	.rail-collapse:hover {
		color: var(--text);
		background: var(--surface-hover);
	}

	.rail-collapsed {
		align-items: center;
	}

	.rail-collapsed .rail-top {
		justify-content: center;
		width: 100%;
		padding: 0;
	}

	.rail-collapsed :global(.rail-search-region),
	.rail-collapsed :global(.rail-group-panel) {
		display: none;
	}

	.rail-collapsed .rail-scroll,
	.rail-collapsed .rail-settings-pin {
		width: 100%;
	}

	.rail-collapsed :global(.disclose-row) {
		justify-content: center;
	}

	.rail-collapsed :global(.disclose) {
		flex: 0 0 40px;
		justify-content: center;
		padding: 8px;
		border-radius: 4px;
	}

	.rail-collapsed :global(.group-title),
	.rail-collapsed :global(.meta),
	.rail-collapsed :global(.disclose .caret) {
		position: absolute;
		width: 1px;
		height: 1px;
		margin: -1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
		white-space: nowrap;
	}

	.rail-collapsed .rail-bottom {
		width: 100%;
		padding: 8px 0;
		text-align: center;
	}

	.collapsed-account {
		display: inline-grid;
		width: 28px;
		height: 28px;
		place-items: center;
		border-radius: 50%;
		background: var(--accent);
		color: var(--bg);
		font-size: 0.8rem;
		font-weight: 600;
	}
</style>
