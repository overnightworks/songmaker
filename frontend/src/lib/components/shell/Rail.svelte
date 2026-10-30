<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { setRailCollapsed } from '#lib/contexts/rail-collapsed.ts';
	import { librarySurface, placeShown, type Place } from '#lib/stores/libraryContext.ts';
	import { selectedSongId } from '#lib/stores/player.ts';
	import { page } from '$app/state';
	import { HOME_ROUTE_PATH } from '#lib/routes/addresses.ts';
	import { standingPathname } from '#lib/routes/standingAddress.ts';
	import { followPlainClick, openHome } from '#lib/stores/navigation.ts';
	import { APP_NAME, HOME_PAGE_LABEL, RAIL_NAV_LABEL } from '#lib/constants.ts';
	import { kineticScroll } from '#lib/actions/kineticScroll.ts';
	import Icon from '../Icon.svelte';
	import RailLibraryGroup from './RailLibraryGroup.svelte';
	import RailPlaylistsGroup from './RailPlaylistsGroup.svelte';
	import RailSearch from './RailSearch.svelte';
	import RailSettings from './RailSettings.svelte';
	import { RAIL_ITEM_SELECTOR } from './rail-item-selector';
	import {
		adjustRailWidth,
		railWidth,
		RAIL_MAX_WIDTH_PX,
		RAIL_MIN_WIDTH_PX,
		RAIL_WIDTH_STEP_PX,
		setRailWidth,
		toggleRailCollapsed
	} from '#lib/stores/ui.ts';

	let { collapsed = false }: { collapsed?: boolean } = $props();

	setRailCollapsed(() => collapsed);
	const homePlace: Place = 'home';
	const onHome = $derived(
		placeShown(homePlace, $librarySurface, $selectedSongId, standingPathname(page.state))
	);

	const collapseRailLabel = 'Collapse rail';
	const expandRailLabel = 'Expand rail';
	const resizeRailLabel = 'Resize rail';
	let rail: HTMLElement;
	let resizing = $state(false);

	function resizeFromPointer(clientX: number): void {
		setRailWidth(clientX - rail.getBoundingClientRect().left);
	}

	function startResize(event: PointerEvent): void {
		if (event.button !== 0) return;
		event.preventDefault();
		if (event.currentTarget instanceof HTMLElement) {
			event.currentTarget.focus({ preventScroll: true });
		}
		resizing = true;
		resizeFromPointer(event.clientX);
	}

	function stopResize(): void {
		resizing = false;
	}

	function handleWindowPointerMove(event: PointerEvent): void {
		if (!resizing) return;
		event.preventDefault();
		resizeFromPointer(event.clientX);
	}

	function handleResizeKeydown(event: KeyboardEvent): void {
		if (event.key === 'ArrowLeft') {
			event.preventDefault();
			adjustRailWidth(-RAIL_WIDTH_STEP_PX);
		}
		if (event.key === 'ArrowRight') {
			event.preventDefault();
			adjustRailWidth(RAIL_WIDTH_STEP_PX);
		}
	}

	function resizeHandle(node: HTMLElement): { destroy: () => void } {
		node.addEventListener('pointerdown', startResize);
		node.addEventListener('keydown', handleResizeKeydown);
		return {
			destroy: () => {
				node.removeEventListener('pointerdown', startResize);
				node.removeEventListener('keydown', handleResizeKeydown);
			}
		};
	}
</script>

<svelte:window
	onpointermove={handleWindowPointerMove}
	onpointerup={stopResize}
	onpointercancel={stopResize}
/>

<nav bind:this={rail} class="rail" class:rail-collapsed={collapsed} aria-label={RAIL_NAV_LABEL}>
	<div class="rail-top">
		<button
			type="button"
			class="brand"
			aria-label={collapsed ? APP_NAME : undefined}
			onclick={() => openHome()}
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
		<a
			class="home-link rail-page-link"
			href={HOME_ROUTE_PATH}
			aria-current={onHome ? 'page' : undefined}
			title={collapsed ? HOME_PAGE_LABEL : undefined}
			onclick={(event) => followPlainClick(event, openHome)}
		>
			<span class="home-fold-spacer" aria-hidden="true"></span>
			<span aria-hidden="true"><Icon name={homePlace} size={14} /></span>
			<span class="group-title">{HOME_PAGE_LABEL}</span>
		</a>
		<RailLibraryGroup />
		<RailPlaylistsGroup />
	</div>

	<div class="rail-settings-pin">
		<RailSettings />
	</div>

	<button
		type="button"
		class="rail-collapse"
		aria-label={collapsed ? expandRailLabel : collapseRailLabel}
		title={collapsed ? expandRailLabel : collapseRailLabel}
		onclick={toggleRailCollapsed}
	>
		{collapsed ? '›' : '‹'}
	</button>

	{#if !collapsed}
		<input
			type="range"
			class="rail-resize"
			class:rail-resizing={resizing}
			aria-label={resizeRailLabel}
			min={RAIL_MIN_WIDTH_PX}
			max={RAIL_MAX_WIDTH_PX}
			step={RAIL_WIDTH_STEP_PX}
			value={$railWidth}
			use:resizeHandle
		/>
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

	.home-link {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 8px 16px;
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: 0.85rem;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		text-decoration: none;
	}

	.home-link:hover {
		background: var(--surface-hover);
		color: var(--text);
	}

	.home-link[aria-current='page'] {
		background: var(--surface-hover);
		color: var(--text);
	}

	.home-fold-spacer {
		flex: 0 0 18px;
	}

	.rail-collapsed .home-fold-spacer {
		display: none;
	}

	.rail-collapsed .home-link {
		justify-content: center;
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

	.rail-resize {
		position: absolute;
		top: 0;
		right: -4px;
		bottom: 0;
		z-index: 1;
		width: 8px;
		padding: 0;
		border: 0;
		background: linear-gradient(90deg, transparent 3px, var(--border) 3px 5px, transparent 5px);
		appearance: none;
		cursor: col-resize;
		touch-action: none;
	}

	.rail-resize:hover,
	.rail-resize.rail-resizing,
	.rail-resize:focus-visible {
		background: linear-gradient(90deg, transparent 3px, var(--accent) 3px 5px, transparent 5px);
	}

	.rail-resize:focus-visible {
		outline: none;
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

	.rail-collapsed :global(.fold) {
		display: none;
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
</style>
