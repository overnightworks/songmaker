<script lang="ts">
	import { page } from '$app/state';
	import {
		fetchSharedCollection,
		sharedCollectionFailure,
		type SharedCollectionFailure
	} from '#lib/api/shared.ts';
	import { APP_NAME } from '#lib/constants.ts';
	import SharedCollection from '#lib/components/share/SharedCollection.svelte';
	import { fromSharedSong, type SharedSongPayload } from '#lib/share/sharedCollection.ts';

	let data: SharedSongPayload | null = $state(null);
	let errorKind: SharedCollectionFailure | null = $state(null);
	let loading = $state(true);

	const slug = $derived(page.params.slug ?? '');
	const view = $derived(data ? fromSharedSong(data) : null);

	$effect(() => {
		if (slug) void fetchData(slug);
	});

	async function fetchData(s: string): Promise<void> {
		loading = true;
		errorKind = null;
		try {
			data = await fetchSharedCollection('song', s);
		} catch (err) {
			errorKind = sharedCollectionFailure(err);
		} finally {
			loading = false;
		}
	}
</script>

<svelte:head>
	<title>{data ? `${data.title} — ${data.artist}` : 'Shared song'} | {APP_NAME}</title>
</svelte:head>

<SharedCollection
	{loading}
	{errorKind}
	resource="song"
	onretry={() => fetchData(slug)}
	{view}
	fetchStream={null}
/>
