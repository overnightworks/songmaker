<script lang="ts">
	import { HOME_PAGE_LABEL } from '#lib/constants.ts';
	import HomeWrite from './HomeWrite.svelte';
	import HomeListen from './HomeListen.svelte';
	import NewPlaceMenu from './NewPlaceMenu.svelte';
</script>

<div class="library-home">
	<div class="home-titlebar">
		<h1 class="home-title">{HOME_PAGE_LABEL}</h1>
		<NewPlaceMenu />
	</div>
	<HomeListen />
	<HomeWrite />
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
		display: flex;
		flex-shrink: 0;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
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
