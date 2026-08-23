<script lang="ts">
	import { page } from '$app/state';
	import { fetchSharedAlbumStream } from '$lib/api/queue-streams';
	import { APP_NAME } from '$lib/constants';
	import SharedCollection from '$lib/components/share/SharedCollection.svelte';
	import { fromSharedAlbum, type SharedAlbumPayload } from '$lib/share/sharedCollection';

	let album: SharedAlbumPayload | null = $state(null);
	let errorKind: 'missing' | 'error' | null = $state(null);
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
			const resp = await fetch(`/shared/${s}`);
			if (!resp.ok) {
				errorKind = resp.status === 404 ? 'missing' : 'error';
				return;
			}
			album = (await resp.json()) as SharedAlbumPayload;
		} catch {
			errorKind = 'error';
		} finally {
			loading = false;
		}
	}
</script>

<svelte:head>
	<title>{album ? `${album.title} — ${album.artist}` : 'Shared Album'} | {APP_NAME}</title>
</svelte:head>

<SharedCollection
	{loading}
	{errorKind}
	resource="album"
	onretry={() => fetchAlbum(slug)}
	{view}
	fetchStream={() => fetchSharedAlbumStream(slug)}
/>
