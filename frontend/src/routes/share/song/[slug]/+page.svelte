<script lang="ts">
	import { page } from '$app/state';
	import { APP_NAME } from '$lib/constants';
	import SharedCollection from '$lib/components/share/SharedCollection.svelte';
	import { fromSharedSong, type SharedSongPayload } from '$lib/share/sharedCollection';

	let data: SharedSongPayload | null = $state(null);
	let errorKind: 'missing' | 'error' | null = $state(null);
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
			const resp = await fetch(`/shared/song/${s}`);
			if (!resp.ok) {
				errorKind = resp.status === 404 ? 'missing' : 'error';
				return;
			}
			data = (await resp.json()) as SharedSongPayload;
		} catch {
			errorKind = 'error';
		} finally {
			loading = false;
		}
	}
</script>

<svelte:head>
	<title>{data ? `${data.title} — ${data.artist}` : 'Shared Song'} | {APP_NAME}</title>
</svelte:head>

<SharedCollection
	{loading}
	{errorKind}
	resource="song"
	onretry={() => fetchData(slug)}
	{view}
	fetchStream={null}
/>
