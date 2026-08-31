<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path, and the URL is already a resolved library address built by albumRoutePath */
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { albumRoutePath, openSongAddress } from '$lib/stores/libraryContext';
	// A song address is a third entrance to the one library workspace (issue
	// #275) — `/`, `/album/<slug>` and this one all mount it. The component is
	// shared so a route swap between them neither rebuilds the workspace nor
	// re-runs its bootstrap.
	import LibraryWorkspace from '$lib/components/LibraryWorkspace.svelte';

	type AddressState = 'resolving' | 'open' | 'unknown-song' | 'unknown-album' | 'unreachable';

	const RESOLVING_LABEL = 'Loading song...';
	const UNKNOWN_ALBUM_HEADING = 'No such album';
	const UNKNOWN_ALBUM_MESSAGE = 'This address does not name an album in your library.';
	const UNKNOWN_SONG_HEADING = 'No such song';
	const UNKNOWN_SONG_MESSAGE = 'This address does not name a song in this album.';
	const UNREACHABLE_SONG_MESSAGE = 'This song could not be loaded.';
	const BACK_TO_LIBRARY_LABEL = 'Back to the library';
	const BACK_TO_ALBUM_LABEL = 'Back to the album';
	const RETRY_LABEL = 'Try again';

	let addressState = $state<AddressState>('resolving');
	let failure = $state<string | null>(null);
	let openRequests = 0;

	const albumSlug = $derived(page.params.slug ?? '');
	const songSlug = $derived(page.params.song ?? '');
	const generationId = $derived(page.url.searchParams.get('gen'));

	$effect(() => {
		void openAddress(albumSlug, songSlug, generationId);
	});

	async function openAddress(albumId: string, slug: string, genId: string | null): Promise<void> {
		const request = ++openRequests;
		addressState = 'resolving';
		failure = null;
		try {
			const address = await openSongAddress(albumId, slug, genId);
			if (request !== openRequests) return;
			addressState = address === 'found' ? 'open' : address;
		} catch (err) {
			if (request !== openRequests) return;
			failure = err instanceof Error ? err.message : UNREACHABLE_SONG_MESSAGE;
			addressState = 'unreachable';
		}
	}
</script>

{#if addressState === 'open'}
	<LibraryWorkspace />
{:else if addressState === 'unknown-song'}
	<div class="address-state" role="alert">
		<h1>{UNKNOWN_SONG_HEADING}</h1>
		<p>{UNKNOWN_SONG_MESSAGE}</p>
		<a class="address-action" href={albumRoutePath(albumSlug)}>{BACK_TO_ALBUM_LABEL}</a>
	</div>
{:else if addressState === 'unknown-album'}
	<div class="address-state" role="alert">
		<h1>{UNKNOWN_ALBUM_HEADING}</h1>
		<p>{UNKNOWN_ALBUM_MESSAGE}</p>
		<a class="address-action" href={resolve('/')}>{BACK_TO_LIBRARY_LABEL}</a>
	</div>
{:else if addressState === 'unreachable'}
	<div class="address-state" role="alert">
		<p>{failure ?? UNREACHABLE_SONG_MESSAGE}</p>
		<button
			class="address-action"
			type="button"
			onclick={() => openAddress(albumSlug, songSlug, generationId)}>{RETRY_LABEL}</button
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
