<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { openAlbumAddress } from '$lib/stores/libraryContext';
	import { libraryAddressOverlayActive } from '$lib/stores/libraryAddressOverlay';

	type AddressState = 'resolving' | 'open' | 'unknown' | 'unreachable';

	const RESOLVING_LABEL = 'Loading album...';
	const UNKNOWN_ALBUM_HEADING = 'No such album';
	const UNKNOWN_ALBUM_MESSAGE = 'This address does not name an album in your library.';
	const UNREACHABLE_ALBUM_MESSAGE = 'This album could not be loaded.';
	const BACK_TO_LIBRARY_LABEL = 'Back to the library';
	const RETRY_LABEL = 'Try again';

	let addressState = $state<AddressState>('resolving');
	let failure = $state<string | null>(null);
	let openRequests = 0;

	const slug = $derived(page.params.slug ?? '');

	$effect(() => {
		void openAddress(slug);
	});

	// The overlay above hides a stale workspace visually (`position: absolute`)
	// but not from the accessibility tree or the tab order -- `inert` on the
	// workspace wrapper is what actually does that, and it lives one level up
	// in `(library)/+layout.svelte`, so this bridges the address state across
	// with a store. Active whenever this page isn't showing the open workspace,
	// including the (route-change-only) unmount below: leaving this page for
	// `/` or another address must not leave the workspace inert behind it.
	$effect(() => {
		libraryAddressOverlayActive.set(addressState !== 'open');
		return () => libraryAddressOverlayActive.set(false);
	});

	async function openAddress(albumId: string): Promise<void> {
		const request = ++openRequests;
		addressState = 'resolving';
		failure = null;
		try {
			const address = await openAlbumAddress(albumId);
			if (request !== openRequests) return;
			addressState = address === 'found' ? 'open' : 'unknown';
		} catch (err) {
			if (request !== openRequests) return;
			failure = err instanceof Error ? err.message : UNREACHABLE_ALBUM_MESSAGE;
			addressState = 'unreachable';
		}
	}
</script>

{#if addressState === 'unknown'}
	<div class="address-overlay" role="alert">
		<h1>{UNKNOWN_ALBUM_HEADING}</h1>
		<p>{UNKNOWN_ALBUM_MESSAGE}</p>
		<a class="address-action" href={resolve('/')}>{BACK_TO_LIBRARY_LABEL}</a>
	</div>
{:else if addressState === 'unreachable'}
	<div class="address-overlay" role="alert">
		<p>{failure ?? UNREACHABLE_ALBUM_MESSAGE}</p>
		<button class="address-action" type="button" onclick={() => openAddress(slug)}
			>{RETRY_LABEL}</button
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
