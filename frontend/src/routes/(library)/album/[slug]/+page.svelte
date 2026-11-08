<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { LIBRARY_ROUTE_ID } from '#lib/routes/addresses.ts';
	import { createAddressLoad } from '#lib/stores/addressLoad.svelte.ts';
	import { openAlbumAddress } from '#lib/stores/libraryContext.ts';

	const RESOLVING_LABEL = 'Loading album...';
	const UNKNOWN_ALBUM_HEADING = 'No such album';
	const UNKNOWN_ALBUM_MESSAGE = 'This address does not name an album in your library.';
	const UNREACHABLE_ALBUM_MESSAGE = 'This album could not be loaded.';
	const BACK_TO_LIBRARY_LABEL = 'Back to the library';
	const RETRY_LABEL = 'Try again';

	const slug = $derived(page.params.slug ?? '');

	const address = createAddressLoad<'unknown'>({
		load: () => openAlbumAddress(slug),
		fallbackMessage: UNREACHABLE_ALBUM_MESSAGE
	});
</script>

{#if address.state === 'unknown'}
	<div class="address-overlay" role="alert">
		<h1>{UNKNOWN_ALBUM_HEADING}</h1>
		<p>{UNKNOWN_ALBUM_MESSAGE}</p>
		<a class="address-action" href={resolve(LIBRARY_ROUTE_ID)}>{BACK_TO_LIBRARY_LABEL}</a>
	</div>
{:else if address.state === 'unreachable' && !address.pressing}
	<div class="address-overlay" role="alert">
		<p>{address.failure ?? UNREACHABLE_ALBUM_MESSAGE}</p>
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
