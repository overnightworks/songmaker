<script lang="ts">
	import { PHONE_TABS, PHONE_TABS_NAV_LABEL } from '#lib/constants/phone-tabs.ts';
	import { libraryRouteShape } from '#lib/routes/addresses.ts';
	import type { Place } from '#lib/stores/libraryContext.ts';
	import Icon from '../Icon.svelte';

	let { pathname, onSelect }: { pathname: string; onSelect: (place: Place) => void } = $props();

	function placeForPathname(pathname: string): Place | null {
		switch (libraryRouteShape(pathname)) {
			case 'home':
				return 'home';
			case 'library':
			case 'album':
			case 'album-song':
			case 'album-song-take':
				return 'library';
			case 'playlists':
			case 'playlist':
				return 'playlists';
			default:
				return null;
		}
	}

	const currentPlace = $derived(placeForPathname(pathname));
</script>

<nav class="phone-tabs" aria-label={PHONE_TABS_NAV_LABEL}>
	{#each PHONE_TABS as tab (tab.place)}
		<button
			type="button"
			data-hitbox="frequent"
			aria-current={currentPlace === tab.place ? 'page' : undefined}
			onclick={() => onSelect(tab.place)}
		>
			<span aria-hidden="true"><Icon name={tab.icon} size={22} /></span>
			<span>{tab.label}</span>
		</button>
	{/each}
</nav>

<style>
	.phone-tabs {
		position: fixed;
		inset: auto 0 0;
		z-index: 100;
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		flex: none;
		height: var(--phone-tabs-room);
		padding-bottom: env(safe-area-inset-bottom, 0px);
		background: var(--header-bg);
	}

	button {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 4px;
		border: none;
		border-radius: 0;
		background: transparent;
		color: var(--text-muted);
		font: inherit;
		font-family: var(--font-display);
		font-size: 0.72rem;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		cursor: pointer;
	}

	button[aria-current='page'] {
		color: var(--text);
		font-weight: 700;
	}

	button[aria-current='page'] span:first-child {
		color: var(--accent);
	}

	button:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: -2px;
	}
</style>
