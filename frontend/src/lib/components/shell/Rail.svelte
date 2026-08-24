<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { albumList } from '$lib/stores/libraryData';
	import { openLibraryWall } from '$lib/stores/navigation';
	import { libraryBrowse } from '$lib/stores/librarySearch';
	import { ensurePlaylistsLoaded, playlistList, playlistLoad } from '$lib/stores/playlists';
	import {
		APP_NAME,
		RAIL_LIBRARY_LABEL,
		RAIL_SETTINGS_LABEL,
		RAIL_SUMMARY_LOADING
	} from '$lib/constants';
	import { librarySummaryLabel } from '$lib/utils/format';
	import RailContext from './RailContext.svelte';
	import UserRow from './UserRow.svelte';

	let { username, onlogout }: { username: string; onlogout: () => void } = $props();

	const albumCount = $derived($albumList.length);
	const playlistCount = $derived($playlistList.length);

	// Latches true the first time both lists have settled (ready or error) and
	// never resets, so a later pagination/sort reload of either list doesn't
	// blank the summary again — only the very first mount waits.
	let summaryReady = $state(false);
	$effect(() => {
		const albumsSettled = $libraryBrowse.status === 'ready' || $libraryBrowse.status === 'error';
		const playlistsSettled = $playlistLoad.status === 'ready' || $playlistLoad.status === 'error';
		if (albumsSettled && playlistsSettled) summaryReady = true;
	});

	const summary = $derived(
		summaryReady ? librarySummaryLabel(albumCount, playlistCount) : RAIL_SUMMARY_LOADING
	);

	$effect(() => {
		void ensurePlaylistsLoaded();
	});
</script>

<nav class="rail" aria-label="Primary">
	<div class="rail-top">
		<button
			type="button"
			class="brand"
			onclick={() => openLibraryWall()}
			aria-label={RAIL_LIBRARY_LABEL}
			data-text={APP_NAME}>{APP_NAME}</button
		>
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
		<span class="library-label">{RAIL_LIBRARY_LABEL}</span>
		<span class="library-summary">{summary}</span>
	</button>

	<div class="rail-divider"></div>

	<div class="rail-context-slot">
		<RailContext />
	</div>

	<div class="rail-bottom">
		<a class="settings-link" href="/settings">{RAIL_SETTINGS_LABEL}</a>
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

	.library-label {
		font-family: var(--font-display);
		font-size: 0.85rem;
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.library-summary {
		margin-left: auto;
		font-size: 0.75rem;
		color: var(--text-subtle);
		white-space: nowrap;
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
