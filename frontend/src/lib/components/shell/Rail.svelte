<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { albumList } from '$lib/stores/player';
	import { openLibraryWall } from '$lib/stores/navigation';
	import { playlistList } from '$lib/stores/playlists';
	import {
		APP_NAME,
		RAIL_LIBRARY_LABEL,
		RAIL_SETTINGS_LABEL,
		librarySummaryLabel
	} from '$lib/constants';
	import RailContext from './RailContext.svelte';
	import UserMenu from './UserMenu.svelte';

	let { username, onlogout }: { username: string; onlogout: () => void } = $props();

	const albumCount = $derived($albumList.length);
	const playlistCount = $derived($playlistList.length);
	const summary = $derived(librarySummaryLabel(albumCount, playlistCount));
</script>

<nav class="rail" aria-label="Primary">
	<div class="rail-top">
		<a class="brand" href="/" data-text={APP_NAME}>{APP_NAME}</a>
	</div>

	<button type="button" class="library-link" onclick={() => openLibraryWall()}>
		<svg
			class="library-icon"
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
			<rect x="3" y="3" width="7" height="7" rx="1" />
			<rect x="14" y="3" width="7" height="7" rx="1" />
			<rect x="3" y="14" width="7" height="7" rx="1" />
			<rect x="14" y="14" width="7" height="7" rx="1" />
		</svg>
		<span class="library-text">
			<span class="library-label">{RAIL_LIBRARY_LABEL}</span>
			<span class="library-summary">{summary}</span>
		</span>
	</button>

	<div class="rail-divider"></div>

	<div class="rail-context-slot">
		<RailContext />
	</div>

	<div class="rail-bottom">
		<a class="settings-link" href="/settings">{RAIL_SETTINGS_LABEL}</a>
		<UserMenu {username} {onlogout} />
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
		font-family: var(--font-display);
		font-size: 16px;
		font-weight: 700;
		color: var(--accent);
		letter-spacing: 3px;
		text-transform: uppercase;
		text-decoration: none;
	}

	.library-link {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 10px 16px;
		background: none;
		border: none;
		color: var(--text);
		text-align: left;
		cursor: pointer;
		flex-shrink: 0;
	}

	.library-link:hover {
		background: var(--surface-hover);
	}

	.library-icon {
		flex-shrink: 0;
		color: var(--text-muted);
	}

	.library-text {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}

	.library-label {
		font-family: var(--font-display);
		font-size: 0.85rem;
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.library-summary {
		font-size: 0.7rem;
		color: var(--text-subtle);
	}

	.rail-divider {
		height: 1px;
		background: var(--border);
		flex-shrink: 0;
	}

	.rail-context-slot {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
	}

	.rail-bottom {
		flex-shrink: 0;
		border-top: 1px solid var(--border);
		padding: 4px 0;
	}

	.settings-link {
		display: block;
		padding: 8px 16px;
		color: var(--text-muted);
		font-size: 0.85rem;
		text-decoration: none;
	}

	.settings-link:hover {
		background: var(--surface-hover);
		color: var(--text);
	}
</style>
