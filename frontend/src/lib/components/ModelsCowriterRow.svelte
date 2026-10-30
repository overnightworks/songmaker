<script lang="ts">
	import type { Snippet } from 'svelte';
	import { MODELS_SET_BY_AGENT_SERVICE_LABEL, MODELS_TASK_COWRITER_LABEL } from '#lib/constants.ts';
	import ModelsServiceRow from './ModelsServiceRow.svelte';

	interface Props {
		advanced: Snippet;
	}

	let { advanced }: Props = $props();
</script>

<ModelsServiceRow
	task={MODELS_TASK_COWRITER_LABEL}
	provider={MODELS_SET_BY_AGENT_SERVICE_LABEL}
	route="Agent service"
	model={MODELS_SET_BY_AGENT_SERVICE_LABEL}
	{advanced}
/>
