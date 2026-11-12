<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { albumRoutePath, LIBRARY_ROUTE_ID } from '#lib/routes/addresses.ts';
	import { createAddressLoad } from '#lib/stores/addressLoad.svelte.ts';
	import { openSongAddress } from '#lib/stores/libraryContext.ts';
	import AddressOverlay from '#lib/components/AddressOverlay.svelte';
	import { pageText } from '#lib/utils/page-words.ts';

	const albumSlug = $derived(page.params.slug ?? '');
	const songSlug = $derived(page.params.song ?? '');
	const generationId = $derived(page.url.searchParams.get('gen'));

	const address = createAddressLoad<'unknown-song' | 'unknown-album'>({
		load: () => openSongAddress(albumSlug, songSlug, generationId),
		fallbackMessage: pageText('addressPage.songUnreachable')
	});
</script>

{#if address.state === 'unknown-song'}
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
		message={address.failure ?? pageText('addressPage.songUnreachable')}
		retryLabel={pageText('addressPage.tryAgain')}
		onRetry={address.tryAgain}
	/>
{:else if address.state === 'resolving' || address.pressing}
	<AddressOverlay kind="loading" message={pageText('addressPage.loadingSong')} />
{/if}
