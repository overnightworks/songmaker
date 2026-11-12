<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { LIBRARY_ROUTE_ID } from '#lib/routes/addresses.ts';
	import { createAddressLoad } from '#lib/stores/addressLoad.svelte.ts';
	import { openPlaylistAddress } from '#lib/stores/libraryContext.ts';
	import AddressOverlay from '#lib/components/AddressOverlay.svelte';
	import { pageText } from '#lib/utils/page-words.ts';

	const slug = $derived(page.params.slug ?? '');

	const address = createAddressLoad<'unknown'>({
		load: () => openPlaylistAddress(slug),
		fallbackMessage: pageText('addressPage.playlistUnreachable')
	});
</script>

{#if address.state === 'unknown'}
	<AddressOverlay
		kind="unknown"
		head={pageText('addressPage.noSuchPlaylist')}
		explanation={pageText('addressPage.playlistUnknown')}
		backLabel={pageText('addressPage.backToLibrary')}
		backHref={resolve(LIBRARY_ROUTE_ID)}
	/>
{:else if address.state === 'unreachable' && !address.pressing}
	<AddressOverlay
		kind="unreachable"
		message={address.failure ?? pageText('addressPage.playlistUnreachable')}
		retryLabel={pageText('addressPage.tryAgain')}
		onRetry={address.tryAgain}
	/>
{:else if address.state === 'resolving' || address.pressing}
	<AddressOverlay kind="loading" message={pageText('addressPage.loadingPlaylist')} />
{/if}
