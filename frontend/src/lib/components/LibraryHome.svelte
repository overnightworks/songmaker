<script lang="ts">
	import { HOME_PAGE_LABEL } from '$lib/constants';
	import LibraryContinue from './LibraryContinue.svelte';
</script>

<div class="library-home">
	<div class="home-titlebar">
		<h1 class="home-title">{HOME_PAGE_LABEL}</h1>
	</div>
	<LibraryContinue />
</div>

<style>
	.library-home {
		display: flex;
		flex: 1;
		flex-direction: column;
		min-width: 0;
		min-height: 0;
	}

	.home-titlebar {
		flex-shrink: 0;
		padding: 16px 20px 12px;
		border-bottom: 1px solid var(--border);
	}

	.home-title {
		margin: 0;
		color: var(--text);
		font-family: var(--font-display);
		font-size: 22px;
		letter-spacing: 1px;
		text-transform: uppercase;
	}

	@media (max-width: 768px) {
		.home-titlebar {
			padding: 10px 12px 6px;
		}
	}
</style>
