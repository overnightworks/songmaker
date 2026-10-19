<script lang="ts">
	import LegalContent from '$lib/components/LegalContent.svelte';
	import { APP_NAME } from '$lib/constants';
	import { SIGN_IN_PATH } from '$lib/api/fetch';
	import { stepBackOrGoTo } from '$lib/history/historyController';

	function goBack(): void {
		void stepBackOrGoTo(SIGN_IN_PATH);
	}
</script>

<svelte:head>
	<title>Datenschutz | {APP_NAME}</title>
</svelte:head>

<div class="legal-standalone">
	<LegalContent initialSection="datenschutz" onback={goBack} />
</div>

<style>
	.legal-standalone {
		height: 100dvh;
		overflow-y: auto;
	}
</style>
