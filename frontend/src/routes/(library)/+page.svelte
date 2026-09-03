<script lang="ts">
	// The root library address needs no address resolution of its own and
	// renders nothing (issue #276) -- except when it still carries the legacy
	// `?song=<uuid>` (and `?gen=<uuid>`) query a bookmark or a shared link from
	// before S3/S4 (#275/#281) can hold. That form still worked (see the note
	// on the removed `?song=` branch of initNavigation, in navigation.ts), but
	// the address bar kept showing it forever and Back could return to it --
	// S6 (issue #284) redirects it onto its canonical song or take address
	// instead, in place, so a stale bookmark converges to the one address that
	// resource actually has. `resolveLegacySongQueryAddress` (libraryContext.ts)
	// does the id -> slug/number lookup; this only drives the redirect and,
	// while it is in flight or fails, shows the same overlay-over-the-standing-
	// workspace the sibling addresses already use.
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { LEGACY_TAKE_LINK_NOT_FOUND_TOAST } from '$lib/constants';
	import { readLegacySongQuery } from '$lib/routes/addresses';
	import {
		currentLibraryHistoryState,
		isLibraryHistoryState,
		resolveLegacySongQueryAddress
	} from '$lib/stores/libraryContext';
	import { libraryAddressOverlayActive } from '$lib/stores/libraryAddressOverlay';
	import { addToast } from '$lib/stores/toast';

	type AddressState = 'idle' | 'resolving' | 'unknown-song' | 'unreachable';

	const RESOLVING_LABEL = 'Loading song...';
	const UNKNOWN_SONG_HEADING = 'No such song';
	const UNKNOWN_SONG_MESSAGE = 'This address does not name a song in your library.';
	const UNREACHABLE_SONG_MESSAGE = 'This song could not be loaded.';
	const BACK_TO_LIBRARY_LABEL = 'Back to the library';
	const RETRY_LABEL = 'Try again';

	let addressState = $state<AddressState>('idle');
	let failure = $state<string | null>(null);
	let openRequests = 0;

	const legacySongQuery = $derived(readLegacySongQuery(page.url.searchParams));
	const songId = $derived(legacySongQuery.songId);
	const generationId = $derived(legacySongQuery.generationId);

	// A tab that already carries a LibraryHistoryState naming this exact
	// legacy `?song=` entry has `onPopstate` (navigation.ts) apply it
	// instantly from `history.state` on Back/Forward -- this happens whenever
	// a song not yet in `songList` gets its own history entry written in this
	// query form (`libraryHistoryUrl`'s own fallback, still a same-shape write
	// against '/' per `libraryRouteShape`, so it never crosses a route on its
	// own) and the person later returns to it. Re-resolving over the network
	// would be redundant in that case -- `history.state` already carries the
	// answer onPopstate just applied -- so this checks it first and skips
	// straight to idle, with no overlay flash, whenever the entry already
	// names this exact id/generation pair; issue #265's S7 closed this rather
	// than leaving it to self-heal on a redundant fetch.
	$effect(() => {
		if (matchesResolvedHistoryState(songId, generationId)) {
			addressState = 'idle';
			return;
		}
		void redirectLegacyAddress(songId, generationId);
	});

	function matchesResolvedHistoryState(id: string | null, genId: string | null): boolean {
		if (!id) return false;
		const state = currentLibraryHistoryState();
		return isLibraryHistoryState(state) && state.songId === id && state.generationId === genId;
	}

	// Same inert bridge as the sibling addresses (issue #276): the overlay
	// only hides the stale workspace visually, `inert` on the wrapper one
	// level up in `(library)/+layout.svelte` is what removes it from the tab
	// order and the accessibility tree. Idle -- the ordinary root address,
	// carrying no `?song=` -- never activates it; there is nothing stale to
	// hide, and the workspace underneath is this address's own content.
	$effect(() => {
		libraryAddressOverlayActive.set(addressState !== 'idle');
		return () => libraryAddressOverlayActive.set(false);
	});

	async function redirectLegacyAddress(id: string | null, genId: string | null): Promise<void> {
		const request = ++openRequests;
		if (!id) {
			addressState = 'idle';
			return;
		}
		addressState = 'resolving';
		failure = null;
		try {
			const resolved = await resolveLegacySongQueryAddress(id, genId);
			if (request !== openRequests) return;
			if (resolved.kind === 'unknown-song') {
				addressState = 'unknown-song';
				return;
			}
			// eslint-disable-next-line svelte/no-navigation-without-resolve -- static SPA with no base path, and the path is already a resolved library address built by songRoutePath/takeRoutePath
			await goto(resolved.path, { replaceState: true, noScroll: true, keepFocus: true });
			// After the landing, not before: the toast reports the take is gone once
			// the song's own address is already showing, never while the bar still
			// reads the legacy form the person is leaving.
			if (resolved.droppedUnknownTake) addToast(LEGACY_TAKE_LINK_NOT_FOUND_TOAST, 'error');
		} catch (err) {
			if (request !== openRequests) return;
			failure = err instanceof Error ? err.message : UNREACHABLE_SONG_MESSAGE;
			addressState = 'unreachable';
		}
	}
</script>

{#if addressState === 'unknown-song'}
	<div class="address-overlay" role="alert">
		<h1>{UNKNOWN_SONG_HEADING}</h1>
		<p>{UNKNOWN_SONG_MESSAGE}</p>
		<a class="address-action" href={resolve('/')}>{BACK_TO_LIBRARY_LABEL}</a>
	</div>
{:else if addressState === 'unreachable'}
	<div class="address-overlay" role="alert">
		<p>{failure ?? UNREACHABLE_SONG_MESSAGE}</p>
		<button
			class="address-action"
			type="button"
			onclick={() => redirectLegacyAddress(songId, generationId)}>{RETRY_LABEL}</button
		>
	</div>
{:else if addressState === 'resolving'}
	<div class="address-overlay">{RESOLVING_LABEL}</div>
{/if}

<style>
	.address-overlay {
		position: absolute;
		inset: 0;
		z-index: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 16px;
		padding: 0 24px;
		text-align: center;
		color: var(--text-muted);
		background: var(--bg);
	}

	.address-overlay h1 {
		margin: 0;
		font-family: var(--font-display);
		font-size: 1.4rem;
		color: var(--text);
	}

	.address-overlay p {
		margin: 0;
	}

	.address-action {
		padding: 6px 12px;
		background: none;
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text-muted);
		font-size: var(--label-font-size);
		font-family: var(--font-body);
		text-decoration: none;
		cursor: pointer;
	}

	.address-action:hover {
		border-color: var(--primary);
		color: var(--primary);
	}
</style>
