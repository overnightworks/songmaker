<script lang="ts">
	import { page } from '$app/state';
	import {
		fetchSharedCollection,
		fetchSharedStream,
		sharedCollectionFailure,
		type SharedCollectionFailure
	} from '#lib/api/shared.ts';
	import { APP_NAME } from '#lib/constants.ts';
	import SharedCollection from '#lib/components/share/SharedCollection.svelte';
	import { fromSharedAlbum, type SharedAlbumPayload } from '#lib/share/sharedCollection.ts';

	let album: SharedAlbumPayload | null = $state(null);
	let errorKind: SharedCollectionFailure | null = $state(null);
	let loading = $state(true);

	const slug = $derived(page.params.slug ?? '');
	const view = $derived(album ? fromSharedAlbum(album) : null);

	$effect(() => {
		if (slug) void fetchAlbum(slug);
	});

	async function fetchAlbum(s: string): Promise<void> {
		loading = true;
		errorKind = null;
		try {
			album = await fetchSharedCollection('album', s);
		} catch (err) {
			errorKind = sharedCollectionFailure(err);
		} finally {
			loading = false;
		}
	}
</script>

<svelte:head>
	<title>{album ? `${album.title} — ${album.artist}` : 'Shared album'} | {APP_NAME}</title>
</svelte:head>

<SharedCollection
	{loading}
	{errorKind}
	resource="album"
	onretry={() => fetchAlbum(slug)}
	{view}
	fetchStream={() => fetchSharedStream('album', slug)}
/>
