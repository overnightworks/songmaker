<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { albumRoutePath, LIBRARY_ROUTE_ID, songRoutePath } from '#lib/routes/addresses.ts';
	import { createAddressLoad } from '#lib/stores/addressLoad.svelte.ts';
	import { openTakeAddress } from '#lib/stores/libraryContext.ts';
	import AddressOverlay from '#lib/components/AddressOverlay.svelte';
	import { pageText } from '#lib/utils/page-words.ts';

	const albumSlug = $derived(page.params.slug ?? '');
	const songSlug = $derived(page.params.song ?? '');
	const takeNumber = $derived(Number(page.params.n));

	const address = createAddressLoad<'unknown-take' | 'unknown-song' | 'unknown-album'>({
		load: () => openTakeAddress(albumSlug, songSlug, takeNumber),
		fallbackMessage: pageText('addressPage.takeUnreachable')
	});
</script>

{#if address.state === 'unknown-take'}
	<AddressOverlay
		kind="unknown"
		head={pageText('addressPage.noSuchTake')}
		explanation={pageText('addressPage.takeUnknown')}
		backLabel={pageText('addressPage.backToSong')}
		backHref={songRoutePath(albumSlug, songSlug)}
	/>
{:else if address.state === 'unknown-song'}
	<AddressOverlay
		kind="unknown"
		head={pageText('addressPage.noSuchSong')}
		explanation={pageText('addressPage.songUnknown')}
		backLabel={pageText('addressPage.backToAlbum')}
		backHref={albumRoutePath(albumSlug)}
	/>
{:else if address.state === 'unknown-album'}
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
		message={address.failure ?? pageText('addressPage.takeUnreachable')}
		retryLabel={pageText('addressPage.tryAgain')}
		onRetry={address.tryAgain}
	/>
{:else if address.state === 'resolving' || address.pressing}
	<AddressOverlay kind="loading" message={pageText('addressPage.loadingTake')} />
{/if}
