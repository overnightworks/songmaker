<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { openAlbumAddress } from '$lib/stores/libraryContext';
	// An album address is a second entrance to the one library workspace, not
	// a surface of its own; `/` is the other. The component is shared so a
	// route swap between them neither rebuilds the workspace nor re-runs its
	// bootstrap.
	import LibraryWorkspace from '$lib/components/LibraryWorkspace.svelte';

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

{#if addressState === 'open'}
	<LibraryWorkspace />
{:else if addressState === 'unknown'}
	<div class="address-state" role="alert">
		<h1>{UNKNOWN_ALBUM_HEADING}</h1>
		<p>{UNKNOWN_ALBUM_MESSAGE}</p>
		<a class="address-action" href={resolve('/')}>{BACK_TO_LIBRARY_LABEL}</a>
	</div>
{:else if addressState === 'unreachable'}
	<div class="address-state" role="alert">
		<p>{failure ?? UNREACHABLE_ALBUM_MESSAGE}</p>
		<button class="address-action" type="button" onclick={() => openAddress(slug)}
			>{RETRY_LABEL}</button
		>
	</div>
{:else}
	<div class="address-state">{RESOLVING_LABEL}</div>
{/if}

<style>
	.address-state {
		display: flex;
		flex: 1;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 16px;
		padding: 0 24px;
		text-align: center;
		color: var(--text-muted);
	}

	.address-state h1 {
		margin: 0;
		font-family: var(--font-display);
		font-size: 1.4rem;
		color: var(--text);
	}

	.address-state p {
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
