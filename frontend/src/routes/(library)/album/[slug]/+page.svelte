<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { LIBRARY_ROUTE_ID } from '#lib/routes/addresses.ts';
	import { createAddressLoad } from '#lib/stores/addressLoad.svelte.ts';
	import { openAlbumAddress } from '#lib/stores/libraryContext.ts';
	import { pageText } from '#lib/utils/page-words.ts';

	const slug = $derived(page.params.slug ?? '');

	const address = createAddressLoad<'unknown'>({
		load: () => openAlbumAddress(slug),
		fallbackMessage: pageText('addressPage.albumUnreachable')
	});
</script>

{#if address.state === 'unknown'}
	<div class="address-overlay" role="alert">
		<h1>{pageText('addressPage.noSuchAlbum')}</h1>
		<p>{pageText('addressPage.albumUnknown')}</p>
		<a class="address-action" href={resolve(LIBRARY_ROUTE_ID)}
			>{pageText('addressPage.backToLibrary')}</a
		>
	</div>
{:else if address.state === 'unreachable' && !address.pressing}
	<div class="address-overlay" role="alert">
		<p>{address.failure ?? pageText('addressPage.albumUnreachable')}</p>
		<button class="address-action" type="button" onclick={address.tryAgain}
			>{pageText('addressPage.tryAgain')}</button
		>
	</div>
{:else if address.state === 'resolving' || address.pressing}
	<div class="address-overlay">{pageText('addressPage.loadingAlbum')}</div>
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
