<script lang="ts">
	import { page } from '$app/state';
	import {
		fetchSharedCollection,
		sharedCollectionFailure,
		type SharedCollectionFailure
	} from '#lib/api/shared.ts';
	import { pageText } from '#lib/utils/page-words.ts';
	import SharedCollection from '#lib/components/share/SharedCollection.svelte';
	import {
		fromSharedGeneration,
		type SharedGenerationPayload
	} from '#lib/share/sharedCollection.ts';

	let data: SharedGenerationPayload | null = $state(null);
	let errorKind: SharedCollectionFailure | null = $state(null);
	let loading = $state(true);

	const slug = $derived(page.params.slug ?? '');
	const view = $derived(data ? fromSharedGeneration(data) : null);

	$effect(() => {
		if (slug) void fetchData(slug);
	});

	async function fetchData(s: string): Promise<void> {
		loading = true;
		errorKind = null;
		try {
			data = await fetchSharedCollection('take', s);
		} catch (err) {
			errorKind = sharedCollectionFailure(err);
		} finally {
			loading = false;
		}
	}
</script>

<svelte:head>
	<title
		>{data
			? pageText('shareTakePage.documentTitle', {
					number: String(data.generation_number),
					title: data.title,
					app: pageText('app.name')
				})
			: pageText('shareTakePage.fallbackTitle', { app: pageText('app.name') })}</title
	>
</svelte:head>

<SharedCollection
	{loading}
	{errorKind}
	resource="take"
	onretry={() => fetchData(slug)}
	{view}
	fetchStream={null}
/>
