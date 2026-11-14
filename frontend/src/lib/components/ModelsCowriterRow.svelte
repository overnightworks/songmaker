<script lang="ts">
	import type { Snippet } from 'svelte';
	import { pageText } from '#lib/utils/page-words.ts';
	import ModelsServiceRow from './ModelsServiceRow.svelte';

	interface Props {
		advanced: Snippet;
	}

	let { advanced }: Props = $props();
</script>

<ModelsServiceRow
	task={pageText('modelsTable.taskCowriter')}
	provider={pageText('modelsTable.setByAgentFile')}
	route={pageText('modelsTable.routeGateway')}
	model={pageText('modelsTable.setByAgentFile')}
	{advanced}
/>
