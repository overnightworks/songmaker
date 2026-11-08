<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path, and the URL is already a resolved library address built by albumRoutePath */
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { albumRoutePath, LIBRARY_ROUTE_ID } from '#lib/routes/addresses.ts';
	import { createAddressLoad } from '#lib/stores/addressLoad.svelte.ts';
	import { openSongAddress } from '#lib/stores/libraryContext.ts';

	const RESOLVING_LABEL = 'Loading song...';
	const UNKNOWN_ALBUM_HEADING = 'No such album';
	const UNKNOWN_ALBUM_MESSAGE = 'This address does not name an album in your library.';
	const UNKNOWN_SONG_HEADING = 'No such song';
	const UNKNOWN_SONG_MESSAGE = 'This address does not name a song in this album.';
	const UNREACHABLE_SONG_MESSAGE = 'This song could not be loaded.';
	const BACK_TO_LIBRARY_LABEL = 'Back to the library';
	const BACK_TO_ALBUM_LABEL = 'Back to the album';
	const RETRY_LABEL = 'Try again';

	const albumSlug = $derived(page.params.slug ?? '');
	const songSlug = $derived(page.params.song ?? '');
	const generationId = $derived(page.url.searchParams.get('gen'));

	const address = createAddressLoad<'unknown-song' | 'unknown-album'>({
		load: () => openSongAddress(albumSlug, songSlug, generationId),
		fallbackMessage: UNREACHABLE_SONG_MESSAGE
	});
</script>

{#if address.state === 'unknown-song'}
	<div class="address-overlay" role="alert">
		<h1>{UNKNOWN_SONG_HEADING}</h1>
		<p>{UNKNOWN_SONG_MESSAGE}</p>
		<a class="address-action" href={albumRoutePath(albumSlug)}>{BACK_TO_ALBUM_LABEL}</a>
	</div>
{:else if address.state === 'unknown-album'}
	<div class="address-overlay" role="alert">
		<h1>{UNKNOWN_ALBUM_HEADING}</h1>
		<p>{UNKNOWN_ALBUM_MESSAGE}</p>
		<a class="address-action" href={resolve(LIBRARY_ROUTE_ID)}>{BACK_TO_LIBRARY_LABEL}</a>
	</div>
{:else if address.state === 'unreachable' && !address.pressing}
	<div class="address-overlay" role="alert">
		<p>{address.failure ?? UNREACHABLE_SONG_MESSAGE}</p>
		<button class="address-action" type="button" onclick={address.tryAgain}>{RETRY_LABEL}</button>
	</div>
{:else if address.state === 'resolving' || address.pressing}
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
		border-color: var(--accent);
		color: var(--accent);
	}
</style>
