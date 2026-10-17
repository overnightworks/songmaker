<script module lang="ts">
	import type { AlbumItem, PlaylistItem, SongItem } from '$lib/api/types';
	import { HOME_PAGE_LABEL, RAIL_SETTINGS_LABEL } from '$lib/constants';
	import {
		albumRoutePath,
		HOME_ROUTE_PATH,
		isPlaylistRoutePath,
		LIBRARY_ROUTE_PATH,
		libraryRouteShape,
		playlistRoutePath,
		PLAYLISTS_ROUTE_PATH,
		songRoutePath
	} from '$lib/routes/addresses';
	import type { PageList } from '$lib/stores/navigation';
	import { visibleRailSearchPages } from '$lib/stores/railSearch';

	export const SEARCH_OPEN_LABEL = 'Search';
	export const SEARCH_SHEET_LABEL = 'Search';
	export const SEARCH_CLOSE_LABEL = 'Close search';

	const LIBRARY_HREF: PageList = LIBRARY_ROUTE_PATH;
	const PLAYLISTS_HREF: PageList = PLAYLISTS_ROUTE_PATH;
	const SETTINGS_HREF: PageList = '/settings';
	// Home and the lists the app opens on, which carry the brand and the account
	// circle instead of ‹ wherever they were opened from.
	const PLACE_LISTS: ReadonlySet<string> = new Set([HOME_ROUTE_PATH, LIBRARY_HREF, PLAYLISTS_HREF]);
	const ALBUM_NAME = 'Album';
	const PLAYLIST_NAME = 'Playlist';
	const SONG_NAME = 'Song';
	const PREVIOUS_PAGE_NAME = 'Previous page';

	export function backLabel(pageName: string): string {
		return `Back to ${pageName}`;
	}

	interface LibraryTitles {
		readonly albums: readonly AlbumItem[];
		readonly playlists: readonly PlaylistItem[];
		readonly songs: readonly SongItem[];
	}

	// The list a page belongs to, which its ‹ opens when no page of the tab's
	// own lies below it (#1354 rule 25): a Settings section belongs to the
	// Settings list, a playlist to the Playlists page, every other page to the
	// Library.
	export function listOfPage(pathname: string): PageList {
		if (pathname.startsWith(`${SETTINGS_HREF}/`)) return SETTINGS_HREF;
		return isPlaylistRoutePath(pathname) ? PLAYLISTS_HREF : LIBRARY_HREF;
	}

	// What ‹ calls the page it goes back to: an app page by the name the app
	// gives it, an album, playlist or song by its title, or by its kind while
	// the library has not loaded it.
	export function pageName(pathname: string, titles: LibraryTitles): string {
		if (pathname === HOME_ROUTE_PATH) return HOME_PAGE_LABEL;
		if (pathname === SETTINGS_HREF) return RAIL_SETTINGS_LABEL;
		const appPage = visibleRailSearchPages(true).find((page) => page.href === pathname);
		if (appPage) return appPage.label;
		switch (libraryRouteShape(pathname)) {
			case 'album':
				return (
					titles.albums.find((album) => albumRoutePath(album.id) === pathname)?.title ?? ALBUM_NAME
				);
			case 'playlist':
				return (
					titles.playlists.find((playlist) => playlistRoutePath(playlist.slug) === pathname)
						?.title ?? PLAYLIST_NAME
				);
			case 'album-song':
			case 'album-song-take':
				return titles.songs.find((song) => isSongAddress(pathname, song))?.title ?? SONG_NAME;
			default:
				return PREVIOUS_PAGE_NAME;
		}
	}

	function isSongAddress(pathname: string, song: SongItem): boolean {
		const songPath = songRoutePath(song.album_id, song.slug);
		return pathname === songPath || pathname.startsWith(`${songPath}/`);
	}
</script>

<script lang="ts">
	import { page } from '$app/state';
	import { APP_NAME, RAIL_DRAWER_OPEN_LABEL, SONG_TITLE_LABEL } from '$lib/constants';
	import { pageBelowStandingPage, stepBackOr } from '$lib/history/historyController';
	import { standingPathname } from '$lib/routes/standingAddress';
	import { historyLayerState } from '$lib/stores/layers';
	import { inertWhileAddressOverlay } from '$lib/stores/libraryAddressOverlay';
	import { albumList, songList } from '$lib/stores/libraryData';
	import { openHome, openListOverPage } from '$lib/stores/navigation';
	import { playlistList } from '$lib/stores/playlists';
	import { phoneAppBar, sidebarOpen, toggleSidebar } from '$lib/stores/ui';
	import { handleFocusTrapKeydown } from '$lib/utils/focus-trap';
	import AccountMenu from './AccountMenu.svelte';
	import EditableTitle from './EditableTitle.svelte';
	import ShareButton from './ShareButton.svelte';
	import SongMenu from './editor/SongMenu.svelte';
	import RailSearch from './shell/RailSearch.svelte';

	let { username, onlogout }: { username: string; onlogout: () => void } = $props();

	let titleEditor: { startEdit: () => void } | undefined = $state();
	let sheet: HTMLDivElement | undefined = $state();

	const searchSheet = historyLayerState('search-sheet', false);

	interface StandingPage {
		readonly pathname: string;
		readonly below: string | null;
	}

	// The bar reads again where history stands, and what lies below it, whenever
	// `page.state` changes.
	function standingPage(stateOfStandingEntry: unknown): StandingPage {
		return {
			pathname: standingPathname(stateOfStandingEntry),
			below: pageBelowStandingPage()
		};
	}

	const standing = $derived(standingPage(page.state));
	const backTargetName = $derived.by((): string | null => {
		if (PLACE_LISTS.has(standing.pathname)) return null;
		const target =
			standing.below === null ? listOfPage(standing.pathname) : new URL(standing.below).pathname;
		return pageName(target, { albums: $albumList, playlists: $playlistList, songs: $songList });
	});

	// ‹ is the page's own Back: the history controller steps back onto the page
	// below, or has the page's list written over the page, by the same question
	// that names ‹ above. The song, the one page whose draft could be lost on
	// the way, carries its own bar instead of ‹.
	function goBack(): void {
		void stepBackOr(() => openListOverPage(listOfPage(location.pathname)));
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
	{:else if backTargetName !== null}
		<button
			type="button"
			class="back"
			data-hitbox="frequent"
			aria-label={backLabel(backTargetName)}
			onclick={goBack}
		>
			<span class="back-chevron">{@render backChevron()}</span>
			<span class="back-name">{backTargetName}</span>
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

	.drawer-trigger,
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
