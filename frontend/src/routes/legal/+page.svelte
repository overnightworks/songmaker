<!-- eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path -->
<script lang="ts">
	import LegalContent from '$lib/components/LegalContent.svelte';
	import { APP_NAME } from '$lib/constants';

	function goBack(): void {
		if (window.history.length > 1) {
			window.history.back();
		} else {
			window.location.href = '/login';
		}
	}
</script>

<svelte:head>
	<title>Legal | {APP_NAME}</title>
</svelte:head>

<div class="legal-standalone">
	<LegalContent onback={goBack} />
</div>

<style>
	.legal-standalone {
		height: 100dvh;
		overflow-y: auto;
	}
</style>
