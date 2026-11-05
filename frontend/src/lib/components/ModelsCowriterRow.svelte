<script lang="ts">
	import type { Snippet } from 'svelte';
	import {
		MODELS_ROUTE_GATEWAY_LABEL,
		MODELS_SET_BY_AGENT_FILE_LABEL,
		MODELS_TASK_COWRITER_LABEL
	} from '#lib/constants/models.ts';
	import ModelsServiceRow from './ModelsServiceRow.svelte';

	interface Props {
		advanced: Snippet;
	}

	let { advanced }: Props = $props();
</script>

<ModelsServiceRow
	task={MODELS_TASK_COWRITER_LABEL}
	provider={MODELS_SET_BY_AGENT_FILE_LABEL}
	route={MODELS_ROUTE_GATEWAY_LABEL}
	model={MODELS_SET_BY_AGENT_FILE_LABEL}
	{advanced}
/>
