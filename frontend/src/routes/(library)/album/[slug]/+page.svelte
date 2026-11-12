<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { LIBRARY_ROUTE_ID } from '#lib/routes/addresses.ts';
	import { createAddressLoad } from '#lib/stores/addressLoad.svelte.ts';
	import { openAlbumAddress } from '#lib/stores/libraryContext.ts';
	import AddressOverlay from '#lib/components/AddressOverlay.svelte';
	import { pageText } from '#lib/utils/page-words.ts';

	const slug = $derived(page.params.slug ?? '');

	const address = createAddressLoad<'unknown'>({
		load: () => openAlbumAddress(slug),
		fallbackMessage: pageText('addressPage.albumUnreachable')
	});
</script>

{#if address.state === 'unknown'}
	<AddressOverlay
		kind="unknown"
		head={pageText('addressPage.noSuchAlbum')}
		explanation={pageText('addressPage.albumUnknown')}
		backLabel={pageText('addressPage.backToLibrary')}
		backHref={resolve(LIBRARY_ROUTE_ID)}
	/>
{:else if address.state === 'unreachable' && !address.pressing}
	<AddressOverlay
		kind="unreachable"
		message={address.failure ?? pageText('addressPage.albumUnreachable')}
		retryLabel={pageText('addressPage.tryAgain')}
		onRetry={address.tryAgain}
	/>
{:else if address.state === 'resolving' || address.pressing}
	<AddressOverlay kind="loading" message={pageText('addressPage.loadingAlbum')} />
{/if}
