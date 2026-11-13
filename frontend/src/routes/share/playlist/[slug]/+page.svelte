<script lang="ts">
	import { page } from '$app/state';
	import {
		fetchSharedCollection,
		fetchSharedStream,
		sharedCollectionFailure,
		type SharedCollectionFailure
	} from '#lib/api/shared.ts';
	import { pageText } from '#lib/utils/page-words.ts';
	import { APP_NAME } from '#lib/constants/app.ts';
	import SharedCollection from '#lib/components/share/SharedCollection.svelte';
	import { fromSharedPlaylist, type SharedPlaylistPayload } from '#lib/share/sharedCollection.ts';

	let playlist: SharedPlaylistPayload | null = $state(null);
	let errorKind: SharedCollectionFailure | null = $state(null);
	let loading = $state(true);

	const slug = $derived(page.params.slug ?? '');
	const view = $derived(playlist ? fromSharedPlaylist(playlist) : null);

	$effect(() => {
		if (slug) void fetchData(slug);
	});

	async function fetchData(s: string): Promise<void> {
		loading = true;
		errorKind = null;
		try {
			playlist = await fetchSharedCollection('playlist', s);
		} catch (err) {
			errorKind = sharedCollectionFailure(err);
		} finally {
			loading = false;
		}
	}
</script>

<svelte:head>
	<title
		>{playlist
			? pageText('sharePlaylistPage.documentTitle', { title: playlist.title, app: APP_NAME })
			: pageText('sharePlaylistPage.fallbackTitle', { app: APP_NAME })}</title
	>
</svelte:head>

<SharedCollection
	{loading}
	{errorKind}
	resource="playlist"
	onretry={() => fetchData(slug)}
	{view}
	fetchStream={() => fetchSharedStream('playlist', slug)}
/>
