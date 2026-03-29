<!-- eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path -->
<script lang="ts">
	import LegalContent from '$lib/components/LegalContent.svelte';

	function goBack(): void {
		if (window.history.length > 1) {
			window.history.back();
		} else {
			window.location.href = '/login';
		}
	}
</script>

<svelte:head>
	<title>Legal | Hallucinai</title>
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
