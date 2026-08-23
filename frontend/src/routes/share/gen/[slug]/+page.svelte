<script lang="ts">
	import { page } from '$app/state';
	import { APP_NAME } from '$lib/constants';
	import SharedCollection from '$lib/components/share/SharedCollection.svelte';
	import { fromSharedGeneration, type SharedGenerationPayload } from '$lib/share/sharedCollection';

	let data: SharedGenerationPayload | null = $state(null);
	let errorKind: 'missing' | 'error' | null = $state(null);
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
			const resp = await fetch(`/shared/gen/${s}`);
			if (!resp.ok) {
				errorKind = resp.status === 404 ? 'missing' : 'error';
				return;
			}
			data = (await resp.json()) as SharedGenerationPayload;
		} catch {
			errorKind = 'error';
		} finally {
			loading = false;
		}
	}
</script>

<svelte:head>
	<title
		>{data ? `Take ${data.generation_number} — ${data.title}` : 'Shared take'} | {APP_NAME}</title
	>
</svelte:head>

<SharedCollection
	{loading}
	{errorKind}
	resource="generation"
	onretry={() => fetchData(slug)}
	{view}
	fetchStream={null}
/>
