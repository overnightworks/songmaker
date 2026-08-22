<script lang="ts">
	import { page } from '$app/state';
	import { fetchSharedPlaylistStream } from '$lib/api/client';
	import { APP_NAME } from '$lib/constants';
	import SharedCollection from '$lib/components/share/SharedCollection.svelte';
	import { fromSharedPlaylist, type SharedPlaylistPayload } from '$lib/share/sharedCollection';

	let playlist: SharedPlaylistPayload | null = $state(null);
	let errorKind: 'missing' | 'error' | null = $state(null);
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
			const resp = await fetch(`/shared/playlist/${s}`);
			if (!resp.ok) {
				errorKind = resp.status === 404 ? 'missing' : 'error';
				return;
			}
			playlist = (await resp.json()) as SharedPlaylistPayload;
		} catch {
			errorKind = 'error';
		} finally {
			loading = false;
		}
	}
</script>

<svelte:head>
	<title>{playlist ? playlist.title : 'Shared Playlist'} | {APP_NAME}</title>
</svelte:head>

<SharedCollection
	{loading}
	{errorKind}
	resource="playlist"
	onretry={() => fetchData(slug)}
	{view}
	fetchStream={() => fetchSharedPlaylistStream(slug)}
/>
